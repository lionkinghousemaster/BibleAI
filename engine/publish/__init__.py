"""Publish Engine。

`UploadProvider`（`DummyUploadProvider` 離線測試用、`YouTubeUploadProvider`
真正呼叫 YouTube Data API v3）負責把 `content_metadata.build_upload_payload()`
產生的 `upload.json`（snippet/status）連同整集影片與封面圖，實際上傳到
YouTube，並把 `upload_status`/`video_id`/`published_at` 回填進
`upload.json`（見 uploader.py）。呼叫端只需要
`from engine.publish import DummyUploadProvider, YouTubeUploadProvider`。

尚未遷入：封面／YouTube Metadata／上架欄位骨架邏輯（`generate_cover_prompt`/
`generate_youtube_metadata`/`build_upload_payload`）仍在專案根目錄的
`content_metadata.py`；批次協調邏輯（`ReleasePaths`/`process_story`/
`run_batch`）仍在 `batch_pipeline.py`。未來遷入時會把它們移到這裡，並在
此 re-export，維持與 `engine.prompt` 相同的對外介面風格。
"""

from .uploader import DummyUploadProvider, UploadProvider, YouTubeUploadProvider

__all__ = [
    "UploadProvider",
    "DummyUploadProvider",
    "YouTubeUploadProvider",
]
