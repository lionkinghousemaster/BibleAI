import json
from abc import ABC, abstractmethod
from pathlib import Path


class CameraProvider(ABC):
    @abstractmethod
    def load_all(self) -> dict:
        ...

    @abstractmethod
    def get(self, camera_id: str) -> dict | None:
        ...


class JSONCameraProvider(CameraProvider):
    """從 camera/ 資料夾讀取鏡頭運動設定 JSON 檔案（一個 preset 一個檔案，檔名即 camera_id）。

    `camera/` 資料夾本身仍放在專案根目錄（跟 `characters/`／`prompts/`
    一樣是資料，不隨程式碼一起搬進 `engine/`），因此預設路徑往上推三層
    （engine/video/camera_manager.py -> engine/video -> engine -> 專案根目錄）
    才是 `camera/`。
    """

    def __init__(self, camera_dir: Path = None):
        self.camera_dir = Path(camera_dir) if camera_dir else Path(__file__).parent.parent.parent / "camera"

    def load_all(self) -> dict:
        cameras = {}
        if not self.camera_dir.exists():
            return cameras

        for file_path in sorted(self.camera_dir.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            camera_id = data.get("id", file_path.stem)
            cameras[camera_id] = data

        return cameras

    def get(self, camera_id: str) -> dict | None:
        file_path = self.camera_dir / f"{camera_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


class CameraManager:
    """鏡頭運動資料的存取入口，包裝 CameraProvider。"""

    def __init__(self, provider: CameraProvider = None):
        self.provider = provider or JSONCameraProvider()

    def get_camera(self, camera_id: str) -> dict | None:
        return self.provider.get(camera_id)

    def list_cameras(self) -> dict:
        return self.provider.load_all()

    def get_filter(self, camera_id: str) -> str:
        """回傳鏡頭運動對應的 ffmpeg filter 片段，給 FFmpegVideoProvider 組 filter chain 時引用。"""
        camera = self.get_camera(camera_id)
        if not camera:
            return ""
        return camera.get("filter", "")
