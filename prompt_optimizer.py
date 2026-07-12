class PromptOptimizer:
    """對 PromptBuilder 組出來的分層 prompt 做兩件事：去除重複片語、在超出
    token 預算時裁剪低優先級分類。

    設計刻意保持單純：
    - 「token」用空白斷詞數近似（沒有引入額外的 CLIP/BPE tokenizer 相依套件），
      這是保守的估計方式，足以驅動「太長就裁剪」的保護機制，但不是精確的
      CLIP token 計數。
    - 去重以逗號分隔的片語為單位，保留每個片語第一次出現的位置，維持
      呼叫端傳入的分類順序（例如 Character > Environment > Lighting >
      Composition > Style）。
    - 裁剪永遠不會處理 protected 分類（呼叫端指定，通常是 character 與
      environment），其餘分類依照呼叫端提供的優先順序，從最低優先開始，
      一個片語一個片語地從尾端裁掉，直到符合預算或該分類裁光為止。
    """

    def __init__(self, max_positive_tokens: int = 77, max_negative_tokens: int = 77):
        self.max_positive_tokens = max_positive_tokens
        self.max_negative_tokens = max_negative_tokens

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

    def enforce_length_budget(self, ordered_sections: list, protected: set, max_tokens: int) -> tuple:
        """超過 max_tokens 時，依 ordered_sections 由後到前的順序裁剪
        非 protected 分類（也就是排在越後面、優先級越低的分類越先被裁）。
        """
        log = []
        sections = dict(ordered_sections)
        order = [category for category, _ in ordered_sections]

        def joined_text() -> str:
            return ", ".join(sections[category] for category in order if sections.get(category))

        total_tokens = self.estimate_tokens(joined_text())
        if total_tokens <= max_tokens:
            return ordered_sections, log

        log.append(f"[trim] Prompt 預估 {total_tokens} tokens，超過上限 {max_tokens}，開始依優先順序裁剪")

        trimmable_categories = [category for category in reversed(order) if category not in protected]

        for category in trimmable_categories:
            phrases = self._split_phrases(sections.get(category, ""))
            while phrases and self.estimate_tokens(joined_text()) > max_tokens:
                dropped = phrases.pop()
                sections[category] = ", ".join(phrases)
                log.append(f"[trim] 裁剪 {category} 分類最後一個片語：\"{dropped}\"")

            if self.estimate_tokens(joined_text()) <= max_tokens:
                break

        final_tokens = self.estimate_tokens(joined_text())
        if final_tokens > max_tokens:
            log.append(
                f"[trim] 裁完所有可裁剪分類後仍有 {final_tokens} tokens（上限 {max_tokens}）。"
                "Character／Environment 為保護分類、不會被裁剪，這是目前已知的上限，"
                "需要縮短故事原文或角色描述才能進一步改善。"
            )

        return [(category, sections[category]) for category, _ in ordered_sections], log
