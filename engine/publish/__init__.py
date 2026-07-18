"""Publish Engine。

Content Factory 之後「上架前還需要的東西」全部整合在這裡：

- `metadata.py` — `build_cover_scene`/`generate_cover_prompt`/
  `generate_youtube_metadata`/`build_upload_payload`：自動組出封面 prompt
  與 YouTube 上架草稿（title/description/tags/上傳欄位）。
- `uploader.py` — `UploadProvider`（`DummyUploadProvider` 離線測試用、
  `YouTubeUploadProvider` 真正呼叫 YouTube Data API v3）：把
  `build_upload_payload()` 產生的 snippet/status 連同整集影片與封面圖
  實際上傳到 YouTube，並把 `upload_status`/`video_id`/`published_at`
  回填進 `upload.json`。
- `pipeline.py` — `ReleasePaths`/`process_story`/`run_batch` 等批次協調
  邏輯：把 Prompt Engine、`engine.image`、`engine.video`、上面兩個模組全部
  串起來，從一份故事 JSON 產出 `release/<story_id>/` 底下的完整發布產出。

本次 v0.9 Engine Migration Sprint 從專案根目錄的 `content_metadata.py`／
`batch_pipeline.py` 完整遷入。呼叫端只需要
`from engine.publish import run_batch, process_story, ReleasePaths, ...`
這樣的頂層 import，不需要知道內部檔案是怎麼拆的，維持與 `engine.prompt`
相同的對外介面風格。頂層的 `batch_pipeline.py` 現在只是一個轉呼叫
`run_batch()` 的入口腳本（跟 `main.py` 一樣，不再是實作所在）。
"""

from .metadata import build_cover_scene, build_upload_payload, generate_cover_prompt, generate_youtube_metadata
from .pipeline import (
    ACTIVE_IMAGE_PROVIDER,
    ACTIVE_UPLOAD_PROVIDER,
    ACTIVE_VIDEO_PROVIDER,
    ACTIVE_VOICE_PROVIDER,
    RELEASE_DIR,
    WORKFLOW_PATH,
    ReleasePaths,
    export_image_prompts,
    export_metadata,
    export_subtitles,
    export_voice,
    generate_cover_image,
    generate_episode_video,
    generate_images,
    generate_videos,
    get_image_provider,
    get_upload_provider,
    get_video_provider,
    get_voice_provider,
    load_previous_upload_result,
    process_story,
    run_batch,
    upload_video,
)
from .uploader import DummyUploadProvider, UploadProvider, YouTubeUploadProvider

__all__ = [
    "UploadProvider",
    "DummyUploadProvider",
    "YouTubeUploadProvider",
    "build_cover_scene",
    "generate_cover_prompt",
    "generate_youtube_metadata",
    "build_upload_payload",
    "ReleasePaths",
    "export_image_prompts",
    "generate_images",
    "export_voice",
    "export_subtitles",
    "generate_videos",
    "generate_episode_video",
    "generate_cover_image",
    "load_previous_upload_result",
    "upload_video",
    "export_metadata",
    "process_story",
    "run_batch",
    "get_image_provider",
    "get_voice_provider",
    "get_video_provider",
    "get_upload_provider",
    "RELEASE_DIR",
    "WORKFLOW_PATH",
    "ACTIVE_IMAGE_PROVIDER",
    "ACTIVE_VOICE_PROVIDER",
    "ACTIVE_VIDEO_PROVIDER",
    "ACTIVE_UPLOAD_PROVIDER",
]
