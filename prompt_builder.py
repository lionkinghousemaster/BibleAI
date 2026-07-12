import json
from abc import ABC, abstractmethod
from pathlib import Path

from character_manager import CharacterManager


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

    正向 prompt 依序疊 5 層：
      Environment（scene 既有的 image_prompt，逐場景手寫，不走模板）
      Character（透過 CharacterManager，依 scene["characters"] 查 visual_prompt）
      Lighting / Composition / Style（透過 prompts/<category>/*.json 模板，
      預設都用 "default"，scene 可用 scene["lighting"]／["composition"]／["style"]
      指定其他 preset id）
    負向 prompt 獨立一層，來自 prompts/negative/*.json。

    設計風格與 CharacterManager / CameraManager 一致：任何一層模板找不到（分類
    資料夾不存在、preset id 找不到對應檔案）都只會讓那一層變成空字串並被跳過，
    不會丟例外，確保生成圖片的流程不受影響。
    """

    def __init__(self, character_manager: CharacterManager = None, prompt_provider: PromptProvider = None):
        self.character_manager = character_manager or CharacterManager()
        self.prompt_provider = prompt_provider or JSONPromptProvider()

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

    def build_positive_prompt(self, scene: dict) -> str:
        environment_prompt = scene.get("image_prompt", "")
        character_prompt = self.build_character_prompt(scene.get("characters", []))
        lighting_prompt = self._get_template_text("lighting", scene.get("lighting", "default"))
        composition_prompt = self._get_template_text("composition", scene.get("composition", "default"))
        style_prompt = self._get_template_text("style", scene.get("style", "default"))

        sections = [environment_prompt, character_prompt, lighting_prompt, composition_prompt, style_prompt]
        sections = [section for section in sections if section]
        return ", ".join(sections)

    def build_negative_prompt(self, scene: dict = None) -> str:
        scene = scene or {}
        return self._get_template_text("negative", scene.get("negative", "default"))
