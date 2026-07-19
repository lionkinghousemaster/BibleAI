from character_manager import CharacterManager

from .importance import resolve_character_importance
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
      visual_prompt，每個角色各自成為一個獨立分類，見 Story Intelligence）
      Environment（scene 既有的 image_prompt，逐場景手寫，不走模板）
      Lighting / Composition / Style（透過 PromptLibrary 讀取
      prompts/<category>/*.json 模板；scene 可用 scene["lighting"]／
      ["composition"]／["style"] 指定 preset id，省略時由 PromptLibrary
      依 prompts/manifest.json 決定預設值）
    負向 prompt 獨立一層，同樣透過 PromptLibrary（prompts/negative/*.json）。

    Story Intelligence（importance_score）機制：token 預算不足時，不再是
    固定的三段式 Priority（main/secondary/background），而是依
    `engine.prompt.importance` 算出的連續分數（0.0～1.0）決定每個角色該
    保護多少：
      - `importance_score >= MAIN_IMPORTANCE_THRESHOLD`（預設 0.75）：
        視為保護分類，永遠不裁剪（跟 Environment 同等級）。
      - 其餘：可裁剪，權重 = `max(1, round(importance_score * 10))`——
        分數越高，budget 不足時流失得越少，而不是像三段式 Priority 那樣
        只有三種固定權重可選。
    importance_score 的來源（見 `resolve_character_importance`）：scene
    可用 `scene["character_importance"]`（`{character_id: 0.0~1.0}`）
    明確覆寫；沒覆寫的角色會嘗試沿用 v0.9 Token Allocation Sprint 的
    `scene["character_priority"]` 三段式 tier（向下相容）；兩者都沒有時，
    現場依「是否為主角／是否有台詞／是否有動作／是否為情節核心」四個
    信號加總計算——單角色 scene 固定視為 1.0（見 importance.py）。

    組好的分層在回傳前會先經過 PromptOptimizer：先去除跨分類重複的片語，
    再依 Priority（Environment／高分角色保護；其餘角色與 Lighting／
    Composition／Style 依權重）分配 Token Budget、裁剪超出各自預算的內容。

    Character（CharacterManager）、Environment（scene["image_prompt"]）、
    Camera（CameraManager，屬於影片 pipeline，不在這裡）皆維持既有介面
    與 stories/*.json 格式不變，PromptBuilder 只是呼叫它們、不重新實作；
    `scene["character_importance"]`／`scene["character_priority"]` 都是
    可選欄位，省略時行為與加入這個機制之前完全一致。

    設計風格與 CharacterManager / CameraManager 一致：任何一層模板找不到（分類
    資料夾不存在、preset id 找不到對應檔案）都只會讓那一層變成空字串並被跳過，
    不會丟例外，確保生成圖片的流程不受影響。
    """

    MAIN_IMPORTANCE_THRESHOLD = 0.75

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

    #: importance_score 換算權重的縮放係數。跟 Lighting(3)/Composition(2)/
    #: Style(1) 同一個量級（0.0～1.0 分換算成約 0～5），故意不用更大的
    #: 縮放倍率——實測（Genesis_001 scene 9／11 三角色同場）發現縮放倍率
    #: 太大時，高分角色會把權重拉開到跟 Lighting/Composition 不成比例，
    #: budget 不足時會把 Lighting/Composition 直接擠到 0，重現「角色完全
    #: 保護、其餘全部挨刀」的舊問題；縮放到跟其他分類同量級才能讓所有
    #: 可裁剪分類公平競爭剩餘預算。
    IMPORTANCE_WEIGHT_SCALE = 5

    @classmethod
    def weight_from_importance(cls, importance_score: float) -> int:
        """把 0.0～1.0 的 importance_score 換算成 PromptOptimizer 用的整數
        權重——分數越高權重越大，budget 不足時流失得越少。下限 1（避免
        權重 0 造成分配時被完全忽略）。
        """
        return max(1, round(importance_score * cls.IMPORTANCE_WEIGHT_SCALE))

    def _character_sections(self, scene: dict) -> tuple:
        """回傳 (character_sections, protected_character_categories,
        character_weights, importance_by_character)。

        character_sections：[(category, text), ...]，每個角色各自一筆，
        category 統一用 `character:{character_id}` 命名，跟 Environment／
        Lighting／Composition／Style 的分類名稱空間分開，不會互相碰撞。
        找不到 visual_prompt（CharacterManager 回傳空字串）的角色直接跳過，
        不佔用任何預算，也不會出現在報告裡。

        importance_by_character：`{character_id: resolve_character_importance() 的完整回傳值}`，
        供 build_prompt_report_entry 產生 prompt_report.txt 用。
        """
        character_ids = scene.get("characters", []) or []

        sections = []
        protected_categories = set()
        weights = {}
        importance_by_character = {}

        for character_id in character_ids:
            visual_prompt = self.character_manager.get_visual_prompt(character_id)
            if not visual_prompt:
                continue

            category = f"character:{character_id}"
            sections.append((category, visual_prompt))

            character_data = self.character_manager.get_character(character_id)
            importance = resolve_character_importance(character_id, character_data, scene)
            importance_by_character[character_id] = importance

            if importance["importance_score"] >= self.MAIN_IMPORTANCE_THRESHOLD:
                protected_categories.add(category)
            else:
                weights[category] = self.weight_from_importance(importance["importance_score"])

        return sections, protected_categories, weights, importance_by_character

    def build_positive_prompt_with_debug(self, scene: dict) -> tuple:
        """回傳 (最終正向 prompt, debug log 訊息列表)。"""
        character_sections, protected_characters, character_weights, _importance = self._character_sections(scene)

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
        """回傳這個 scene 的 Prompt Engine 報告資料：每個角色的
        importance_score（含四個原始信號與來源）與實際分配到的權重／
        token 數，以及 Environment／Lighting／Composition／Style 各自
        （去重/裁剪前的原始內容）的字元數、token 數、來源、權重、最終
        正向/負向 prompt 的字元數與 token 數，以及去重／裁剪的完整
        debug log，供 engine/prompt/report.py 產生人工可讀的
        prompt_report.txt，方便分析「這個角色的描述長度為什麼是這樣」。
        """
        character_sections, protected_characters, _weights, importance_by_character = self._character_sections(
            scene
        )
        character_ids = [category.split(":", 1)[1] for category, _ in character_sections]

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
            importance = importance_by_character.get(character_id, {})
            category = f"character:{character_id}"
            score = importance.get("importance_score", 0.0)
            weight = "protected" if category in protected_characters else self.weight_from_importance(score)
            signals = [
                name
                for name in ("is_main", "is_plot_core", "has_action", "has_dialogue")
                if importance.get(name)
            ]
            module_info[category] = {
                "chars": len(visual_prompt),
                "tokens": self.optimizer.estimate_tokens(visual_prompt),
                "source": f"CharacterManager ({character_id}, source={importance.get('source', 'heuristic')})",
                "weight": weight,
                "importance_score": score,
                "signals": signals,
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
