from pathlib import Path


def split_sentences(text: str) -> list[str]:
    """依句尾標點（。！？）切句，標點保留在句尾，不改變/刪除任何文字內容。"""
    sentence_end = "。！？"
    sentences = []
    current = ""
    for ch in text:
        current += ch
        if ch in sentence_end:
            sentences.append(current)
            current = ""
    if current.strip():
        sentences.append(current)
    return sentences


# 純標準庫的 MP3 (CBR) 時長估算器：解析第一個合法 frame header 取得
# bitrate / sample rate，再用「音訊位元組數 * 8 / bitrate」推算總長度。
# 不需要 ffmpeg 或 mutagen 等套件。
_MPEG_VERSION = {0b00: "2.5", 0b10: "2", 0b11: "1"}
_LAYER = {0b01: 3, 0b10: 2, 0b11: 1}

_BITRATE_TABLE = {
    ("1", 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, None],
    ("1", 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, None],
    ("1", 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None],
    ("2", 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, None],
    ("2", 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
    ("2", 3): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None],
}
_BITRATE_TABLE[("2.5", 1)] = _BITRATE_TABLE[("2", 1)]
_BITRATE_TABLE[("2.5", 2)] = _BITRATE_TABLE[("2", 2)]
_BITRATE_TABLE[("2.5", 3)] = _BITRATE_TABLE[("2", 3)]

_SAMPLE_RATE_TABLE = {
    "1": [44100, 48000, 32000, None],
    "2": [22050, 24000, 16000, None],
    "2.5": [11025, 12000, 8000, None],
}


def get_mp3_duration_seconds(path: Path) -> float:
    """解析 MP3 第一個合法 frame header 估算音檔總長（秒），假設是 CBR。"""
    data = Path(path).read_bytes()

    frame_offset = None
    for i in range(len(data) - 4):
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            frame_offset = i
            break

    if frame_offset is None:
        raise ValueError(f"找不到合法的 MP3 frame header：{path}")

    b1, b2 = data[frame_offset + 1], data[frame_offset + 2]

    version = _MPEG_VERSION.get((b1 >> 3) & 0b11)
    layer = _LAYER.get((b1 >> 1) & 0b11)
    if version is None or layer is None:
        raise ValueError(f"無法辨識的 MP3 版本/層：{path}")

    bitrate_index = (b2 >> 4) & 0b1111
    samplerate_index = (b2 >> 2) & 0b11

    bitrate_kbps = _BITRATE_TABLE[(version, layer)][bitrate_index]
    sample_rate = _SAMPLE_RATE_TABLE[version][samplerate_index]
    if not bitrate_kbps or not sample_rate:
        raise ValueError(f"無法解析 bitrate/sample rate：{path}")

    audio_bytes = len(data) - frame_offset
    return (audio_bytes * 8) / (bitrate_kbps * 1000)


def format_srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(sentences: list[str], total_duration_seconds: float) -> str:
    """沒有逐字時間軸時的替代方案：把音檔總長平均分配給切出來的每一句。"""
    if not sentences:
        return ""

    per_sentence = total_duration_seconds / len(sentences)

    lines = []
    for index, sentence in enumerate(sentences, start=1):
        start = (index - 1) * per_sentence
        end = index * per_sentence
        lines.append(str(index))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(sentence)
        lines.append("")

    return "\n".join(lines)


def generate_subtitle_srt(text: str, audio_path: Path, output_path: Path) -> Path:
    """依 narration 文字與對應音檔時長，產生標準 .srt 字幕檔。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sentences = split_sentences(text)
    duration = get_mp3_duration_seconds(audio_path)
    srt_content = build_srt(sentences, duration)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    return output_path
