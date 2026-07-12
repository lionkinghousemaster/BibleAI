"""Publish Engine（預留）。

尚未遷入：封面／YouTube Metadata／上架欄位骨架邏輯（`generate_cover_prompt`/
`generate_youtube_metadata`/`build_upload_payload`）仍在專案根目錄的
`content_metadata.py`；批次協調邏輯（`ReleasePaths`/`process_story`/
`run_batch`）仍在 `batch_pipeline.py`。未來遷入時會把它們移到這裡，並在
此 re-export，維持與 `engine.prompt` 相同的對外介面風格。
"""
