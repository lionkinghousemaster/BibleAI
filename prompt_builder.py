from character_manager import CharacterManager
from prompt_library import PromptLibrary
from prompt_optimizer import PromptOptimizer


class PromptBuilder:
    """把 scene 資料組成分層的最終 prompt。

    PromptBuilder 本身不保存任何固定 Prompt 字串、分類清單，或權重設定——
    這些全部來自注入的 PromptLibrary（模板內容、預設 preset id、Token
    Budget 權重）與 CharacterManager（角色視覺描述）。PromptBuilder 只
    負責「依序組裝」與「呼叫 PromptOptimizer 去重/裁剪」，是純粹的組裝層。

    正向 prompt 依組裝優先順序疊 5 層（Character 最優先，Style 最低）：
      Character（透過 CharacterManager，依 scene["characters"] 查 visual_prompt)
      Environment（scene 既有的 image_prompt，逐場景手寫，不走模板）
      Lighting / Composition / Style（透過 PromptLibrary 讀取
      prompts/<category>/*.json 模板；scene 可用 scene["lighting"]／
      ["composition"]／["style"] 指定 preset id，省略時由 PromptLibrary
      依 prompts/manifest.json 決定預設值）
    負向 prompt 獨立一層，同樣透過 PromptLibrary（prompts/negative/*.json）。

    組好的分層在回傳前會先經過 PromptOptimizer：先去除跨分類重複的片語，
    再視需要依 Priority 分配 Token Budget、裁剪超出各自預算的內容——
    Character／Environment 是保護分類、永遠不限制／不裁剪，Lighting／
    Composition／Style 依 PromptLibrary 登記的權重分配剩餘預算，權重越高
    的分類 budget 不足時流失得越少。

    Character（CharacterManager）、Environment（scene["image_prompt"]）、
    Camera（CameraManager，屬於影片 pipeline，不在這裡）皆維持既有介面
    與 stories/*.json 格式不變，PromptBuilder 只是呼叫它們、不重新實作。

    設計風格與 CharacterManager / CameraManager 一致：任何一層模板找不到（分類
    資料夾不存在、preset id 找不到對應檔案）都只會讓那一層變成空字串並被跳過，
    不會丟例外，確保生成圖片的流程不受影響。
    """

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

    def build_positive_prompt_with_debug(self, scene: dict) -> tuple:
        """回傳 (最終正向 prompt, debug log 訊息列表)。"""
        character_prompt = self.build_character_prompt(scene.get("characters", []))
        environment_prompt = scene.get("image_prompt", "")
        lighting_prompt = self.prompt_library.get_text("lighting", scene.get("lighting"))
        composition_prompt = self.prompt_library.get_text("composition", scene.get("composition"))
        style_prompt = self.prompt_library.get_text("style", scene.get("style"))

        ordered_sections = [
            ("character", character_prompt),
            ("environment", environment_prompt),
            ("lighting", lighting_prompt),
            ("composition", composition_prompt),
            ("style", style_prompt),
        ]

        deduped_sections, dedupe_log = self.optimizer.dedupe(ordered_sections)
        trimmed_sections, trim_log = self.optimizer.enforce_length_budget(
            deduped_sections,
            protected={"character", "environment"},
            max_tokens=self.optimizer.max_positive_tokens,
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
        """回傳這個 scene 的 Prompt Engine 報告資料：各模組（去重/裁剪前的
        原始內容）的字元數、token 數、來源（preset 檔案路徑或 Manager
        名稱）與權重、最終正向/負向 prompt 的字元數與 token 數，以及
        去重／裁剪的完整 debug log，供 prompt_report.py 產生人工可讀的
        prompt_report.txt。
        """
        character_ids = scene.get("characters", []) or []
        character_prompt = self.build_character_prompt(character_ids)
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

        character_source = "CharacterManager ({})".format(", ".join(character_ids) if character_ids else "none")

        module_info = {
            "character": {
                "chars": len(character_prompt),
                "tokens": self.optimizer.estimate_tokens(character_prompt),
                "source": character_source,
                "weight": "protected",
            },
            "environment": {
                "chars": len(environment_prompt),
                "tokens": self.optimizer.estimate_tokens(environment_prompt),
                "source": "scene.image_prompt",
                "weight": "protected",
            },
            "lighting": {
                "chars": len(lighting_prompt),
                "tokens": self.optimizer.estimate_tokens(lighting_prompt),
                "source": f"prompts/lighting/{lighting_preset}.json",
                "weight": self.prompt_library.weight("lighting"),
            },
            "composition": {
                "chars": len(composition_prompt),
                "tokens": self.optimizer.estimate_tokens(composition_prompt),
                "source": f"prompts/composition/{composition_preset}.json",
                "weight": self.prompt_library.weight("composition"),
            },
            "style": {
                "chars": len(style_prompt),
                "tokens": self.optimizer.estimate_tokens(style_prompt),
                "source": f"prompts/style/{style_preset}.json",
                "weight": self.prompt_library.weight("style"),
            },
            "negative": {
                "chars": len(negative_prompt),
                "tokens": self.optimizer.estimate_tokens(negative_prompt),
                "source": f"prompts/negative/{negative_preset}.json",
                "weight": self.prompt_library.weight("negative"),
            },
        }

        return {
            "scene_number": scene.get("scene_number"),
            "module_info": module_info,
            "final_positive_chars": len(positive_prompt),
            "final_positive_tokens": self.optimizer.estimate_tokens(positive_prompt),
            "final_negative_chars": len(negative_prompt),
            "final_negative_tokens": self.optimizer.estimate_tokens(negative_prompt),
            "debug_log": positive_log + negative_log,
        }
