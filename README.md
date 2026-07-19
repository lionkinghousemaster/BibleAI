# BibleAI

BibleAI 是一個把聖經故事自動轉成兒童向動畫短片的內容工廠：從一份故事 JSON 出發，自動產生角色一致的插圖、配音、字幕、鏡頭運動、整集影片、上架用的封面與 metadata，並可直接上傳到 YouTube。

## 1. 系統架構圖

```
                              ┌─────────────────────┐
                              │  stories/*.json      │  (故事原文：scene、
                              │  （一部作品一個檔案） │   narration、image_prompt、
                              └──────────┬───────────┘   characters、camera…）
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │  engine.story        │  掃描 stories/，解析
                              │  StoryScanner        │  metadata，壞檔案自動跳過
                              └──────────┬───────────┘
                                         │
                                         ▼
        ┌───────────────────────────────────────────────────────────┐
        │                     batch_pipeline.py                      │
        │      （入口腳本，實作在 engine.publish.pipeline）            │
        └───────────────────────────────────────────────────────────┘
                 │           │            │            │
                 ▼           ▼            ▼            ▼
        ┌──────────────┐┌──────────┐┌───────────┐┌───────────────┐
        │ engine.prompt ││  Voice   ││ Subtitle  ││ engine.video   │
        │ (PromptBuilder││ Provider ││ Generator ││ CameraManager  │
        │ +PromptLibrary││(EdgeTTS/ ││(標點切句 + ││ (zoom/pan      │
        │ +PromptOptim- ││ Dummy)   ││ 音檔時長)  ││  filter 模板)  │
        │  izer+Report) │└──────────┘└───────────┘└───────────────┘
        └──────┬───────┘
               ▼
        ┌──────────────┐
        │ engine.image  │  ImageProvider：ComfyUI（FLUX.1-schnell）／Dummy
        └──────┬───────┘
               ▼
        ┌──────────────┐      ┌────────────────┐      ┌───────────────────┐
        │ 每個 scene 的  │ ───▶ │ engine.video    │ ───▶ │ 整集影片串接        │
        │ image+audio+  │      │ VideoProvider   │      │ concatenate_episode│
        │ subtitle      │      │（FFmpeg 燒字幕  │      │（engine.video）    │
        │               │      │ +套用鏡頭運動）  │      │                    │
        └──────────────┘      └────────────────┘      └─────────┬─────────┘
                                                                   ▼
                                                        ┌─────────────────────┐
                                                        │ engine.publish       │
                                                        │ metadata.py：封面     │
                                                        │ Prompt / 圖片 /       │
                                                        │ YouTube Metadata /   │
                                                        │ Upload 欄位          │
                                                        └─────────┬───────────┘
                                                                   ▼
                                                        ┌─────────────────────┐
                                                        │ engine.publish       │
                                                        │ uploader.py：         │
                                                        │ UploadProvider       │
                                                        │（YouTube Data API /  │
                                                        │  Dummy）             │
                                                        └─────────┬───────────┘
                                                                   ▼
                                                        ┌─────────────────────┐
                                                        │ release/<story_id>/  │
                                                        │  video/ image/       │
                                                        │  metadata/           │
                                                        │  （最終可發布產出，   │
                                                        │   upload.json 含真實  │
                                                        │   video_id/上架狀態） │
                                                        └─────────────────────┘
```

`main.py` 是另一條並行的手動入口，固定只處理 `stories/Genesis_001.json`，輸出到 `output/`（詳見第 5 節）；`batch_pipeline.py` 是可以一次處理 `stories/` 底下所有故事的正式流程，兩者共用同一套 Provider／Manager／Builder，互不影響。兩者都只是入口腳本——`main.py` 一直都是如此，`batch_pipeline.py` 從 v0.9 Engine Migration Sprint 起也是（實作全部搬進 `engine.publish.pipeline`，見第 3 節）。

上圖最上方的 `stories/*.json` 除了人工撰寫，v0.9 起也可以用 `engine.story` 的 `StoryGenerator` 依主題自動產生（見第 4、7 節）——產生的故事是完全相同的 JSON 結構，`batch_pipeline.py` 不需要知道這份故事是人工寫的還是自動生成的。

## 2. Pipeline 流程（Story → Release）

以 `batch_pipeline.run_batch()` 為例，單一故事的完整流程：

1. **StoryScanner** 讀取 `stories/<story_id>.json`，解析出 scenes、characters、camera 等欄位。
2. **`engine.prompt` 的 PromptBuilder**（結合 `CharacterManager`、`engine.director` 的 Director Layer、`PromptLibrary` 讀到的 `prompts/` 模板、`PromptOptimizer`）依序組出 Character → Environment → Lighting → Composition → Camera Angle → Mood → Style 的正向 prompt，以及獨立的 Negative prompt；Lighting／Composition／Camera Angle／Mood 這四個分類不再固定用 manifest 的 default preset，而是由 Director 依 scene 語意自動決定（見第 4 節）。同時把每個 scene 的 debug（去重/裁剪紀錄）與 Director 的判斷依據匯出成檔案。
3. **`engine.image` 的 ImageProvider**（ComfyUI 或 Dummy）依正向／負向 prompt 生成每個 scene 的圖片。
4. **VoiceProvider**（EdgeTTS 或 Dummy）依 `narration_zh` 生成每個 scene 的配音。
5. **Subtitle Generator** 依配音檔實際時長，把 `narration_zh` 依標點切句、分配時間軸，產生 `.srt`。
6. **`engine.video` 的 VideoProvider**（FFmpeg 或 Dummy）把圖片＋配音＋字幕燒錄成每個 scene 的 mp4，套用的鏡頭運動由 `engine.director.resolve_visual_plan(scene)["camera_shot"]` 決定（scene 明確指定 `camera` 時原樣沿用，否則由 Director 依語意自動判斷，見第 4 節），再透過 `engine.video` 的 `CameraManager` 轉成對應的 zoompan 濾鏡（Director Camera Integration Mission 新增；先前是直接讀 `scene["camera"]`，缺席時等同靜態鏡頭）。
7. **`engine.video` 的 concatenate_episode** 依 scene 順序把所有 scene mp4 無損串接成整集影片。
8. **`engine.publish` 的 metadata.py** 自動組出封面 prompt 並呼叫 ImageProvider 生成封面圖，同時產生 YouTube 上架用的 Title／Description／Tags 與 Upload 欄位（`build_upload_payload`）。
9. **`engine.publish` 的 UploadProvider**（`YouTubeUploadProvider` 或 `Dummy`）把整集影片＋封面圖連同上一步的 snippet/status 實際呼叫 YouTube Data API v3 上傳，把 `upload_status`/`video_id`/`published_at` 回填進 `upload.json`；若整集影片還沒成功產生，或這部作品先前已經上傳成功過，這一步會安全地跳過（見第 4、8 節）。
10. 所有產出依統一結構寫入 `release/<story_id>/`，並把整批執行結果彙整進 `release/batch_report.json`。

單一故事的影片或 metadata 若失敗，只會記錄在該故事的結果裡，不會讓其他故事的批次處理中斷，也不會影響同一故事已經完成的圖片／配音／字幕。

## 3. 專案目錄說明

```
BibleAI/
├── stories/                  故事原文 JSON（一部作品一個檔案，新增作品只需在這裡加檔案）
├── characters/               角色設定 JSON（CharacterManager 讀取）
├── camera/                   鏡頭運動 preset JSON（CameraManager 讀取）
├── prompts/                  Prompt 模板與權重設定（PromptLibrary 讀取）
│   ├── lighting/ composition/ camera_angle/ mood/ style/ negative/   各分類的 preset JSON
│   │                          （camera_angle／mood 為 v0.9 Director Intelligence Sprint 新增）
│   └── manifest.json         各分類的 Token Budget 權重與預設 preset id
├── workflows/                ComfyUI 匯出的 API Format workflow JSON
├── engine/                   Engine Layer：依領域劃分的核心引擎模組
│   ├── prompt/                Prompt 組裝與最佳化（v0.8 遷入）
│   │   ├── library.py          PromptLibrary：模板／權重集中管理
│   │   ├── builder.py          PromptBuilder：組裝層
│   │   ├── optimizer.py        PromptOptimizer：去重＋Token Budget 裁剪
│   │   ├── importance.py        角色 importance_score 計算（v0.9 Story Intelligence Sprint 新增）
│   │   └── report.py           generate_prompt_report：prompt_report.txt
│   ├── director/                Director：視覺語意決策層（v0.9 Director Intelligence Sprint 新增）
│   │   └── director.py          依 scene 語意自動決定 lighting/composition/camera_shot/
│   │                            camera_angle/mood，見第 4 節
│   ├── story/                  Story Engine（v0.9 新增 StoryGenerator；scanner.py 本次遷入）
│   │   ├── scanner.py           StoryScanner：掃描 stories/、解析故事 metadata
│   │   ├── generator.py        StoryGenerator：依主題組出 stories/*.json 格式的故事
│   │   ├── llm_provider.py     LLMProvider：DummyLLMProvider（離線）／AnthropicProvider（Claude API）
│   │   └── report.py           generate_story_report：story_report.txt
│   ├── image/                  Image Engine（本次 v0.9 Engine Migration Sprint 遷入）
│   │   └── provider.py          ImageProvider：ComfyUIProvider／DummyProvider／
│   │                            generate_scene_image／generate_image_from_prompt
│   ├── video/                  Video Engine（本次 v0.9 Engine Migration Sprint 遷入）
│   │   ├── provider.py          VideoProvider：FFmpegVideoProvider／DummyVideoProvider／
│   │   │                        concatenate_episode／get_episode_video_paths
│   │   └── camera_manager.py    CameraManager：讀取 camera/*.json 鏡頭運動 preset
│   └── publish/                Publish Engine（uploader.py 是 v1.0 新增；metadata.py／
│       │                       pipeline.py 本次 v0.9 Engine Migration Sprint 遷入）
│       ├── metadata.py          封面 Prompt／YouTube Metadata／Upload 欄位產生
│       ├── uploader.py          UploadProvider：DummyUploadProvider（離線）／
│       │                        YouTubeUploadProvider（YouTube Data API v3）
│       └── pipeline.py          ReleasePaths／process_story／run_batch 等批次協調邏輯
├── character_manager.py      角色管理模組
├── generate_story.py         StoryGenerator 執行入口：產生新故事 JSON + story_report.txt
├── generate_voice.py         配音生成 Provider（EdgeTTS／Dummy）
├── generate_subtitle.py      字幕產生（純標準庫解析 MP3 時長）
├── batch_pipeline.py         入口腳本：批次處理 stories/ 底下所有故事（轉呼叫 engine.publish.run_batch）
├── main.py                   單一故事（Genesis_001）手動執行入口，輸出到 output/
├── output/                   main.py 的輸出（執行產物，.gitignore 排除，只留 .gitkeep）
└── release/                  batch_pipeline.py 的輸出（執行產物，.gitignore 排除，只留 .gitkeep）
```

`engine/` 是 v0.8 開始建立的分層架構：對外只需要 `from engine.prompt import PromptBuilder, generate_prompt_report` 這樣的頂層 import，不需要知道內部檔案是 library.py／builder.py／optimizer.py／report.py 這樣拆的。`engine.story`（v0.9）／`engine.image`／`engine.video`／`engine.publish`（本次 v0.9 Engine Migration Sprint）都是同樣的入口風格：`from engine.image import ComfyUIProvider, DummyProvider, generate_scene_image`、`from engine.video import FFmpegVideoProvider, CameraManager, concatenate_episode`、`from engine.publish import run_batch, process_story, ReleasePaths, DummyUploadProvider, YouTubeUploadProvider`。`engine.prompt`／`engine.story`／`engine.image`／`engine.video`／`engine.publish` 現在都有實際模組，頂層目錄只剩 `main.py`、`batch_pipeline.py` 這類入口腳本，以及 `character_manager.py`／`generate_story.py`／`generate_voice.py`／`generate_subtitle.py`。`character_manager.py`（角色資料存取，不屬於任何單一 Engine，被 `engine.prompt`／`engine.story`／`engine.publish` 共用）與 `generate_voice.py`／`generate_subtitle.py`（尚未規劃對應的 Engine）目前仍是獨立的頂層模組。`prompts/`／`characters/`／`camera/`（模板／資料）一樣仍放在專案根目錄，不隨程式碼一起搬進 `engine/`——各自對應的 Manager／Library／Scanner 內部路徑會依實際遷入深度往上推對應層數解析回專案根目錄（例如 `engine/video/camera_manager.py`、`engine/story/scanner.py` 都是往上推三層才是 `camera/`／`stories/`）。

## 4. 核心模組角色

- **CharacterManager**（`character_manager.py` + `characters/*.json`）：一個角色一個 JSON 檔（`id`/`name_zh`/`name_en`/`visual_prompt`/`color_palette`/`voice`…），`get_visual_prompt(character_id)` 回傳固定的角色視覺描述片段，確保同一角色在不同 scene、不同集數之間長相、服裝、配色一致。找不到角色 id 一律回傳空字串，不丟例外。

- **CameraManager**（`engine/video/camera_manager.py` + `camera/*.json`）：一個鏡頭運動 preset 一個 JSON 檔（`id`/`filter`/`description`），`get_filter(camera_id)` 回傳對應的 ffmpeg `zoompan` 濾鏡片段。目前內建 `static`／`slow_zoom_in`／`slow_zoom_out`／`pan_left`／`pan_right` 五種 preset。找不到 id 一律回傳空字串，`FFmpegVideoProvider` 會自動退化為靜態畫面，不影響既有影片。

- **PromptLibrary**（`engine/prompt/library.py` + `prompts/<category>/*.json` + `prompts/manifest.json`）：Lighting／Composition／Camera Angle／Mood／Style／Negative 六類 Prompt 模板與 metadata 的唯一集中管理入口（Camera Angle／Mood 為 v0.9 Director Intelligence Sprint 新增）。除了模板文字內容，也管理每個分類的 Token Budget 權重與預設 preset id（皆定義在 `prompts/manifest.json`，不是寫死在程式碼裡）。找不到 manifest、分類資料夾、或 preset 檔案一律回傳空值／預設值，不丟例外。

- **Director**（`engine/director/director.py`，v0.9 Director Intelligence Sprint 新增）：依 scene 的 `narration_zh`/`narration_en`/`animation_prompt`/`title` 判斷這是哪一種戲劇情境——`divine_appearance`（神顯現）／`climax`（高潮）／`conflict`（衝突）／`sadness`（悲傷）／`joy`（喜樂）／`creation`（建立），每個情境對應到一組固定的 `lighting`/`composition`/`camera_shot`/`camera_angle`/`mood` preset id（`THEMES` 常數表）。一個 scene 可能同時命中多個情境，依 `THEME_PRIORITY`（`divine_appearance` > `climax` > `conflict` > `sadness` > `joy` > `creation`）取第一個命中的當主導情境；都沒命中時套用 `DEFAULT_DECISION`（等同這個機制導入之前的固定 `default`/`eye_level`/`neutral`/`static`，行為不變）。`resolve_visual_plan(scene)` 是實際呼叫入口：scene 若已明確指定 `lighting`/`composition`/`camera_angle`/`mood`/`camera`，一律優先採用，Director 不會覆蓋人工設定的值，只補上沒指定的欄位。英文關鍵字比對用「左邊字界」regex（只要求關鍵字開頭前是字界，結尾不要求）——關鍵字表裡故意保留 `argu`/`tempt`/`celebrat`/`deceiv` 這類詞幹以涵蓋 arguing/tempted/celebration/deceived 等變化形，但完整子字串比對曾經讓 `sin` 誤判命中 `pulsing` 這個單字中間，跟 importance.py 的 "Eve"/"reveal" 是同一類 bug，改成只要求左字界後解決。`camera_shot` 對應到既有的 `camera/*.json`（鏡頭運動 preset）；PromptBuilder 只消費 `lighting`/`composition`/`camera_angle`/`mood` 四個欄位組正向 prompt，`camera_shot` 則是由 `main.py`／`engine.publish.pipeline` 的 `generate_videos()` 與 `StoryGenerator._normalize_scene` 消費，實際決定每個 scene 的影片鏡頭運動（見第 2、7 節，Director Camera Integration Mission 新增）。

- **PromptBuilder**（`engine/prompt/builder.py`）：把一個 scene 的資料組成分層 prompt，依優先順序疊 Character（CharacterManager，每個角色各自成為獨立分類，見下方 Story Intelligence／importance_score）→ Environment（scene 自己的 `image_prompt`）→ Lighting → Composition → Camera Angle → Mood → Style，並產生獨立的 Negative prompt。Lighting／Composition／Camera Angle／Mood 這四層的 preset id 不再固定用 manifest 的 default preset，而是先呼叫 `engine.director.resolve_visual_plan(scene)` 依語意自動決定，再透過 PromptLibrary 讀取實際模板文字。PromptBuilder 本身不保存任何固定 Prompt 字串或分類設定，只負責組裝與呼叫 PromptOptimizer。任何一層模板缺席都只讓那一層變空字串、不影響其餘內容。

  **Story Intelligence／importance_score 機制**（v0.9 Story Intelligence Sprint 新增，取代舊版三段式 Character Priority）：每個角色在每個 scene 裡的重要程度不再是固定的 `main`/`secondary`/`background` tier，而是連續的 0.0～1.0 `importance_score`，由 `engine/prompt/importance.py` 依四個信號加權計算：`is_main`（是否為 `scene["characters"]` 第一個角色，權重 0.4）、`is_plot_core`（角色名字是否出現在 narration 裡，權重 0.3）、`has_action`（角色名字是否出現在 `animation_prompt` 裡，權重 0.2）、`has_dialogue`（角色名字是否緊接在旁白引號前，粗略代表有台詞，權重 0.1）。單角色 scene 一律視為 1.0（完全保護，維持舊行為、不需要改任何既有 story JSON）。分數來源判斷順序（`resolve_character_importance`）：1. `scene["character_importance"][id]`（明確覆寫，StoryGenerator 產生的故事會自動寫入）→ 2. `scene["character_priority"][id]`（舊版 tier，向下相容，映射 main=1.0／secondary=0.5／background=0.2）→ 3. 現場計算的啟發式分數。`importance_score ≥ MAIN_IMPORTANCE_THRESHOLD`（0.75）的角色視為保護分類、永不裁剪；低於門檻的角色依 `weight_from_importance()`（`max(1, round(score * IMPORTANCE_WEIGHT_SCALE)`，`IMPORTANCE_WEIGHT_SCALE = 5`）換算成 PromptOptimizer 的權重參與瀑布式分配。（權重縮放係數選 5 而非更大的值是經驗調校結果——縮放 10 時中等分數角色的權重會蓋過 Lighting/Composition，重現舊版三角色場景擠壓 Composition 到空的問題。）名字比對對英文名字採用 `\b` 字界 regex（避免 "Eve" 誤判命中 "reveal" 這類子字串），中文名字維持子字串比對。

- **PromptOptimizer**（`engine/prompt/optimizer.py`）：PromptBuilder 內部使用的最佳化元件。(1) 去重：跨分類比對逗號分隔的片語，重複片語只保留第一次出現的位置；(2) Priority Token Budget：用空白斷詞數近似 token 數，超過預算（預設 77，對應 CLIP-L 上限）時依呼叫端傳入的 `protected` 集合與 `category_weights` 把剩餘預算瀑布式分配給每個可裁剪分類——**Environment 與 importance_score ≥ 0.75 的角色永遠是保護分類、不會被裁剪**，其餘角色與 Lighting／Composition／Style 依各自權重（預設 Lighting:Composition:Style = 3:2:1，角色權重依 importance_score 換算）公平分配剩餘預算；每一次去重／裁剪都會記錄成 debug log，可從 `image/prompts/scene{N}_final_prompt.txt` 與 `prompt_report.txt` 檢視。PromptOptimizer 本身不知道「Character」「importance_score」這些概念，只認得呼叫端傳入的分類名稱與權重——Story Intelligence 完全是 PromptBuilder 那一層的邏輯，`allocate_budget()`／`enforce_length_budget()` 都支援傳入呼叫端專屬的 `category_weights`（省略時沿用建構時的預設值）。

  **Camera Angle／Mood 的權重刻意設為 0**（`prompts/manifest.json`）：這兩個分類是這次 Sprint 新增的補充描述，budget 不足需要裁剪時永遠優先被裁到 0（weight 0 不影響其他分類計算份額時的權重總和，數學上等同它們不存在），讓 Lighting/Composition/Style 的預算分配結果跟這個機制加入之前完全一致——實測 `Genesis_001` scene001/009/011 確認 FINAL positive token 數與 Lighting/Composition/Style 存活狀況都跟加入 Director 之前一模一樣，沒有因為多了兩個競爭分類而被擠壓。budget 足夠、完全不需要裁剪的 scene（多數情況）仍然會完整保留 Camera Angle／Mood 的內容。

- **`generate_prompt_report`**（`engine/prompt/report.py`）：產生整部作品的 `prompt_report.txt`，逐 scene 列出每個模組的字元數、token 數、來源（preset 檔案路徑或 Manager 名稱）與權重，以及完整的去重／裁剪 debug log。每個角色分類額外列出 `importance_score` 與觸發的 `signals`（`is_main`／`is_plot_core`／`has_action`／`has_dialogue`）；每個 scene 開頭額外列出 Director 的判斷結果（`theme`／`camera_shot`／命中的 `matched_keywords`／每個欄位是人工指定還是 Director 自動判斷），方便直接對照分數與實際分配到的 Token／權重，分析 Story Intelligence／Director 的判斷依據。

以上四個模組對外都從 `engine.prompt` 這一個入口 import（`from engine.prompt import PromptBuilder, PromptLibrary, PromptOptimizer, generate_prompt_report`），呼叫端不需要知道內部檔案是怎麼拆的。

- **StoryScanner**（`engine/story/scanner.py`）：掃描 `stories/` 底下所有故事 JSON、解析出 `episode`/`book`/`chapter`/`title_zh`/`title_en`/`duration`/`scene_count` 等 metadata。新增一部作品只需要在 `stories/` 底下多丟一個 JSON 檔案，不需要改任何程式碼；無法解析的 JSON 或缺少有效 `scenes` 的檔案會被跳過並印出警告，不會讓整批掃描中斷。

- **StoryGenerator**（`engine/story/generator.py`，v0.9 新增）：依主題自動產生符合 `stories/*.json` 格式的故事。本身不生成敘事內容——把 `CharacterManager`／`CameraManager`／`PromptLibrary` 目前有哪些可用的角色、鏡頭運動、lighting/composition/style preset id 組成 context 交給注入的 `LLMProvider`，再驗證回傳的每個 scene（不存在的 character/camera/preset id 一律回退成安全預設值——`camera` 的回退值改由 `engine.director.decide_visual_plan` 依這個 scene 的語意建議，建議值也無效才退回固定預設值，見 Director Camera Integration Mission、duration 轉成合法正整數、依序補上 `scene_number`），組成與 `stories/Genesis_001.json` 完全相同結構的故事 dict，可以直接存成 JSON 交給 `batch_pipeline.py` 處理。

- **LLMProvider**（`engine/story/llm_provider.py`）：與 `ImageProvider`／`VoiceProvider`／`VideoProvider` 同一種抽象介面風格。`DummyLLMProvider` 離線、不需要 API 金鑰，依 context 提供的角色／鏡頭清單輪流組出可辨識的 placeholder 內容，用來驗證整條 pipeline；`AnthropicProvider` 呼叫 Claude API（`anthropic` 官方 SDK，預設 model `claude-opus-4-8`，需要 `ANTHROPIC_API_KEY`），透過 structured outputs（`output_config.format`）保證回傳的 JSON 直接符合 scene schema。

- **`generate_story_report`**（`engine/story/report.py`）：產生 `story_report.txt`，逐 scene 列出角色／鏡頭／lighting／composition／style 的實際取值（省略欄位顯示 `(default)`，代表交由 `PromptLibrary` 的 manifest 預設值決定）與 narration／image_prompt／animation_prompt／subtitle 內容，方便在丟進 `batch_pipeline.py` 之前人工檢視生成內容是否合理。

- **UploadProvider**（`engine/publish/uploader.py`，v1.0 新增）：與 `ImageProvider`／`VoiceProvider`／`VideoProvider`／`LLMProvider` 同一種抽象介面風格。`DummyUploadProvider` 不會呼叫任何網路 API，回傳一組 `DUMMY_` 開頭的假 `video_id` 與目前時間當作 `published_at`，用來驗證「`upload.json` → 呼叫上傳 → 欄位回填」這條路徑；`YouTubeUploadProvider` 透過 YouTube Data API v3（`videos.insert` + `thumbnails.set`，官方 `google-api-python-client`／`google-auth-oauthlib` SDK）把整集影片＋封面圖真正上傳到 YouTube，需要事先在 Google Cloud Console 建立 OAuth 2.0 用戶端並完成一次瀏覽器互動授權（見第 8 節）。`engine/publish/pipeline.py` 的 `upload_video()`（`batch_pipeline.py` re-export 同一份實作）會先檢查該作品是否已經上傳成功過（`upload_status == "uploaded"`）；已上傳過的作品會直接沿用舊有的 `video_id` 等欄位，不會重複上傳，整集影片還沒成功產生時也會安全地跳過。

## 5. Content Factory 與 Publishing Factory 流程

- **Content Factory**（v0.5）：`StoryScanner` + `engine.publish.pipeline` 的圖片／配音／字幕／影片串接部分——把一份 `stories/*.json` 變成完整的一集影片，不需要人工一步一步跑 `main.py` 裡的各個函式。
- **Publishing Factory**（v0.6 起草，v1.0 完成實際上傳）：在 Content Factory 之上加上「上架前還需要的東西」——自動生成封面圖（`generate_cover_image()`，呼叫真正的 ImageProvider）、YouTube 上架草稿（`generate_youtube_metadata()`）、上架用的欄位（`build_upload_payload()`，皆在 `engine/publish/metadata.py`），最後由 `engine.publish` 的 `UploadProvider` 真正呼叫 YouTube Data API 完成上傳，把 `upload_status`/`video_id`/`published_at` 回填進 `upload.json`。四者合起來讓 `engine.publish.run_batch()`（`python batch_pipeline.py` 的入口就是呼叫這個函式）一次呼叫就能從「故事 JSON」產出並上架成一支（預設為不公開的）YouTube 影片。

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
        └── upload.json               YouTube Data API 上傳結果：snippet/status 是上傳用的欄位，
                                       upload_status（not_uploaded/dummy_uploaded/uploaded）/
                                       video_id/published_at/thumbnail_path 由 UploadProvider 執行後回填
```

`release/`（跟 `output/` 一樣）已加入 `.gitignore`，只保留 `.gitkeep`——裡面的內容都是可以重新生成的執行產物，不進版本控制。

## 7. 如何新增一部新的故事

1. 在 `stories/` 底下新增一個 JSON 檔（檔名即 `story_id`，例如 `stories/Exodus_001.json`）。
2. 依現有的 `stories/Genesis_001.json` 格式撰寫：`episode`/`book`/`chapter`/`title_zh`/`title_en`/`duration`/`scenes`（每個 scene 至少要有 `scene_number`、`image_prompt`、`narration_zh`；`characters`/`camera` 為可選欄位，`characters` 缺席時等同「沒有角色」；`camera` 缺席或填了不存在的 preset id 時，改由 `engine.director` 依這個 scene 的語意自動決定鏡頭運動（見第 4 節 Director，Director Camera Integration Mission 新增），沒有命中任何情境時才等同舊行為的「靜態鏡頭」；`character_importance`——`{character_id: 0.0~1.0}`——也是可選欄位，省略時由 `engine/prompt/importance.py` 依 is_main／is_plot_core／has_action／has_dialogue 四個信號現場計算（單角色 scene 一律視為 1.0，等同舊行為），只有想手動覆寫 AI 判斷結果時才需要填這個欄位；舊版的 `character_priority`——`{character_id: "main"/"secondary"/"background"}`——仍相容支援但已不建議使用，見第 4 節 PromptBuilder 的 Story Intelligence／importance_score 機制）。`lighting`/`composition`/`camera_angle`/`mood` 同樣都是可選欄位，省略時由 `engine.director` 依 narration／animation_prompt／title 的語意自動決定該用哪個 preset（見第 4 節 Director），只有想手動覆寫 Director 判斷結果時才需要填這些欄位。
3. 若故事用到新角色，先在 `characters/` 新增對應的角色 JSON（`id` 需與 scene 的 `characters` 陣列所引用的 id 一致）。
4. 不需要修改任何程式碼——`StoryScanner` 會自動掃到新檔案，`batch_pipeline.py` 下次執行就會一併處理。

也可以不手寫 JSON，改用 `engine.story` 的 `StoryGenerator` 自動產生（v0.9 新增）：

```python
from engine.story import StoryGenerator, AnthropicProvider  # 或 DummyLLMProvider 離線測試

generator = StoryGenerator(llm_provider=AnthropicProvider())  # 需要 ANTHROPIC_API_KEY
story = generator.generate(
    theme="該隱與亞伯的故事",
    episode="EP03", book="創世記 (Genesis)", chapter="4",
    title_zh="該隱與亞伯", title_en="Cain and Abel",
    scene_count=8,
)
```

`generate()` 回傳的 dict 可以直接 `json.dump` 存到 `stories/<story_id>.json`；`generate_story.py` 是現成的執行入口（預設用 `DummyLLMProvider`，把 `ACTIVE_LLM_PROVIDER` 改成 `"anthropic"` 並設定 `ANTHROPIC_API_KEY` 就會改叫真正的 Claude API），會同時輸出 `story_report.txt` 方便存檔前先人工檢查生成內容。若主題用到 `characters/` 裡沒有的角色，記得依上面第 3 步先補上角色 JSON，否則該角色只會被當成純文字敘述，缺少視覺一致性描述。

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

- **只想重新生成某部作品的某個環節**（例如改了 prompt 模板想重新生成圖片）：可以在 Python 內直接呼叫 `batch_pipeline.py` re-export 的函式（`generate_images`／`export_voice`／`export_subtitles`／`generate_videos`／`generate_episode_video`／`export_metadata`，實作都在 `engine/publish/pipeline.py`），傳入 `engine.story.StoryScanner().get("<story_id>")` 取得的 story 資料與對應的 `ReleasePaths`，不需要重跑整個 `run_batch()`。
- 執行前請確認需要的外部服務已啟動：圖片走 ComfyUI 需要先啟動 ComfyUI（預設 `http://127.0.0.1:8188`）；影片合成需要本機安裝 FFmpeg 並可在 PATH 找到 `ffmpeg`/`ffprobe`。
- 真正上傳到 YouTube（`ACTIVE_UPLOAD_PROVIDER = "youtube"`）需要事先完成以下設定，預設值是不會呼叫任何網路 API 的 `"dummy"`：
  1. `pip install google-api-python-client google-auth-oauthlib google-auth-httplib2`（本專案沒有維護 `requirements.txt`，跟 `edge-tts` 的作法一致，需要另外手動安裝）。
  2. 到 [Google Cloud Console](https://console.cloud.google.com/) 建立專案並啟用「YouTube Data API v3」。
  3. 建立 OAuth 2.0 用戶端 ID（應用程式類型選「桌面應用程式」），下載憑證 JSON，存成專案根目錄的 `youtube_client_secrets.json`（檔名可透過 `YouTubeUploadProvider(client_secrets_path=...)` 自訂；已加入 `.gitignore`，不會被提交）。
  4. 把 **`engine/publish/pipeline.py`** 的 `ACTIVE_UPLOAD_PROVIDER` 改成 `"youtube"`（不是 `batch_pipeline.py`——那裡只轉呼叫，`get_upload_provider()` 讀的是 `engine/publish/pipeline.py` 自己模組內的常數，見第 3 節）。第一次執行 `python batch_pipeline.py` 時會跳出瀏覽器要求登入並同意授權，取得的憑證會存到 `youtube_token.json`（同樣已加入 `.gitignore`），之後執行會自動用 refresh token 續期，不需要再次互動登入。
  5. `build_upload_payload()`（`engine/publish/metadata.py`）預設 `privacyStatus` 是 `"private"`（不公開），確認上傳內容沒問題後再自行改成 `"public"`／`"unlisted"`。

## 9. 未來 Roadmap（v0.9 ～ v1.1）

已完成（v0.7～v0.8）：Prompt Engine（去重、Priority Token Budget、prompt_report.txt）、PromptLibrary／PromptBuilder 解耦、`engine/prompt` 分層架構。

已完成（v0.9）：Story Generator（`engine.story` 的 `StoryGenerator` + `LLMProvider`/`DummyLLMProvider`/`AnthropicProvider` + `generate_story_report`，見第 4、7 節）——依主題自動產生符合 `stories/*.json` 格式的故事，與既有 `batch_pipeline.py` 完全相容。

已完成（v1.0）：YouTube 實際上傳（`engine.publish` 的 `UploadProvider`/`DummyUploadProvider`/`YouTubeUploadProvider`，見第 4、8 節）——`export_metadata()` 現在會真正呼叫 YouTube Data API v3 上傳整集影片與封面縮圖，並把 `upload_status`/`video_id`/`published_at` 回填進 `upload.json`；已上傳成功的作品重跑批次不會被重複上傳。

已完成（v0.9 Engine Migration Sprint）：其餘 Engine 遷入——`generate_image.py`→`engine/image/provider.py`、`generate_video.py`/`camera_manager.py`→`engine/video/provider.py`+`engine/video/camera_manager.py`、`content_metadata.py`/`batch_pipeline.py` 的實作→`engine/publish/metadata.py`+`engine/publish/pipeline.py`、`story_scanner.py`→`engine/story/scanner.py`（見第 3 節）。`main.py`／`batch_pipeline.py` 現在都只是入口腳本，`python main.py`／`python batch_pipeline.py` 行為與遷移前完全相同；每遷完一個 Engine 都跑過 `main.py`／`batch_pipeline.py` regression test 確認無回歸。`engine.prompt`／`engine.story`／`engine.image`／`engine.video`／`engine.publish` 現在都是實際模組，v0.8 訂下的 Engine Layer 遷移目標全數完成。同一個 Sprint 也用 `StoryGenerator` 產生 3 部全新故事（`Genesis_002`～`004`，共 20 個 scene）跟既有的 `Genesis_001`（11 個 scene）一起丟進同一次 `run_batch()`，驗證了多故事規模下的穩定性——批次正確處理全部 4 部故事、無互相污染，「多集規模驗證」視為完成。

已完成（v0.9 Prompt Quality Sprint）：Prompt 資料清理——把 `characters/*.json`（`adam`/`eve`/`god`/`serpent`）與 `stories/Genesis_001.json`（全部 11 個 scene）的 `visual_prompt`／`image_prompt` 裡內嵌的繪本風格字詞（`children's storybook illustration style`／`soft watercolor texture`／`2D flat illustration for kids`）移除，讓 `prompts/style/default.json` 成為唯一風格來源（見第 4 節 UploadProvider 之前的段落）。清理前後對 `Genesis_001` 重新產生 `prompt_report.txt` 比對：protected 的 character／environment 分類 token 數明顯下降（單角色 scene 的 character 24→20 tokens，environment 平均下降約 10～13 tokens；多角色 scene 的 character 83→71 tokens），釋出的預算讓 lighting／composition 存活更多內容、trim 次數變少；最關鍵的是風格層的核心信號詞「`children's storybook illustration`」以前在 11 個 scene 中有 10 個會被預算裁剪掉（等於完全沒送進最終 prompt），清理後只剩 2 個角色數過多的 scene（9、11，god+adam+eve 三個角色同時出場）仍會被裁掉——這 2 個 scene 的結構性上限問題由下一個 Sprint（Token Allocation Sprint）解決，其餘 9 個 scene 現在都能穩定保留風格一致性。另外用 `StoryGenerator`／`DummyLLMProvider` 產生的故事（`Genesis_002`～`004`，因為原本就沒有把風格字詞寫進 `image_prompt`）全數 0 次 trim，佐證了「資料不重複」時 PromptOptimizer 完全不需要裁剪。

已完成（v0.9 Token Allocation Sprint）：Character Priority 機制（見第 4 節 PromptBuilder／PromptOptimizer 段落）——不再是「整個 Character 固定保護、Lighting/Composition/Style 固定挨刀」的寫死規則，而是依 Main／Secondary／Background 三個 tier 決定每個角色該不該被保護、被裁剪時的優先順序，權重定義在 `prompts/manifest.json` 的 `character_priority_weights`（資料，不是程式碼常數）。單角色 scene 不需要改任何既有 story JSON（預設第一個角色是 `main`，等同舊行為）；`Genesis_001` scene 9／11（god+adam+eve 三角色同場）額外標了 `scene["character_priority"]` 覆寫（三個角色都設 `secondary`，讓 Environment 獨自扛保護分類——因為這兩個 scene 的 `image_prompt` 本身已經涵蓋了角色的視覺描述，個別角色的 visual_prompt 是加分而非唯一資訊來源），驗證結果：scene 9 的 Lighting／Composition 從完全空白（trim 到 0 token）變成各自保留一個片語（`soft diffused natural light`／`balanced centered composition`），scene 11 甚至連 Style 的核心信號詞都保住了；兩個 scene 的 FINAL positive token 數都降到 77 上限以內（scene 9：122→66、scene 11：99→72），不再超出預算。

已完成（v0.9 Story Intelligence Sprint）：把上面的三段式 Character Priority 換成連續的 `importance_score`（`engine/prompt/importance.py`，見第 4 節）——`StoryGenerator` 產生新故事時會依 is_main／is_plot_core／has_action／has_dialogue 四個信號自動算好每個角色在每個 scene 的重要性分數並寫進 `character_importance` 欄位，不再需要事後人工覆寫 `character_priority`；`prompt_report.txt` 也同步列出每個角色的 `importance_score` 與觸發的 signals，方便直接對照分數與實際分配到的 Token。過程中修掉一個子字串誤判的 bug（英文名字 "Eve" 曾誤判命中 "reveal" 這個單字，導致假的 `has_action` 訊號），改成 `\b` 字界 regex 比對；也把角色權重換算的縮放係數從最初嘗試的 10 調成 5（`IMPORTANCE_WEIGHT_SCALE`），避免中等分數角色的權重蓋過 Lighting/Composition。移除 `Genesis_001` scene 9／11 的舊版 `character_priority` 覆寫後，改用純啟發式計算重新驗證：scene 9 維持 66 tokens（FINAL），scene 11 從 72 進一步降到 63 tokens，兩個 scene 的 Lighting／Composition／Style 都確認無回歸、持續存活；額外用 `StoryGenerator`＋`DummyLLMProvider` 生成的 `Genesis_002` 也跑過同一輪驗證，確認 `character_importance` 欄位正確寫入且 `source=explicit` 被 PromptBuilder 正確採用。

已完成（v0.9 Director Intelligence Sprint）：新增 `engine.director`（見第 4 節）——PromptBuilder 不再固定用 manifest 的 `default` preset，而是依 scene 的 narration／animation_prompt／title 語意，自動判斷這是建立／衝突／高潮／悲傷／喜樂／神顯現哪一種情境，再決定 `lighting`/`composition`/`camera_angle`/`mood`（以及 `camera_shot`，這次 Sprint 只出現在報告裡，尚未接回實際影片鏡頭運動邏輯，見下方 Director Camera Integration Mission）該用哪個 preset；新增 `prompts/camera_angle/`（`eye_level`/`low_angle`/`high_angle`）與 `prompts/mood/`（`neutral`/`awe`/`wonder`/`tense`/`dramatic`/`somber`/`joyful`）兩個分類，以及一個新的 `prompts/lighting/dramatic.json`。過程中修掉一個跟 Story Intelligence Sprint 同類型的子字串誤判 bug（英文關鍵字 "sin" 曾誤判命中 "pulsing" 這個單字中間），改成左字界 regex 解決。整合時發現：直接把 Camera Angle／Mood 當成跟 Lighting/Composition/Style 同權重（1）的可裁剪分類，會稀釋 Style 的預算份額，讓 `Genesis_001` scene001 的 style 核心信號詞「`children's storybook illustration`」被裁掉——重現 Prompt Quality Sprint 修過的問題；修法是把 Camera Angle／Mood 的 manifest 權重設為 0（budget 不足時優先犧牲這兩個新分類，數學上不影響其他分類的份額計算），修正後對 `Genesis_001` scene 001／009／011 重新驗證，FINAL positive token 數與 Lighting／Composition／Style 存活狀況都跟加入 Director 之前完全一致，`Genesis_001` 全 11 個 scene 與 `StoryGenerator` 產生的 `Genesis_002`（該隱與亞伯，6 個 scene）都跑過 `main.py`／`prompt_report.txt` regression test 確認無回歸、無例外。

已完成（Director Camera Integration Mission）：把 Director 的 `camera_shot` 判斷正式接回實際影片鏡頭運動邏輯——`main.py`／`engine.publish.pipeline` 的 `generate_videos()` 不再直接讀 `scene.get("camera")`，改呼叫 `engine.director.resolve_visual_plan(scene)["camera_shot"]`（scene 明確指定 `camera` 時原樣沿用，缺席或無效時才由 Director 依語意決定，等同 `camera/static.json` 空濾鏡的舊行為，對現有 story JSON 零影響）；`StoryGenerator._normalize_scene` 的 camera 回退邏輯也從「固定挑第一個 camera preset」改成「先問 Director 這個 scene 語意上該用哪個鏡頭運動，答案無效才退回固定預設值」。驗證方式：(1) 直接呼叫 `FFmpegVideoProvider.generate()` 對 Director 六種情境會用到的全部 5 個 camera_shot id（`static`/`slow_zoom_in`/`slow_zoom_out`/`pan_left`/`pan_right`）各自產生一支測試影片，`ffprobe` 確認每支都是合法的 1920x1080 H.264/AAC mp4，並用 PSNR 比對同一支影片裡第 0 幀與第 60 幀（`static` PSNR≈63dB 幾乎無差異、`slow_zoom_in` PSNR≈8.8dB 有明顯位移、`pan_left` PSNR≈46dB 有中等位移），證實濾鏡確實依 camera_shot 產生對應強度的真實鏡頭運動，不是被靜默忽略；(2) 用一個故意回傳缺席／無效 `camera` 欄位的假 LLMProvider 驗證 `StoryGenerator` 的新回退邏輯，確認神顯現語意的 scene 自動選到 `slow_zoom_out`、無特定語意的 scene 退回 `static`；(3) `Genesis_001`（11 scene，全部明確指定 camera）與 `StoryGenerator` 產生的 `Genesis_002`～`004`（共 20 scene，`DummyLLMProvider` 一律明確指定 camera）跑過完整 `batch_pipeline.run_batch()`，確認 image/voice/subtitle/video 各階段場次數量不變、無例外。

- **v1.0 — YouTube 實際上傳實測**：`YouTubeUploadProvider` 已完整實作（`videos.insert` + `thumbnails.set` + OAuth 憑證管理），但這個開發環境沒有 Google Cloud OAuth 憑證，只用 `DummyUploadProvider` 驗證過「上傳結果回填」與「已上傳過就跳過」的邏輯，尚未對真正的 YouTube API 實測過——需要使用者依第 8 節設定好 `youtube_client_secrets.json` 後，實際跑一次 `python batch_pipeline.py`（`ACTIVE_UPLOAD_PROVIDER = "youtube"`）確認整個流程。
- **v0.9 — Story Generator 品質驗證**：目前只用 `DummyLLMProvider` 跑過完整流程驗證 schema 相容性；`AnthropicProvider` 尚未接上真實 `ANTHROPIC_API_KEY` 實測過，需要實際跑一次並檢視 `story_report.txt`／`prompt_report.txt`，確認生成內容的敘事品質與 image_prompt 是否符合兒童向分級與角色一致性要求。
- **v0.9 — importance_score 精確度**：目前的四信號啟發式（is_main／is_plot_core／has_action／has_dialogue）都是規則式判斷，`has_dialogue` 尤其只靠「名字緊接在引號前」這種粗略字串比對；可評估是否讓 `AnthropicProvider` 生成故事時直接由 LLM 自己判斷並填入 `character_importance`（比純規則式更懂情節脈絡），或至少用真實產生的多故事資料集驗證目前四個信號的權重（0.4/0.3/0.2/0.1）是否需要調整。
- **v0.9 — Director 語意規則精確度**：目前的情境判斷是關鍵字表式的規則引擎，`THEMES`／`THEME_PRIORITY` 都是程式碼常數，關鍵字涵蓋範圍有限（例如 `DummyLLMProvider` 產生的模板化敘事容易全部命中同一個關鍵字）；可評估是否讓 `AnthropicProvider` 生成故事時由 LLM 直接判斷情境並填入 `lighting`/`composition`/`camera_angle`/`mood`（比純規則式更懂情節脈絡），或至少用更多真實故事資料驗證目前六種情境的關鍵字表與優先順序是否需要調整。
- **v0.9 — 精確 Token 計數**：`PromptOptimizer` 目前用空白斷詞數近似 token 數，可評估導入真正的 CLIP/BPE tokenizer 讓長度保護更精準。
- **v1.0 — 多語系擴充**：`language: ["zh-TW", "en"]` 目前只用了 `narration_zh` 做配音／字幕，可評估是否要一併產出英文語音版本與雙語 YouTube 上架素材。
- **v1.0 — 正式發布 Pipeline**：整合排程（例如固定週期自動掃描新故事並發布）、失敗通知、以及 `release/` 產出的封存／備份策略。
- **v1.1 — 上傳結果通知與重試**：`YouTubeUploadProvider` 目前失敗會直接拋出例外（讓該故事的批次處理中止，記錄在 `batch_report.json`），可評估加上重試（處理 429/5xx）與失敗通知（例如寫入單獨的 upload 失敗清單，或串接 Slack/Email）。
