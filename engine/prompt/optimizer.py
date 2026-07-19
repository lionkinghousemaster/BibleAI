class PromptOptimizer:
    """對 PromptBuilder 組出來的分層 prompt 做兩件事：去除重複片語、依
    Priority 建立 Token Budget 並依此裁剪超出預算的分類。

    設計刻意保持單純：
    - 「token」用空白斷詞數近似（沒有引入額外的 CLIP/BPE tokenizer 相依套件），
      這是保守的估計方式，足以驅動「太長就裁剪」的保護機制，但不是精確的
      CLIP token 計數。
    - 去重以逗號分隔的片語為單位，保留每個片語第一次出現的位置，維持
      呼叫端傳入的分類順序（例如 Character > Environment > Lighting >
      Composition > Style）。
    - Priority／Token Budget：呼叫端（通常是 PromptBuilder）決定哪些分類
      是「保護分類」（`protected` 參數）——固定會是 Environment，以及
      Character 裡被標成 Main 的角色；其餘分類（Secondary／Background
      角色、Lighting、Composition、Style）都依 `category_weights` 的權重，
      把「扣掉保護分類之後剩下的預算」用瀑布式比例分配給每個分類——權重
      高的分類先按比例取得份額，若它本身不需要那麼多（內容較短），沒用完
      的預算會留給後面權重較低的分類，而不是被浪費掉。分配好預算後，每個
      分類各自裁到符合「自己的預算」，而不是像過去那樣不斷從某個分類尾端
      裁到「全域總長度」符合為止。這個 Optimizer 本身不知道「Character」
      「Main／Secondary／Background」這些概念是什麼——它只認得呼叫端傳入
      的 `(category, text)` 分類名稱與 `protected`／`category_weights`，
      Character Priority 完全是 PromptBuilder 那一層的邏輯。
    """

    DEFAULT_CATEGORY_WEIGHTS = {"lighting": 3, "composition": 2, "style": 1}

    def __init__(
        self,
        max_positive_tokens: int = 77,
        max_negative_tokens: int = 77,
        category_weights: dict = None,
    ):
        self.max_positive_tokens = max_positive_tokens
        self.max_negative_tokens = max_negative_tokens
        self.category_weights = dict(category_weights) if category_weights else dict(self.DEFAULT_CATEGORY_WEIGHTS)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """用空白斷詞數近似 token 數（不是精確的 CLIP tokenizer）。"""
        return len(text.split()) if text else 0

    @staticmethod
    def _split_phrases(text: str) -> list:
        if not text:
            return []
        return [phrase.strip() for phrase in text.split(",") if phrase.strip()]

    def dedupe(self, ordered_sections: list) -> tuple:
        """ordered_sections: [(category, text), ...]，依組裝順序排列。

        回傳 (去重後的 [(category, text), ...]，debug log 訊息列表)。
        重複片語只保留第一次出現的位置，之後（不論在同一分類或後面的
        分類）再出現同樣的片語（大小寫不敏感比對）一律移除。
        """
        seen = set()
        log = []
        result = []

        for category, text in ordered_sections:
            phrases = self._split_phrases(text)
            kept = []
            for phrase in phrases:
                key = phrase.lower()
                if key in seen:
                    log.append(f"[dedupe] {category}: 移除重複片語 \"{phrase}\"（先前的分類已出現過）")
                    continue
                seen.add(key)
                kept.append(phrase)
            result.append((category, ", ".join(kept)))

        return result, log

    def allocate_budget(
        self, ordered_sections: list, protected: set, total_budget: int, category_weights: dict = None
    ) -> dict:
        """依優先順序（ordered_sections 的順序）與 category_weights，把
        total_budget 分配給每個分類。protected 分類回傳 None（不限制，
        但仍會從總預算中扣掉它們實際佔用的 tokens）。

        `category_weights` 省略時使用建構時的 `self.category_weights`；
        呼叫端（例如 PromptBuilder 處理 Character Priority 時）可以傳入
        「這次呼叫專屬」的權重表——例如把特定 scene 裡 Secondary／
        Background 角色的權重併進來——而不需要影響這個 Optimizer 實例
        的預設權重。

        瀑布式分配：可裁剪分類依序處理，每個分類先算出「剩餘預算 × 自己
        權重 / 剩餘分類權重總和」的理論份額，實際分配則取
        min(自己的原始長度, 理論份額)——如果這個分類本身不需要那麼多，
        沒花完的預算會繼續留在池子裡，讓後面權重較低的分類也有機會
        分到比純比例計算更多的預算。
        """
        weights = category_weights if category_weights is not None else self.category_weights
        budgets = {}
        remaining = total_budget

        for category, text in ordered_sections:
            if category in protected:
                budgets[category] = None
                remaining -= self.estimate_tokens(text)

        remaining = max(0, remaining)

        trimmable = [(category, text) for category, text in ordered_sections if category not in protected]

        for index, (category, text) in enumerate(trimmable):
            weight = weights.get(category, 1)
            remaining_weight = sum(weights.get(c, 1) for c, _ in trimmable[index:])
            share = round(remaining * weight / remaining_weight) if remaining_weight else 0
            natural = self.estimate_tokens(text)
            allocated = min(natural, share)
            budgets[category] = allocated
            remaining -= allocated

        return budgets

    def enforce_length_budget(
        self, ordered_sections: list, protected: set, max_tokens: int, category_weights: dict = None
    ) -> tuple:
        """超過 max_tokens 時，依 Priority 建立的 Token Budget 裁剪各分類。

        流程：(1) 用 allocate_budget() 依優先順序算出每個非 protected 分類
        各自被分配到多少 token；(2) 每個分類各自裁到符合自己的預算——
        分類內部仍是從尾端裁起（沒有片語重要性模型可判斷該留哪一句），
        但「該裁到剩多少」是由分配好的預算決定，不是不斷從某個分類尾端
        砍到全域總長度符合為止。

        `category_weights` 見 allocate_budget()——省略時沿用建構時的
        `self.category_weights`。
        """
        log = []
        sections = dict(ordered_sections)
        order = [category for category, _ in ordered_sections]

        def joined_text() -> str:
            return ", ".join(sections[category] for category in order if sections.get(category))

        total_tokens = self.estimate_tokens(joined_text())
        if total_tokens <= max_tokens:
            return ordered_sections, log

        budgets = self.allocate_budget(ordered_sections, protected, max_tokens, category_weights=category_weights)

        log.append(f"[budget] Prompt 預估 {total_tokens} tokens，超過上限 {max_tokens}，依優先順序分配 token 預算：")
        for category in order:
            if category in protected:
                log.append(f"[budget]   {category}: 保護分類，不限制（不裁剪）")
            else:
                original = self.estimate_tokens(sections.get(category, ""))
                log.append(f"[budget]   {category}: 分配 {budgets.get(category, 0)} tokens（原本 {original} tokens）")

        for category in order:
            if category in protected:
                continue
            allocated = budgets.get(category, 0)
            phrases = self._split_phrases(sections.get(category, ""))
            while phrases and self.estimate_tokens(", ".join(phrases)) > allocated:
                dropped = phrases.pop()
                log.append(f"[trim] 裁剪 {category} 分類最後一個片語：\"{dropped}\"（超出分配的 {allocated} tokens 預算）")
            sections[category] = ", ".join(phrases)

        final_tokens = self.estimate_tokens(joined_text())
        if final_tokens > max_tokens:
            log.append(
                f"[budget] 依預算裁剪完後仍有 {final_tokens} tokens（上限 {max_tokens}）。"
                "保護分類（Environment、Main 角色）不會被裁剪，這是目前已知的上限——"
                "若場景本身角色多、敘事長，可考慮把非主要角色標成 Secondary／"
                "Background（見 PromptBuilder 的 Character Priority 機制）讓它們的"
                "描述先被裁剪，或縮短故事原文／角色描述才能進一步改善。"
            )

        return [(category, sections[category]) for category, _ in ordered_sections], log
