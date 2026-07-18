"""Video Engine。

影片合成與整集串接邏輯（`VideoProvider`/`DummyVideoProvider`/
`FFmpegVideoProvider`/`concatenate_episode`/`get_episode_video_paths`，見
provider.py）以及 `CameraManager`（見 camera_manager.py）本次 v0.9 Engine
Migration Sprint 從專案根目錄的 `generate_video.py`／`camera_manager.py`
遷入。呼叫端只需要
`from engine.video import FFmpegVideoProvider, DummyVideoProvider, CameraManager, concatenate_episode, get_episode_video_paths`
這樣的頂層 import，不需要知道內部檔案是怎麼拆的，維持與 `engine.prompt`
相同的對外介面風格。
"""

from .camera_manager import CameraManager, CameraProvider, JSONCameraProvider
from .provider import (
    DummyVideoProvider,
    FFmpegVideoProvider,
    VideoProvider,
    concatenate_episode,
    get_episode_video_paths,
)

__all__ = [
    "VideoProvider",
    "DummyVideoProvider",
    "FFmpegVideoProvider",
    "concatenate_episode",
    "get_episode_video_paths",
    "CameraProvider",
    "JSONCameraProvider",
    "CameraManager",
]
