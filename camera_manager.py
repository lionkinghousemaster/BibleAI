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
    """從 camera/ 資料夾讀取鏡頭運動設定 JSON 檔案（一個 preset 一個檔案，檔名即 camera_id）。"""

    def __init__(self, camera_dir: Path = None):
        self.camera_dir = Path(camera_dir) if camera_dir else Path(__file__).parent / "camera"

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
    """鏡頭運動資料的存取入口，包裝 CameraProvider。

    目前是獨立模組，尚未被 generate_video.py / main.py 引用，不影響任何既有 pipeline。
    """

    def __init__(self, provider: CameraProvider = None):
        self.provider = provider or JSONCameraProvider()

    def get_camera(self, camera_id: str) -> dict | None:
        return self.provider.get(camera_id)

    def list_cameras(self) -> dict:
        return self.provider.load_all()

    def get_filter(self, camera_id: str) -> str:
        """回傳鏡頭運動對應的 ffmpeg filter 片段，未來給 generate_video.py 組 filter chain 時引用。"""
        camera = self.get_camera(camera_id)
        if not camera:
            return ""
        return camera.get("filter", "")
