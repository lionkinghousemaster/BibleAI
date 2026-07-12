import json
from abc import ABC, abstractmethod
from pathlib import Path

from character_manager import CharacterManager
from prompt_optimizer import PromptOptimizer


class PromptProvider(ABC):
    @abstractmethod
    def load_all(self, category: str) -> dict:
        ...

    @abstractmethod
    def get(self, category: str, prompt_id: str) -> dict | None:
        ...


class JSONPromptProvider(PromptProvider):
    """從 prompts/<category>/*.json 讀取 prompt 模板（一個模板一個檔案，檔名即 prompt_id）。"""

    def __init__(self, prompts_dir: Path = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else Path(__file__).parent / "prompts"

    def load_all(self, category: str) -> dict:
        category_dir = self.prompts_dir / category
        prompts = {}
        if not category_dir.exists():
            return prompts

        for file_path in sorted(category_dir.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            prompt_id = data.get("id", file_path.stem)
            prompts[prompt_id] = data

        return prompts

    def get(self, category: str, prompt_id: str) -> dict | None:
        file_path = self.prompts_dir / category / f"{prompt_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


class PromptBuilder:
    """把 scene 資料組成分層的最終 prompt。

    正向 prompt 依組裝優先順序疊 5 層（Character 最優先，Style 最低）：
      Character（透過 CharacterManager，依 scene["characters"] 查 visual_prompt)
      Environment（scene 既有的 image_prompt，逐場景手寫，不走模板）
      Lighting / Composition / Style（透過 prompts/<category>/*.json 模板，
      預設都用 "default"，scene 可用 scene["lighting"]／["composition"]／["style"]
      指定其他 preset id）
    負向 prompt 獨立一層，來自 prompts/negative/*.json。

    組好的分層在回傳前會先經過 PromptOptimizer：先去除跨分類重複的片語，
    再視需要裁剪 token 預算內放不下的內容——Character／Environment 是保護
    分類、永遠不會被裁剪，只會裁 Lighting／Composition／Style（依此由低到高
    優先順序裁剪）。

    設計風格與 CharacterManager / CameraManager 一致：任何一層模板找不到（分類
    資料夾不存在、preset id 找不到對應檔案）都只會讓那一層變成空字串並被跳過，
    不會丟例外，確保生成圖片的流程不受影響。
    """

    def __init__(
        self,
        character_manager: CharacterManager = None,
        prompt_provider: PromptProvider = None,
        optimizer: PromptOptimizer = None,
    ):
        self.character_manager = character_manager or CharacterManager()
        self.prompt_provider = prompt_provider or JSONPromptProvider()
        self.optimizer = optimizer or PromptOptimizer()

    def _get_template_text(self, category: str, prompt_id: str) -> str:
        if not prompt_id:
            return ""
        data = self.prompt_provider.get(category, prompt_id)
        if not data:
            return ""
        return data.get("prompt", "")

    def build_character_prompt(self, character_ids: list) -> str:
        fragments = [self.character_manager.get_visual_prompt(cid) for cid in (character_ids or [])]
        fragments = [fragment for fragment in fragments if fragment]
        return ", ".join(fragments)

    def build_positive_prompt_with_debug(self, scene: dict) -> tuple:
        """回傳 (最終正向 prompt, debug log 訊息列表)。"""
        character_prompt = self.build_character_prompt(scene.get("characters", []))
        environment_prompt = scene.get("image_prompt", "")
        lighting_prompt = self._get_template_text("lighting", scene.get("lighting", "default"))
        composition_prompt = self._get_template_text("composition", scene.get("composition", "default"))
        style_prompt = self._get_template_text("style", scene.get("style", "default"))

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
        negative_prompt = self._get_template_text("negative", scene.get("negative", "default"))

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
