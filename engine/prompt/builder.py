from character_manager import CharacterManager

from .library import PromptLibrary
from .optimizer import PromptOptimizer


class PromptBuilder:
    """把 scene 資料組成分層的最終 prompt。

    PromptBuilder 本身不保存任何固定 Prompt 字串、分類清單，或權重設定——
    這些全部來自注入的 PromptLibrary（模板內容、預設 preset id、Token
    Budget 權重）與 CharacterManager（角色視覺描述）。PromptBuilder 只
    負責「依序組裝」與「呼叫 PromptOptimizer 去重/裁剪」，是純粹的組裝層。

    正向 prompt 依組裝優先順序疊層（每個角色各自一層，Style 最低）：
      Character（透過 CharacterManager，依 scene["characters"] 逐一查
      visual_prompt，每個角色各自成為一個獨立分類，見 Character Priority）
      Environment（scene 既有的 image_prompt，逐場景手寫，不走模板）
      Lighting / Composition / Style（透過 PromptLibrary 讀取
      prompts/<category>/*.json 模板；scene 可用 scene["lighting"]／
      ["composition"]／["style"] 指定 preset id，省略時由 PromptLibrary
      依 prompts/manifest.json 決定預設值）
    負向 prompt 獨立一層，同樣透過 PromptLibrary（prompts/negative/*.json）。

    Character Priority 機制：token 預算不足時，不再是「Character 整體
    保護、Lighting/Composition/Style 固定挨刀」的寫死規則，而是依「這個
    角色在這個 scene 裡的重要程度」決定：
      - `main`　　　：保護分類，永遠不裁剪（跟 Environment 同等級）。
      - `secondary`：可裁剪，權重由 `prompts/manifest.json` 的
        `character_priority_weights.secondary` 決定（預設 3，跟
        Lighting 同量級——通常會比 Style 存活更多內容）。
      - `background`：可裁剪，權重同上的 `.background`（預設 1，跟
        Style 同量級，優先被裁）。
    tier 的決定順序：先看 scene 是否有 `scene["character_priority"]`
    （`{character_id: tier}` 的 dict，可以只覆寫部分角色），沒指定的角色
    再套用預設規則——scene["characters"] 裡第一個角色預設 `main`，其餘
    預設 `secondary`（多數 scene 只有一個角色，這條預設規則等同「整個
    Character 都保護」的舊行為，不影響既有單角色 scene）。無效或未知的
    tier 字串一律視為 `secondary`，不丟例外。

    組好的分層在回傳前會先經過 PromptOptimizer：先去除跨分類重複的片語，
    再依 Priority（Environment／Main 角色保護；Secondary／Background
    角色與 Lighting／Composition／Style 依權重）分配 Token Budget、裁剪
    超出各自預算的內容。

    Character（CharacterManager）、Environment（scene["image_prompt"]）、
    Camera（CameraManager，屬於影片 pipeline，不在這裡）皆維持既有介面
    與 stories/*.json 格式不變，PromptBuilder 只是呼叫它們、不重新實作；
    `scene["character_priority"]` 是唯一新增的（可選）欄位，省略時行為
    與加入這個機制之前完全一致。

    設計風格與 CharacterManager / CameraManager 一致：任何一層模板找不到（分類
    資料夾不存在、preset id 找不到對應檔案）都只會讓那一層變成空字串並被跳過，
    不會丟例外，確保生成圖片的流程不受影響。
    """

    VALID_TIERS = {"main", "secondary", "background"}
    DEFAULT_SECONDARY_TIER = "secondary"

    def __init__(
        self,
        character_manager: CharacterManager = None,
        prompt_library: PromptLibrary = None,
        optimizer: PromptOptimizer = None,
    ):
        self.character_manager = character_manager or CharacterManager()
        self.prompt_library = prompt_library or PromptLibrary()
        self.optimizer = optimizer or PromptOptimizer(category_weights=self.prompt_library.category_weights())

    def build_character_prompt(self, character_ids: list) -> str:
        fragments = [self.character_manager.get_visual_prompt(cid) for cid in (character_ids or [])]
        fragments = [fragment for fragment in fragments if fragment]
        return ", ".join(fragments)

    def resolve_character_priorities(self, scene: dict) -> dict:
        """回傳這個 scene 裡每個角色的 tier（`main`／`secondary`／
        `background`）。

        優先套用 scene["character_priority"]（`{character_id: tier}`，
        可以只覆寫部分角色）；沒被覆寫的角色，第一個（scene["characters"]
        裡的順序）預設 `main`，其餘預設 `secondary`。未知或無效的 tier
        字串一律視為 `secondary`，不丟例外——這樣就算 story JSON 裡打錯字
        （例如打成 "Secondary" 或 "extra"），也只會退回可裁剪、不影響
        整個 pipeline。
        """
        character_ids = scene.get("characters", []) or []
        overrides = scene.get("character_priority", {}) or {}

        priorities = {}
        for index, character_id in enumerate(character_ids):
            tier = overrides.get(character_id)
            if tier not in self.VALID_TIERS:
                tier = "main" if index == 0 else self.DEFAULT_SECONDARY_TIER
            priorities[character_id] = tier

        return priorities

    def _character_sections(self, scene: dict) -> tuple:
        """回傳 (character_sections, protected_character_categories, character_weights)。

        character_sections：[(category, text), ...]，每個角色各自一筆，
        category 統一用 `character:{character_id}` 命名，跟 Environment／
        Lighting／Composition／Style 的分類名稱空間分開，不會互相碰撞。
        找不到 visual_prompt（CharacterManager 回傳空字串）的角色直接跳過，
        不佔用任何預算，也不會出現在報告裡。
        """
        character_ids = scene.get("characters", []) or []
        priorities = self.resolve_character_priorities(scene)

        sections = []
        protected_categories = set()
        weights = {}

        for character_id in character_ids:
            visual_prompt = self.character_manager.get_visual_prompt(character_id)
            if not visual_prompt:
                continue

            category = f"character:{character_id}"
            sections.append((category, visual_prompt))

            tier = priorities.get(character_id, "main")
            if tier == "main":
                protected_categories.add(category)
            else:
                weights[category] = self.prompt_library.character_priority_weight(tier)

        return sections, protected_categories, weights

    def build_positive_prompt_with_debug(self, scene: dict) -> tuple:
        """回傳 (最終正向 prompt, debug log 訊息列表)。"""
        character_sections, protected_characters, character_weights = self._character_sections(scene)

        environment_prompt = scene.get("image_prompt", "")
        lighting_prompt = self.prompt_library.get_text("lighting", scene.get("lighting"))
        composition_prompt = self.prompt_library.get_text("composition", scene.get("composition"))
        style_prompt = self.prompt_library.get_text("style", scene.get("style"))

        ordered_sections = character_sections + [
            ("environment", environment_prompt),
            ("lighting", lighting_prompt),
            ("composition", composition_prompt),
            ("style", style_prompt),
        ]

        protected = {"environment"} | protected_characters
        category_weights = dict(self.prompt_library.category_weights())
        category_weights.update(character_weights)

        deduped_sections, dedupe_log = self.optimizer.dedupe(ordered_sections)
        trimmed_sections, trim_log = self.optimizer.enforce_length_budget(
            deduped_sections,
            protected=protected,
            max_tokens=self.optimizer.max_positive_tokens,
            category_weights=category_weights,
        )

        final_prompt = ", ".join(text for _, text in trimmed_sections if text)
        return final_prompt, dedupe_log + trim_log

    def build_positive_prompt(self, scene: dict) -> str:
        final_prompt, _debug_log = self.build_positive_prompt_with_debug(scene)
        return final_prompt

    def build_negative_prompt_with_debug(self, scene: dict = None) -> tuple:
        """回傳 (最終負向 prompt, debug log 訊息列表)。"""
        scene = scene or {}
        negative_prompt = self.prompt_library.get_text("negative", scene.get("negative"))

        deduped_sections, dedupe_log = self.optimizer.dedupe([("negative", negative_prompt)])
        trimmed_sections, trim_log = self.optimizer.enforce_length_budget(
            deduped_sections,
            protected=set(),
            max_tokens=self.optimizer.max_negative_tokens,
        )

        final_negative = trimmed_sections[0][1] if trimmed_sections else ""
        return final_negative, dedupe_log + trim_log

    def build_negative_prompt(self, scene: dict = None) -> str:
        final_negative, _debug_log = self.build_negative_prompt_with_debug(scene)
        return final_negative

    def build_prompt_report_entry(self, scene: dict) -> dict:
        """回傳這個 scene 的 Prompt Engine 報告資料：每個角色（依 Character
        Priority 分出的 tier／權重）與 Environment／Lighting／Composition／
        Style 各自（去重/裁剪前的原始內容）的字元數、token 數、來源
        （preset 檔案路徑或 Manager 名稱）與權重、最終正向/負向 prompt 的
        字元數與 token 數，以及去重／裁剪的完整 debug log，供
        engine/prompt/report.py 產生人工可讀的 prompt_report.txt。
        """
        character_ids = [
            cid for cid in (scene.get("characters", []) or []) if self.character_manager.get_visual_prompt(cid)
        ]
        priorities = self.resolve_character_priorities(scene)
        environment_prompt = scene.get("image_prompt", "")

        lighting_preset = self.prompt_library.resolve_preset_id("lighting", scene.get("lighting"))
        composition_preset = self.prompt_library.resolve_preset_id("composition", scene.get("composition"))
        style_preset = self.prompt_library.resolve_preset_id("style", scene.get("style"))
        negative_preset = self.prompt_library.resolve_preset_id("negative", scene.get("negative"))

        lighting_prompt = self.prompt_library.get_text("lighting", scene.get("lighting"))
        composition_prompt = self.prompt_library.get_text("composition", scene.get("composition"))
        style_prompt = self.prompt_library.get_text("style", scene.get("style"))

        positive_prompt, positive_log = self.build_positive_prompt_with_debug(scene)
        negative_prompt, negative_log = self.build_negative_prompt_with_debug(scene)

        module_info = {}
        for character_id in character_ids:
            visual_prompt = self.character_manager.get_visual_prompt(character_id)
            tier = priorities.get(character_id, "main")
            weight = "protected" if tier == "main" else self.prompt_library.character_priority_weight(tier)
            module_info[f"character:{character_id}"] = {
                "chars": len(visual_prompt),
                "tokens": self.optimizer.estimate_tokens(visual_prompt),
                "source": f"CharacterManager ({character_id}, {tier})",
                "weight": weight,
            }

        module_info["environment"] = {
            "chars": len(environment_prompt),
            "tokens": self.optimizer.estimate_tokens(environment_prompt),
            "source": "scene.image_prompt",
            "weight": "protected",
        }
        module_info["lighting"] = {
            "chars": len(lighting_prompt),
            "tokens": self.optimizer.estimate_tokens(lighting_prompt),
            "source": f"prompts/lighting/{lighting_preset}.json",
            "weight": self.prompt_library.weight("lighting"),
        }
        module_info["composition"] = {
            "chars": len(composition_prompt),
            "tokens": self.optimizer.estimate_tokens(composition_prompt),
            "source": f"prompts/composition/{composition_preset}.json",
            "weight": self.prompt_library.weight("composition"),
        }
        module_info["style"] = {
            "chars": len(style_prompt),
            "tokens": self.optimizer.estimate_tokens(style_prompt),
            "source": f"prompts/style/{style_preset}.json",
            "weight": self.prompt_library.weight("style"),
        }
        module_info["negative"] = {
            "chars": len(negative_prompt),
            "tokens": self.optimizer.estimate_tokens(negative_prompt),
            "source": f"prompts/negative/{negative_preset}.json",
            "weight": self.prompt_library.weight("negative"),
        }

        return {
            "scene_number": scene.get("scene_number"),
            "character_ids": character_ids,
            "module_info": module_info,
            "final_positive_chars": len(positive_prompt),
            "final_positive_tokens": self.optimizer.estimate_tokens(positive_prompt),
            "final_negative_chars": len(negative_prompt),
            "final_negative_tokens": self.optimizer.estimate_tokens(negative_prompt),
            "debug_log": positive_log + negative_log,
        }
