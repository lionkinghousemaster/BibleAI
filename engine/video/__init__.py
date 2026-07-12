"""Video Engine（預留）。

尚未遷入：影片合成與整集串接邏輯（`VideoProvider`/`DummyVideoProvider`/
`FFmpegVideoProvider`/`concatenate_episode`/`get_episode_video_paths`，
以及 `CameraManager`）仍在專案根目錄的 `generate_video.py`／
`camera_manager.py`。未來遷入時會把它們移到這裡，並在此 re-export，
維持與 `engine.prompt` 相同的對外介面風格。
"""
