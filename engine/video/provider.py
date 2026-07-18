import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from .camera_manager import CameraManager


class VideoProvider(ABC):
    @abstractmethod
    def generate(
        self,
        image_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
        camera_id: str = None,
    ) -> Path:
        ...


class DummyVideoProvider(VideoProvider):
    """假影片合成器：建立同名 .txt 檔案代表影片合成成功，不產生真正的影片。"""

    def __init__(self, camera_manager: CameraManager = None):
        self.camera_manager = camera_manager or CameraManager()

    def generate(
        self,
        image_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
        camera_id: str = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        camera_filter = self.camera_manager.get_filter(camera_id) if camera_id else ""

        txt_path = output_path.with_suffix(".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(
                f"image: {image_path}\naudio: {audio_path}\nsubtitle: {subtitle_path}\n"
                f"camera_id: {camera_id}\ncamera_filter: {camera_filter}\n"
            )

        return output_path


class FFmpegVideoProvider(VideoProvider):
    """透過本地 FFmpeg CLI 合成影片：靜態圖片 + 語音 + SRT 硬字幕燒錄。

    直接呼叫 ffmpeg 執行檔（不使用 ffmpeg-python 等第三方套件），使用前需先
    安裝 FFmpeg 並確保可在 PATH 找到 ffmpeg（或透過 ffmpeg_path 指定完整路徑）。
    圖片目前維持靜態（無 Ken Burns 效果），輸出固定 1920x1080、H.264 + AAC。
    """

    WIDTH = 1920
    HEIGHT = 1080

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe", camera_manager: CameraManager = None):
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.camera_manager = camera_manager or CameraManager()

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
        camera_id: str = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 已知問題：搭配 `-loop 1` 的靜態圖片輸入時，`-shortest` 有時無法可靠地
        # 在音訊結束的當下停止影像串流，導致畫面比聲音多出將近 2 秒（實測發現於
        # 部分 scene）。改用明確讀出的音檔真實時長搭配 `-t` 強制限制輸出長度，
        # `-shortest` 保留作為額外保險，但不再是唯一依據。
        audio_duration = self._get_audio_duration(audio_path)

        subtitles_arg = self._escape_subtitles_path(subtitle_path)

        camera_filter = self.camera_manager.get_filter(camera_id) if camera_id else ""

        filter_stages = []
        if camera_filter:
            filter_stages.append(camera_filter)
        filter_stages.append(f"scale={self.WIDTH}:{self.HEIGHT}:force_original_aspect_ratio=decrease")
        filter_stages.append(f"pad={self.WIDTH}:{self.HEIGHT}:(ow-iw)/2:(oh-ih)/2")
        filter_stages.append(f"subtitles='{subtitles_arg}'")
        video_filter = ",".join(filter_stages)

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


def get_episode_video_paths(story: dict, videos_dir: Path) -> list:
    """依 story['scenes'] 目前的順序與數量，組出每個 scene 對應的 mp4 路徑清單。

    完全依 story 內容決定 scene 數量與順序，不寫死任何數字；找不到某個
    scene 的 mp4 會直接丟出例外，而不是靜默跳過，避免串出一集缺片段的影片。
    """
    videos_dir = Path(videos_dir)
    video_paths = []
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        video_path = videos_dir / f"scene{scene_number:03d}.mp4"
        if not video_path.exists():
            raise FileNotFoundError(
                f"找不到 scene{scene_number:03d}.mp4（{video_path}），"
                "請先用 VideoProvider 產生所有 scene 的影片再串接。"
            )
        video_paths.append(video_path)
    return video_paths


def concatenate_episode(video_paths: list, output_path: Path, ffmpeg_path: str = "ffmpeg") -> Path:
    """用 ffmpeg concat demuxer 把已排序好的 scene mp4 清單無損串接成整集影片。

    scene mp4 都是用同一個 FFmpegVideoProvider 產生（相同解析度/編碼），
    串接採 `-c copy` 直接複製串流，不重新編碼，音訊與字幕（已燒錄進畫面）
    維持原樣、不中斷。
    """
    if not video_paths:
        raise ValueError("video_paths 不可為空，至少需要一個 scene 影片才能串接")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    concat_list_path = output_path.parent / f"{output_path.stem}_concat_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for video_path in video_paths:
            escaped = str(Path(video_path).resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    command = [
        ffmpeg_path,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_path),
        "-c", "copy",
        str(output_path),
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 串接失敗（exit code {result.returncode}）：\n{result.stderr}"
        )

    return output_path
