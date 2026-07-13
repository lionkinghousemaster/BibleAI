# BibleAI

BibleAI 是一個把聖經故事自動轉成兒童向動畫短片的內容工廠：從一份故事 JSON 出發，自動產生角色一致的插圖、配音、字幕、鏡頭運動、整集影片，以及上架用的封面與 metadata。

## 1. 系統架構圖

```
                              ┌─────────────────────┐
                              │  stories/*.json      │  (故事原文：scene、
                              │  （一部作品一個檔案） │   narration、image_prompt、
                              └──────────┬───────────┘   characters、camera…）
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   StoryScanner       │  掃描 stories/，解析
                              │ (story_scanner.py)   │  metadata，壞檔案自動跳過
                              └──────────┬───────────┘
                                         │
                                         ▼
        ┌───────────────────────────────────────────────────────────┐
        │                     batch_pipeline.py                      │
        │        （Content Factory + Publishing Factory 入口）        │
        └───────────────────────────────────────────────────────────┘
                 │           │            │            │
                 ▼           ▼            ▼            ▼
        ┌──────────────┐┌──────────┐┌───────────┐┌───────────────┐
        │ engine.prompt ││  Voice   ││ Subtitle  ││ CameraManager  │
        │ (PromptBuilder││ Provider ││ Generator ││ (zoom/pan      │
        │ +PromptLibrary││(EdgeTTS/ ││(標點切句 + ││  filter 模板)  │
        │ +PromptOptim- ││ Dummy)   ││ 音檔時長)  ││                │
        │  izer+Report) │└──────────┘└───────────┘└───────────────┘
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │ ImageProvider │  ComfyUI（FLUX.1-schnell）／Dummy
        │(generate_     │
        │ image.py)     │
        └──────┬───────┘
               ▼
        ┌──────────────┐      ┌────────────────┐      ┌───────────────────┐
        │ 每個 scene 的  │ ───▶ │ VideoProvider   │ ───▶ │ 整集影片串接        │
        │ image+audio+  │      │（FFmpeg 燒字幕  │      │ concatenate_episode│
        │ subtitle      │      │ +套用鏡頭運動）  │      │ (generate_video.py)│
        └──────────────┘      └────────────────┘      └─────────┬─────────┘
                                                                   ▼
                                                        ┌─────────────────────┐
                                                        │ content_metadata.py  │
                                                        │ 封面 Prompt / 圖片 /  │
                                                        │ YouTube Metadata /   │
                                                        │ Upload 欄位骨架       │
                                                        └─────────┬───────────┘
                                                                   ▼
                                                        ┌─────────────────────┐
                                                        │ release/<story_id>/  │
                                                        │  video/ image/       │
                                                        │  metadata/           │
                                                        │  （最終可發布產出）    │
                                                        └─────────────────────┘
```

`main.py` 是另一條並行的手動入口，固定只處理 `stories/Genesis_001.json`，輸出到 `output/`（詳見第 5 節）；`batch_pipeline.py` 是可以一次處理 `stories/` 底下所有故事的正式流程，兩者共用同一套 Provider／Manager／Builder，互不影響。

## 2. Pipeline 流程（Story → Release）

以 `batch_pipeline.run_batch()` 為例，單一故事的完整流程：

1. **StoryScanner** 讀取 `stories/<story_id>.json`，解析出 scenes、characters、camera 等欄位。
2. **`engine.prompt` 的 PromptBuilder**（結合 `CharacterManager`、`PromptLibrary` 讀到的 `prompts/` 模板、`PromptOptimizer`）依序組出 Character → Environment → Lighting → Composition → Style 的正向 prompt，以及獨立的 Negative prompt；同時把每個 scene 的 debug（去重/裁剪紀錄）匯出成檔案。
3. **ImageProvider**（ComfyUI 或 Dummy）依正向／負向 prompt 生成每個 scene 的圖片。
4. **VoiceProvider**（EdgeTTS 或 Dummy）依 `narration_zh` 生成每個 scene 的配音。
5. **Subtitle Generator** 依配音檔實際時長，把 `narration_zh` 依標點切句、分配時間軸，產生 `.srt`。
6. **VideoProvider**（FFmpeg 或 Dummy）把圖片＋配音＋字幕燒錄成每個 scene 的 mp4，並依 `scene["camera"]` 套用 `CameraManager` 對應的 zoompan 濾鏡。
7. **concatenate_episode** 依 scene 順序把所有 scene mp4 無損串接成整集影片。
8. **content_metadata** 自動組出封面 prompt 並呼叫 ImageProvider 生成封面圖，同時產生 YouTube 上架用的 Title／Description／Tags 與 Upload 欄位骨架。
9. 所有產出依統一結構寫入 `release/<story_id>/`，並把整批執行結果彙整進 `release/batch_report.json`。

單一故事的影片或 metadata 若失敗，只會記錄在該故事的結果裡，不會讓其他故事的批次處理中斷，也不會影響同一故事已經完成的圖片／配音／字幕。

## 3. 專案目錄說明

```
BibleAI/
├── stories/                  故事原文 JSON（一部作品一個檔案，新增作品只需在這裡加檔案）
├── characters/               角色設定 JSON（CharacterManager 讀取）
├── camera/                   鏡頭運動 preset JSON（CameraManager 讀取）
├── prompts/                  Prompt 模板與權重設定（PromptLibrary 讀取）
│   ├── lighting/ composition/ style/ negative/   各分類的 preset JSON
│   └── manifest.json         各分類的 Token Budget 權重與預設 preset id
├── workflows/                ComfyUI 匯出的 API Format workflow JSON
├── engine/                   Engine Layer：依領域劃分的核心引擎模組
│   ├── prompt/                Prompt 組裝與最佳化（本次 v0.8 遷入）
│   │   ├── library.py          PromptLibrary：模板／權重集中管理
│   │   ├── builder.py          PromptBuilder：組裝層
│   │   ├── optimizer.py        PromptOptimizer：去重＋Token Budget 裁剪
│   │   └── report.py           generate_prompt_report：prompt_report.txt
│   ├── story/                  Story Engine（預留，尚未遷入 story_scanner.py）
│   ├── image/                  Image Engine（預留，尚未遷入 generate_image.py）
│   ├── video/                  Video Engine（預留，尚未遷入 generate_video.py／camera_manager.py）
│   └── publish/                Publish Engine（預留，尚未遷入 content_metadata.py／batch_pipeline.py）
├── character_manager.py      角色管理模組
├── camera_manager.py         鏡頭運動管理模組
├── content_metadata.py       封面 Prompt／YouTube Metadata／Upload 欄位產生模組
├── story_scanner.py          掃描 stories/、解析故事 metadata
├── generate_image.py         圖片生成 Provider（ComfyUI／Dummy）
├── generate_voice.py         配音生成 Provider（EdgeTTS／Dummy）
├── generate_subtitle.py      字幕產生（純標準庫解析 MP3 時長）
├── generate_video.py         影片合成 Provider（FFmpeg／Dummy）＋整集串接
├── batch_pipeline.py         Content/Publishing Factory 入口：批次處理 stories/ 底下所有故事
├── main.py                   單一故事（Genesis_001）手動執行入口，輸出到 output/
├── output/                   main.py 的輸出（執行產物，.gitignore 排除，只留 .gitkeep）
└── release/                  batch_pipeline.py 的輸出（執行產物，.gitignore 排除，只留 .gitkeep）
```

`engine/` 是 v0.8 開始建立的分層架構：對外只需要 `from engine.prompt import PromptBuilder, generate_prompt_report` 這樣的頂層 import，不需要知道內部檔案是 library.py／builder.py／optimizer.py／report.py 這樣拆的。目前只有 Prompt 相關模組遷入 `engine.prompt`；`engine.story`／`engine.image`／`engine.video`／`engine.publish` 是預留的資料夾骨架，之後的 Sprint 會逐步把對應的頂層檔案（`story_scanner.py`、`generate_image.py`、`generate_video.py`／`camera_manager.py`、`content_metadata.py`／`batch_pipeline.py`）遷入。`prompts/`（模板資料）與 `characters/`／`camera/` 一樣仍放在專案根目錄，不隨程式碼一起搬進 `engine/`。

## 4. 核心模組角色

- **CharacterManager**（`character_manager.py` + `characters/*.json`）：一個角色一個 JSON 檔（`id`/`name_zh`/`name_en`/`visual_prompt`/`color_palette`/`voice`…），`get_visual_prompt(character_id)` 回傳固定的角色視覺描述片段，確保同一角色在不同 scene、不同集數之間長相、服裝、配色一致。找不到角色 id 一律回傳空字串，不丟例外。

- **CameraManager**（`camera_manager.py` + `camera/*.json`）：一個鏡頭運動 preset 一個 JSON 檔（`id`/`filter`/`description`），`get_filter(camera_id)` 回傳對應的 ffmpeg `zoompan` 濾鏡片段。目前內建 `static`／`slow_zoom_in`／`slow_zoom_out`／`pan_left`／`pan_right` 五種 preset。找不到 id 一律回傳空字串，`generate_video.py` 會自動退化為靜態畫面，不影響既有影片。

- **PromptLibrary**（`engine/prompt/library.py` + `prompts/<category>/*.json` + `prompts/manifest.json`）：Style／Lighting／Composition／Negative 四類 Prompt 模板與 metadata 的唯一集中管理入口。除了模板文字內容，也管理每個分類的 Token Budget 權重與預設 preset id（皆定義在 `prompts/manifest.json`，不是寫死在程式碼裡）。找不到 manifest、分類資料夾、或 preset 檔案一律回傳空值／預設值，不丟例外。

- **PromptBuilder**（`engine/prompt/builder.py`）：把一個 scene 的資料組成分層 prompt，依優先順序疊 Character（CharacterManager）→ Environment（scene 自己的 `image_prompt`）→ Lighting → Composition → Style（透過 PromptLibrary 讀取，預設用 manifest 登記的 preset），並產生獨立的 Negative prompt。PromptBuilder 本身不保存任何固定 Prompt 字串或分類設定，只負責組裝與呼叫 PromptOptimizer。任何一層模板缺席都只讓那一層變空字串、不影響其餘內容。

- **PromptOptimizer**（`engine/prompt/optimizer.py`）：PromptBuilder 內部使用的最佳化元件。(1) 去重：跨分類比對逗號分隔的片語，重複片語只保留第一次出現的位置；(2) Priority Token Budget：用空白斷詞數近似 token 數，超過預算（預設 77，對應 CLIP-L 上限）時依 PromptLibrary 登記的權重（預設 Lighting:Composition:Style = 3:2:1）把剩餘預算瀑布式分配給各分類，**Character 與 Environment 永遠是保護分類、不會被裁剪**；每一次去重／裁剪都會記錄成 debug log，可從 `image/prompts/scene{N}_final_prompt.txt` 與 `prompt_report.txt` 檢視。

- **`generate_prompt_report`**（`engine/prompt/report.py`）：產生整部作品的 `prompt_report.txt`，逐 scene 列出每個模組的字元數、token 數、來源（preset 檔案路徑或 Manager 名稱）與權重，以及完整的去重／裁剪 debug log。

以上四個模組對外都從 `engine.prompt` 這一個入口 import（`from engine.prompt import PromptBuilder, PromptLibrary, PromptOptimizer, generate_prompt_report`），呼叫端不需要知道內部檔案是怎麼拆的。

## 5. Content Factory 與 Publishing Factory 流程

- **Content Factory**（v0.5）：`StoryScanner` + `batch_pipeline.py` 的圖片／配音／字幕／影片串接部分——把一份 `stories/*.json` 變成完整的一集影片，不需要人工一步一步跑 `main.py` 裡的各個函式。
- **Publishing Factory**（v0.6）：在 Content Factory 之上加上「上架前還需要的東西」——自動生成封面圖（`generate_cover_image()`，呼叫真正的 ImageProvider）、YouTube 上架草稿（`generate_youtube_metadata()`）、以及預留給未來 YouTube Data API 上傳流程用的欄位骨架（`build_upload_payload()`）。兩者合起來讓 `batch_pipeline.run_batch()` 一次呼叫就能從「故事 JSON」產出「可以直接拿去上架的一整包檔案」。

## 6. release/ 資料夾結構

```
release/
├── batch_report.json              這次批次執行的完整記錄（每個故事的產出統計／錯誤）
└── <story_id>/
    ├── video/
    │   ├── audio/                 逐 scene 配音（scene001.mp3 …）
    │   ├── subtitles/              逐 scene 字幕（scene001.srt …）
    │   ├── scene001.mp4 …          逐 scene 影片（圖片+配音+字幕+鏡頭運動）
    │   ├── <story_id>_concat_list.txt   ffmpeg concat demuxer 用的檔案清單（中繼產物）
    │   └── <story_id>.mp4          整集影片
    ├── image/
    │   ├── prompts/                 每個 scene 的 prompt debug 匯出：
    │   │                             scene{N}.txt（原始 image_prompt）
    │   │                             scene{N}_positive_prompt.txt
    │   │                             scene{N}_negative_prompt.txt
    │   │                             scene{N}_final_prompt.txt（正向+負向+去重/裁剪 log）
    │   ├── scene001.png …           逐 scene 最終圖片
    │   └── cover_image.png          封面圖（由 cover_prompt 生成）
    └── metadata/
        ├── cover_prompt.txt         封面圖生成用的最終 prompt
        ├── metadata.json            story_id/book/episode/chapter/scene_count/title/description/tags
        ├── title.txt                純標題文字
        ├── description.txt         純描述文字
        ├── tags.txt                 標籤，一行一個
        └── upload.json               YouTube Data API（videos.insert）欄位骨架，
                                       upload_status/video_id/published_at 尚未串接真實上傳前皆為預留值
```

`release/`（跟 `output/` 一樣）已加入 `.gitignore`，只保留 `.gitkeep`——裡面的內容都是可以重新生成的執行產物，不進版本控制。

## 7. 如何新增一部新的故事

1. 在 `stories/` 底下新增一個 JSON 檔（檔名即 `story_id`，例如 `stories/Exodus_001.json`）。
2. 依現有的 `stories/Genesis_001.json` 格式撰寫：`episode`/`book`/`chapter`/`title_zh`/`title_en`/`duration`/`scenes`（每個 scene 至少要有 `scene_number`、`image_prompt`、`narration_zh`；`characters`/`camera` 為可選欄位，缺席時效果分別等同「沒有角色」「靜態鏡頭」）。
3. 若故事用到新角色，先在 `characters/` 新增對應的角色 JSON（`id` 需與 scene 的 `characters` 陣列所引用的 id 一致）。
4. 不需要修改任何程式碼——`StoryScanner` 會自動掃到新檔案，`batch_pipeline.py` 下次執行就會一併處理。

## 8. 如何重新生成一部作品

- **整批處理 `stories/` 底下所有故事**（含新的一部）：
  ```
  python batch_pipeline.py
  ```
  輸出到 `release/<story_id>/`，並更新 `release/batch_report.json`。

- **只跑 `stories/Genesis_001.json`（既有的單一故事手動入口，輸出到 `output/`）**：
  ```
  python main.py
  ```

- **只想重新生成某部作品的某個環節**（例如改了 prompt 模板想重新生成圖片）：可以在 Python 內直接呼叫 `batch_pipeline.py` 裡對應的函式（`generate_images`／`export_voice`／`export_subtitles`／`generate_videos`／`generate_episode_video`／`export_metadata`），傳入 `story_scanner.StoryScanner().get("<story_id>")` 取得的 story 資料與對應的 `ReleasePaths`，不需要重跑整個 `run_batch()`。
- 執行前請確認需要的外部服務已啟動：圖片走 ComfyUI 需要先啟動 ComfyUI（預設 `http://127.0.0.1:8188`）；影片合成需要本機安裝 FFmpeg 並可在 PATH 找到 `ffmpeg`/`ffprobe`。

## 9. 未來 Roadmap（v0.9 ～ v1.0）

已完成（v0.7～v0.8）：Prompt Engine（去重、Priority Token Budget、prompt_report.txt）、PromptLibrary／PromptBuilder 解耦、`engine/prompt` 分層架構。

- **v0.9 — 其餘 Engine 遷入**：把 `story_scanner.py`、`generate_image.py`、`generate_video.py`／`camera_manager.py`、`content_metadata.py`／`batch_pipeline.py` 依序遷入 `engine.story`／`engine.image`／`engine.video`／`engine.publish`，讓整個專案的頂層目錄只剩 `main.py`、`batch_pipeline.py` 這類入口腳本。
- **v0.9 — 多集規模驗證**：目前只有 `Genesis_001` 一部作品跑過完整流程，需要實際新增第二、第三部作品，驗證 Content/Publishing Factory 在多故事規模下的穩定性與耗時。
- **v0.9 — Prompt 資料清理**：把 `stories/*.json` 的 `image_prompt` 與 `characters/*.json` 的 `visual_prompt` 裡內嵌的風格字詞抽離，讓 `prompts/style/` 成為唯一風格來源，真正吃到 PromptOptimizer 去重帶來的 token 節省。
- **v0.9 — Lighting/Composition 差異化**：目前所有 scene 都用 `default` preset，可以依 `animation_prompt` 或劇情語意，幫特定 scene 指定 `lighting`/`composition`（例如夜晚場景用 `night`、宏觀場景用 `wide_shot`）。
- **v0.9 — 精確 Token 計數**：`PromptOptimizer` 目前用空白斷詞數近似 token 數，可評估導入真正的 CLIP/BPE tokenizer 讓長度保護更精準。
- **v1.0 — YouTube 實際上傳**：把 `upload.json` 接上真正的 YouTube Data API（`videos.insert` + 縮圖上傳），串接 OAuth 憑證管理，讓 `upload_status`/`video_id`/`published_at` 真正回填。
- **v1.0 — 多語系擴充**：`language: ["zh-TW", "en"]` 目前只用了 `narration_zh` 做配音／字幕，可評估是否要一併產出英文語音版本與雙語 YouTube 上架素材。
- **v1.0 — 正式發布 Pipeline**：整合排程（例如固定週期自動掃描新故事並發布）、失敗通知、以及 `release/` 產出的封存／備份策略。
