from character_manager import CharacterManager
from camera_manager import CameraManager

from engine.prompt import PromptLibrary

from .llm_provider import DummyLLMProvider, LLMProvider


class StoryGenerator:
    """依主題自動產生符合 `stories/*.json` 格式的故事。

    StoryGenerator 本身不生成敘事內容——那是注入的 LLMProvider 的責任
    （見 llm_provider.py）。StoryGenerator 只負責三件事：
      1. 把 CharacterManager／CameraManager／PromptLibrary 目前有哪些
         可用的角色、鏡頭運動、lighting/composition/style preset 組成
         context，交給 LLMProvider 生成 scene 草稿。
      2. 驗證 LLMProvider 回傳的每個 scene：character/camera/lighting/
         composition/style id 若不是既有資產就回退成安全預設值（不丟
         例外），duration 轉成合法正整數，並依序補上 scene_number。
      3. 組成與 `stories/Genesis_001.json` 完全相同結構的故事 dict
         （episode/book/chapter/title_zh/title_en/duration/language/
         scenes），可以直接存成 JSON 交給 batch_pipeline.py 處理，也可以
         直接被 engine.prompt.PromptBuilder／CameraManager 消費，不需要
         任何額外轉換。

    找不到 characters/、camera/、prompts/ 資產時的容錯風格與
    CharacterManager／CameraManager／PromptLibrary 一致：安靜地回退成
    預設值，不中斷整個生成流程。
    """

    def __init__(
        self,
        llm_provider: LLMProvider = None,
        character_manager: CharacterManager = None,
        camera_manager: CameraManager = None,
        prompt_library: PromptLibrary = None,
    ):
        self.llm_provider = llm_provider or DummyLLMProvider()
        self.character_manager = character_manager or CharacterManager()
        self.camera_manager = camera_manager or CameraManager()
        self.prompt_library = prompt_library or PromptLibrary()

    def _describe_presets(self, category: str) -> list:
        presets = self.prompt_library.load_all(category)
        return [{"id": preset_id, "description": data.get("description", "")} for preset_id, data in presets.items()]

    def _build_context(self, book: str, chapter: str, episode: str, title_zh: str, title_en: str, scene_count: int) -> dict:
        characters = self.character_manager.list_characters()
        character_list = [
            {
                "id": character_id,
                "name_zh": data.get("name_zh", ""),
                "name_en": data.get("name_en", ""),
                "description_zh": data.get("description_zh", ""),
                "description_en": data.get("description_en", ""),
            }
            for character_id, data in characters.items()
        ]

        cameras = self.camera_manager.list_cameras()
        camera_list = [
            {
                "id": camera_id,
                "description": data.get("description", ""),
                "type": data.get("type", ""),
                "direction": data.get("direction", ""),
            }
            for camera_id, data in cameras.items()
        ]

        return {
            "book": book,
            "chapter": chapter,
            "episode": episode,
            "title_zh": title_zh,
            "title_en": title_en,
            "scene_count": scene_count,
            "characters": character_list,
            "cameras": camera_list,
            "lighting_presets": self._describe_presets("lighting"),
            "composition_presets": self._describe_presets("composition"),
            "style_presets": self._describe_presets("style"),
        }

    def generate(
        self,
        theme: str,
        episode: str,
        book: str,
        chapter: str,
        title_zh: str,
        title_en: str,
        scene_count: int = 6,
        language: list = None,
    ) -> dict:
        context = self._build_context(book, chapter, episode, title_zh, title_en, scene_count)
        raw_scenes = self.llm_provider.generate_scenes(theme, context)

        valid_character_ids = set(self.character_manager.list_characters().keys())
        valid_camera_ids = set(self.camera_manager.list_cameras().keys())
        default_camera_id = next(iter(sorted(valid_camera_ids)), "static")
        valid_lighting_ids = {preset["id"] for preset in context["lighting_presets"]}
        valid_composition_ids = {preset["id"] for preset in context["composition_presets"]}
        valid_style_ids = {preset["id"] for preset in context["style_presets"]}

        scenes = []
        total_seconds = 0
        for scene_number, raw_scene in enumerate(raw_scenes, start=1):
            scene = self._normalize_scene(
                raw_scene,
                scene_number,
                valid_character_ids,
                valid_camera_ids,
                default_camera_id,
                valid_lighting_ids,
                valid_composition_ids,
                valid_style_ids,
            )
            total_seconds += scene["duration"]
            scenes.append(scene)

        return {
            "episode": episode,
            "book": book,
            "chapter": chapter,
            "title_zh": title_zh,
            "title_en": title_en,
            "duration": self._format_duration(total_seconds),
            "language": language or ["zh-TW", "en"],
            "scenes": scenes,
        }

    def _normalize_scene(
        self,
        raw_scene: dict,
        scene_number: int,
        valid_character_ids: set,
        valid_camera_ids: set,
        default_camera_id: str,
        valid_lighting_ids: set,
        valid_composition_ids: set,
        valid_style_ids: set,
    ) -> dict:
        characters = [
            character_id for character_id in raw_scene.get("characters", []) if character_id in valid_character_ids
        ]

        camera = raw_scene.get("camera")
        if camera not in valid_camera_ids:
            camera = default_camera_id

        scene = {
            "scene_number": scene_number,
            "title": raw_scene.get("title") or f"Scene {scene_number}",
            "characters": characters,
            "camera": camera,
            "narration_zh": raw_scene.get("narration_zh", ""),
            "narration_en": raw_scene.get("narration_en", ""),
            "image_prompt": raw_scene.get("image_prompt", ""),
            "animation_prompt": raw_scene.get("animation_prompt", ""),
            "subtitle": raw_scene.get("subtitle", ""),
            "duration": self._normalize_duration(raw_scene.get("duration")),
        }

        lighting = raw_scene.get("lighting")
        if lighting in valid_lighting_ids:
            scene["lighting"] = lighting

        composition = raw_scene.get("composition")
        if composition in valid_composition_ids:
            scene["composition"] = composition

        style = raw_scene.get("style")
        if style in valid_style_ids:
            scene["style"] = style

        return scene

    @staticmethod
    def _normalize_duration(value) -> int:
        try:
            duration = int(value)
        except (TypeError, ValueError):
            return 10
        return duration if duration > 0 else 10

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        minutes, seconds = divmod(max(total_seconds, 0), 60)
        return f"{minutes:02d}:{seconds:02d}"
