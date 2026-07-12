"""BibleAI Engine Layer.

按領域劃分的核心引擎模組：

- `engine.prompt`  — Prompt 組裝與最佳化（PromptLibrary/PromptBuilder/
  PromptOptimizer/PromptReport）
- `engine.story`   — 故事掃描與解析（預留，尚未遷入，見 story_scanner.py）
- `engine.image`   — 圖片生成（預留，尚未遷入，見 generate_image.py）
- `engine.video`   — 影片合成／串接（預留，尚未遷入，見 generate_video.py）
- `engine.publish` — 封面／Metadata／上架資料（預留，尚未遷入，見
  content_metadata.py、batch_pipeline.py）

v0.8 這次只把 Prompt 相關模組遷入 `engine.prompt`；其餘子模組先建立
資料夾骨架，之後的 Sprint 再逐步把對應的頂層檔案遷入。
"""
