from abc import ABC, abstractmethod
from pathlib import Path


class VoiceProvider(ABC):
    @abstractmethod
    def generate(
        self,
        text: str,
        output_path: Path,
        language: str = "zh-TW",
        voice: str | None = None,
    ) -> Path:
        ...


class DummyVoiceProvider(VoiceProvider):
    """假語音生成器：建立同名 .txt 檔案代表語音生成成功，不產生真正的語音。"""

    def generate(
        self,
        text: str,
        output_path: Path,
        language: str = "zh-TW",
        voice: str | None = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        txt_path = output_path.with_suffix(".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)

        return output_path


# edge-tts 是免費、不需要金鑰的服務，但公開 API 只支援 rate/pitch/volume 這幾個
# prosody 參數；經實測，直接注入原生 <break>/<emphasis> SSML 標籤會被服務端拒絕
# （NoAudioReceived），所以這裡不假裝支援真正的逐字級 SSML。rate/pitch 是真正生效的
# 官方參數；break 由 enhance_narration() 在文字中插入自然停頓標點來模擬；emphasis
# 目前無法在不接付費 API（如 Azure Speech SDK）的前提下實現，先保留在設定中備用。
EMOTION_PRESETS = {
    "none": {"rate": "+0%", "pitch": "+0Hz", "break": "none", "emphasis": "none"},
    "warm": {"rate": "-5%", "pitch": "+8Hz", "break": "short", "emphasis": "moderate"},
    "calm": {"rate": "-12%", "pitch": "-5Hz", "break": "medium", "emphasis": "none"},
    "joyful": {"rate": "+12%", "pitch": "+18Hz", "break": "short", "emphasis": "strong"},
    "mysterious": {"rate": "-15%", "pitch": "-12Hz", "break": "long", "emphasis": "moderate"},
    "sad": {"rate": "-18%", "pitch": "-15Hz", "break": "medium", "emphasis": "reduced"},
}

# Voice Style：朗讀「場合／對象」風格，與 emotion（情緒）是獨立的兩個維度，
# 兩者的 rate/pitch 會疊加、break 停頓強度取兩者較強的一邊。
# "story" 是中性預設值，rate/pitch/break 皆為零調整，確保沒有指定 style 時
# 行為與加入 style 之前完全一致（向下相容 voice / emotion）。
STYLE_PRESETS = {
    "story": {"rate": "+0%", "pitch": "+0Hz", "break": "none"},
    "bedtime": {"rate": "-15%", "pitch": "-10Hz", "break": "long"},
    "children": {"rate": "+5%", "pitch": "+12Hz", "break": "medium"},
}

_SENTENCE_END_PUNCT = "。！？"
_CLAUSE_END_PUNCT = "，、；："

_SENTENCE_PAUSE_BY_BREAK = {"none": "", "short": "", "medium": "…", "long": "……"}
_CLAUSE_PAUSE_BY_BREAK = {"none": "", "short": "…", "medium": "…", "long": "……"}

_BREAK_TIER_ORDER = {"none": 0, "short": 1, "medium": 2, "long": 3}
_BREAK_TIER_NAMES = {order: name for name, order in _BREAK_TIER_ORDER.items()}


def _parse_percent(value: str) -> float:
    return float(value.replace("%", ""))


def _parse_hz(value: str) -> float:
    return float(value.replace("Hz", ""))


def _format_percent(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{value:.0f}%"


def _format_hz(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{value:.0f}Hz"


def combine_rate(style_rate: str, emotion_rate: str) -> str:
    return _format_percent(_parse_percent(style_rate) + _parse_percent(emotion_rate))


def combine_pitch(style_pitch: str, emotion_pitch: str) -> str:
    return _format_hz(_parse_hz(style_pitch) + _parse_hz(emotion_pitch))


def combine_break(style_break: str, emotion_break: str) -> str:
    tier = max(_BREAK_TIER_ORDER.get(style_break, 0), _BREAK_TIER_ORDER.get(emotion_break, 0))
    return _BREAK_TIER_NAMES[tier]


def enhance_narration(text: str, emotion: str, style: str = "story") -> str:
    """依 emotion + style 對應的停頓強度，在既有標點後方插入額外停頓符號，改善朗讀節奏。

    只在既有的句尾（。！？）與子句（，、；：）標點後方「附加」停頓符號，
    不會新增、刪除或修改任何文字內容，故事原文完全不變。
    """
    emotion_preset = EMOTION_PRESETS.get(emotion, EMOTION_PRESETS["none"])
    style_preset = STYLE_PRESETS.get(style, STYLE_PRESETS["story"])
    break_tier = combine_break(style_preset["break"], emotion_preset["break"])

    sentence_pause = _SENTENCE_PAUSE_BY_BREAK.get(break_tier, "")
    clause_pause = _CLAUSE_PAUSE_BY_BREAK.get(break_tier, "")

    if not sentence_pause and not clause_pause:
        return text

    chars = []
    for ch in text:
        chars.append(ch)
        if sentence_pause and ch in _SENTENCE_END_PUNCT:
            chars.append(sentence_pause)
        elif clause_pause and ch in _CLAUSE_END_PUNCT:
            chars.append(clause_pause)

    return "".join(chars)


class EdgeTTSProvider(VoiceProvider):
    """透過 Microsoft Edge 線上 TTS 服務生成語音（edge-tts 套件），免費、不需要 API 金鑰。"""

    DEFAULT_VOICES = {
        "zh-TW": "zh-TW-HsiaoChenNeural",
        "en": "en-US-AriaNeural",
        "en-US": "en-US-AriaNeural",
    }

    VOICE_ALIASES = {
        "narrator_male": "zh-TW-YunJheNeural",
        "narrator_female": "zh-TW-HsiaoChenNeural",
    }

    EMOTION_PRESETS = EMOTION_PRESETS
    STYLE_PRESETS = STYLE_PRESETS

    def generate(
        self,
        text: str,
        output_path: Path,
        language: str = "zh-TW",
        voice: str | None = None,
        emotion: str = "none",
        style: str = "story",
    ) -> Path:
        import asyncio

        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        selected_voice = voice or self.DEFAULT_VOICES.get(language, self.DEFAULT_VOICES["zh-TW"])
        selected_voice = self.VOICE_ALIASES.get(selected_voice, selected_voice)

        emotion_preset = self.EMOTION_PRESETS.get(emotion, self.EMOTION_PRESETS["none"])
        style_preset = self.STYLE_PRESETS.get(style, self.STYLE_PRESETS["story"])

        rate = combine_rate(style_preset["rate"], emotion_preset["rate"])
        pitch = combine_pitch(style_preset["pitch"], emotion_preset["pitch"])
        speech_text = enhance_narration(text, emotion, style)

        async def _synthesize():
            communicate = edge_tts.Communicate(
                speech_text,
                selected_voice,
                rate=rate,
                pitch=pitch,
            )
            await communicate.save(str(output_path))

        asyncio.run(_synthesize())

        return output_path


ACTIVE_PROVIDER = "dummy"  # "dummy"（之後可擴充 "edge-tts" / "elevenlabs" / 本地 TTS 等）


def get_provider() -> VoiceProvider:
    if ACTIVE_PROVIDER == "dummy":
        return DummyVoiceProvider()
    raise ValueError(f"未知的 ACTIVE_PROVIDER: {ACTIVE_PROVIDER}")
