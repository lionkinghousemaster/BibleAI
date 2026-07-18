"""Content/Publishing Factory 入口：批次處理 stories/ 底下所有故事。

實作本體（`ReleasePaths`/`process_story`/`run_batch` 等）本次 v0.9 Engine
Migration Sprint 已遷入 `engine.publish`（見 engine/publish/pipeline.py）。
這裡只是轉呼叫 `run_batch()` 的入口腳本，跟 `main.py` 一樣不再是實作所在；
若要在 Python 內直接呼叫個別環節（`generate_images`／`export_voice`／
`export_subtitles`／`generate_videos`／`generate_episode_video`／
`export_metadata`），可以用這裡 re-export 的名稱，也可以直接
`from engine.publish import ...`，兩者是同一份實作。

若要切換 `ACTIVE_IMAGE_PROVIDER`／`ACTIVE_VOICE_PROVIDER`／
`ACTIVE_VIDEO_PROVIDER`／`ACTIVE_UPLOAD_PROVIDER`，要修改
`engine/publish/pipeline.py` 裡的常數——這幾個常數不在這裡 re-export，
因為 `get_*_provider()` 讀的是 `engine.publish.pipeline` 自己模組內的值，
在這個轉呼叫模組覆寫同名變數並不會真的生效。
"""

from engine.publish import (
    ReleasePaths,
    export_image_prompts,
    export_metadata,
    export_subtitles,
    export_voice,
    generate_cover_image,
    generate_episode_video,
    generate_images,
    generate_videos,
    load_previous_upload_result,
    process_story,
    run_batch,
    upload_video,
)

if __name__ == "__main__":
    run_batch()
