import json
import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """負責「依主題生成逐 scene 敘事內容」的抽象介面。

    與 ImageProvider（generate_image.py）、VoiceProvider（generate_voice.py）、
    VideoProvider（generate_video.py）風格一致：StoryGenerator 只依賴這個
    抽象介面組裝故事，不關心內容實際上是呼叫真正的 LLM API 產生，還是離線
    的假資料（DummyLLMProvider），兩者可以互換而不影響呼叫端。

    `context` 由 StoryGenerator 準備，包含這次生成可以使用的所有素材
    （角色、鏡頭、lighting/composition/style preset 的 id 與說明），確保
    Provider 只能從既有 characters/、camera/、prompts/ 資料中挑選，不會
    生成 stories/*.json 格式以外或指向不存在資產的內容。
    """

    @abstractmethod
    def generate_scenes(self, theme: str, context: dict) -> list:
        ...


class DummyLLMProvider(LLMProvider):
    """離線、不需要 API 金鑰的假生成器：依 context 提供的角色／鏡頭清單，
    以固定規則輪流組出 scene 草稿，用來在沒有 ANTHROPIC_API_KEY 時，也能
    驗證 StoryGenerator → batch_pipeline.py 的完整流程。

    輸出內容是明顯可辨識的 placeholder 文字（標註 "[Dummy]"），不是真正
    有意義的敘事——真正的內容生成交給 AnthropicProvider。
    """

    def generate_scenes(self, theme: str, context: dict) -> list:
        characters = context.get("characters", []) or [{"id": "god"}]
        cameras = context.get("cameras", []) or [{"id": "static"}]
        scene_count = context.get("scene_count", 6)

        scenes = []
        for index in range(scene_count):
            character = characters[index % len(characters)]
            camera = cameras[index % len(cameras)]
            character_name = character.get("name_zh") or character.get("id", "")

            scenes.append(
                {
                    "title": f"[Dummy] {theme} 第 {index + 1} 幕",
                    "characters": [character.get("id")] if character.get("id") else [],
                    "camera": camera.get("id"),
                    "narration_zh": f"（離線測試旁白）這是關於「{theme}」的第 {index + 1} 幕，{character_name}登場。",
                    "narration_en": f"(Offline test narration) Scene {index + 1} of '{theme}', featuring {character_name}.",
                    "image_prompt": f"a simple scene illustrating '{theme}', featuring {character_name}",
                    "animation_prompt": "gentle static hold, no camera movement, placeholder animation",
                    "subtitle": f"[Dummy] {theme}：第 {index + 1} 幕",
                    "duration": 10,
                }
            )

        return scenes


SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "characters": {"type": "array", "items": {"type": "string"}},
                    "camera": {"type": "string"},
                    "lighting": {"type": "string"},
                    "composition": {"type": "string"},
                    "style": {"type": "string"},
                    "narration_zh": {"type": "string"},
                    "narration_en": {"type": "string"},
                    "image_prompt": {"type": "string"},
                    "animation_prompt": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "duration": {"type": "integer"},
                },
                "required": [
                    "title",
                    "characters",
                    "camera",
                    "narration_zh",
                    "narration_en",
                    "image_prompt",
                    "animation_prompt",
                    "subtitle",
                    "duration",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["scenes"],
    "additionalProperties": False,
}


class AnthropicProvider(LLMProvider):
    """呼叫 Claude API（Anthropic 官方 `anthropic` Python SDK）依主題生成逐 scene
    內容，使用 structured outputs（`output_config.format`）確保回傳的 JSON
    直接符合 SCENE_SCHEMA，不需要自行解析或修剪自由格式文字。

    需要環境變數 ANTHROPIC_API_KEY（或已透過 `ant auth login` 設定好的
    憑證，SDK 會自動讀取）。model 預設 claude-opus-4-8。
    """

    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model

    def _build_prompt(self, theme: str, context: dict) -> str:
        characters = context.get("characters", [])
        cameras = context.get("cameras", [])
        lighting_presets = context.get("lighting_presets", [])
        composition_presets = context.get("composition_presets", [])
        style_presets = context.get("style_presets", [])
        scene_count = context.get("scene_count", 6)

        def describe(entries, id_key="id", label_keys=("description",)):
            lines = []
            for entry in entries:
                labels = " / ".join(str(entry.get(k, "")) for k in label_keys if entry.get(k))
                lines.append(f"- {entry.get(id_key)}: {labels}")
            return "\n".join(lines) if lines else "(無)"

        return f"""你是 BibleAI 兒童聖經故事影片的編劇。請根據主題產生 {scene_count} 個 scene，
    供自動化影片生成 pipeline 直接使用。

主題：{theme}
書卷：{context.get('book', '')}　章節：{context.get('chapter', '')}
集數：{context.get('episode', '')}　標題：{context.get('title_zh', '')} / {context.get('title_en', '')}

可用角色（characters 欄位只能填這些 id，一個 scene 可以有多個角色，也可以沒有）：
{describe(characters, label_keys=("name_zh", "description_zh"))}

可用鏡頭運動（camera 欄位必須是其中一個 id）：
{describe(cameras)}

可用 lighting preset（lighting 欄位可省略，省略時使用預設值）：
{describe(lighting_presets)}

可用 composition preset（composition 欄位可省略，省略時使用預設值）：
{describe(composition_presets)}

可用 style preset（style 欄位可省略，省略時使用預設值）：
{describe(style_presets)}

內容要求：
- narration_zh 為繁體中文旁白，narration_en 為對應英文翻譯，語氣溫暖、適合兒童，避免恐怖／暴力／成人內容。
- image_prompt 只需描述「這個 scene 的具體畫面內容」（場景、動作、構圖細節），不要重複寫繪本風格／材質等通用風格字詞
  （例如 watercolor、children's storybook illustration 這類字詞已經由獨立的 style preset 負責，不需要在這裡重複）。
- animation_prompt 描述鏡頭內的動態效果（光影、粒子、角色動作等）。
- subtitle 是字幕，通常是 narration 的精簡版（中文 + 英文各一行）。
- duration 是這個 scene 的預估秒數（整數，建議 8～15 秒）。
- characters 只能填「可用角色」清單中的 id；camera 只能填「可用鏡頭運動」清單中的 id。
"""

    def generate_scenes(self, theme: str, context: dict) -> list:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        prompt = self._build_prompt(theme, context)

        response = client.messages.parse(
            model=self.model,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": SCENE_SCHEMA}},
        )

        parsed = response.parsed_output
        if parsed is None:
            raise ValueError("AnthropicProvider: 回應內容不符合 SCENE_SCHEMA，無法解析出 scenes")

        if isinstance(parsed, dict):
            return parsed.get("scenes", [])
        return json.loads(parsed).get("scenes", [])
