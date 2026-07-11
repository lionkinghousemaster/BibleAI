import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

# Video Pipeline 規劃中的資料流向（尚未實作）：
#
#   images/scene{N}.png ─┐
#   audio/scene{N}.mp3  ─┼─> FFmpeg（圖片+音訊+SRT 字幕燒錄）─> output/videos/scene{N}.mp4
#   subtitles/scene{N}.srt ┘
#
# 之後每個 scene 的 mp4 還會再串接成完整集數影片，屬於下一階段規劃，這裡先不實作。
# 目前只建立 Provider 架構與 Dummy 版本，驗證骨架可以正常呼叫。


class VideoProvider(ABC):
    @abstractmethod
    def generate(
        self,
        image_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
    ) -> Path:
        ...


class DummyVideoProvider(VideoProvider):
    """假影片合成器：建立同名 .txt 檔案代表影片合成成功，不產生真正的影片。"""

    def generate(
        self,
        image_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        txt_path = output_path.with_suffix(".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"image: {image_path}\naudio: {audio_path}\nsubtitle: {subtitle_path}\n")

        return output_path


class FFmpegVideoProvider(VideoProvider):
    """透過本地 FFmpeg CLI 合成影片：靜態圖片 + 語音 + SRT 硬字幕燒錄。

    直接呼叫 ffmpeg 執行檔（不使用 ffmpeg-python 等第三方套件），使用前需先
    安裝 FFmpeg 並確保可在 PATH 找到 ffmpeg（或透過 ffmpeg_path 指定完整路徑）。
    圖片目前維持靜態（無 Ken Burns 效果），輸出固定 1920x1080、H.264 + AAC。
    """

    WIDTH = 1920
    HEIGHT = 1080

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe"):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    @staticmethod
    def _escape_subtitles_path(path: Path) -> str:
        # ffmpeg 的 subtitles 濾鏡把冒號當成選項分隔符，Windows 路徑的磁碟機
        # 代號冒號必須跳脫，反斜線也一併換成正斜線以避免濾鏡語法解析錯誤。
        escaped = str(Path(path).resolve()).replace("\\", "/")
        return escaped.replace(":", "\\:")

    def _get_audio_duration(self, audio_path: Path) -> float:
        result = subprocess.run(
            [
                self.ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(audio_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"FFprobe 讀取音檔時長失敗（exit code {result.returncode}）：\n{result.stderr}"
            )
        return float(result.stdout.strip())

    def generate(
        self,
        image_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 已知問題：搭配 `-loop 1` 的靜態圖片輸入時，`-shortest` 有時無法可靠地
        # 在音訊結束的當下停止影像串流，導致畫面比聲音多出將近 2 秒（實測發現於
        # 部分 scene）。改用明確讀出的音檔真實時長搭配 `-t` 強制限制輸出長度，
        # `-shortest` 保留作為額外保險，但不再是唯一依據。
        audio_duration = self._get_audio_duration(audio_path)

        subtitles_arg = self._escape_subtitles_path(subtitle_path)
        video_filter = (
            f"scale={self.WIDTH}:{self.HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={self.WIDTH}:{self.HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            f"subtitles='{subtitles_arg}'"
        )

        command = [
            self.ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-i", str(audio_path),
            "-vf", video_filter,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-t", str(audio_duration),
            "-shortest",
            "-r", "30",
            str(output_path),
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg 執行失敗（exit code {result.returncode}）：\n{result.stderr}"
            )

        return output_path


ACTIVE_PROVIDER = "dummy"  # "dummy"（之後可擴充 "ffmpeg" 等真正的合成 Provider）


def get_provider() -> VideoProvider:
    if ACTIVE_PROVIDER == "dummy":
        return DummyVideoProvider()
    raise ValueError(f"未知的 ACTIVE_PROVIDER: {ACTIVE_PROVIDER}")
