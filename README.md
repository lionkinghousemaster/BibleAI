# BibleAI

## 資料夾結構

- `stories/`：每一集的故事腳本（JSON），包含各 scene 的旁白、字幕與 prompt
- `characters/`：角色設定（尚未使用）
- `prompts/`：保留資料夾（尚未使用）
- `output/`
  - `image_prompts/`：由 `main.py` 從 story JSON 匯出的每個 scene 的 image_prompt（scene001.txt、scene002.txt...）
  - `images/`：由 `generate_image.py` 產生的圖片
  - `audio/`：由 `generate_voice.py` 產生的語音檔（scene001.mp3、scene002.mp3...）
  - `subtitles/`：由 `generate_subtitle.py` 產生的字幕檔（scene001.srt、scene002.srt...）
  - `videos/`：由 `generate_video.py` 產生的影片（scene001.mp4、scene002.mp4...，目前僅骨架）
- `workflows/`：從 ComfyUI 匯出的 API Format workflow JSON（見 `workflows/README.md`）

## 模組用途

- `main.py`：讀取 `stories/` 中的故事 JSON，將每個 scene 的 image_prompt 輸出到 `output/image_prompts/`，並呼叫 `generate_image.py` / `generate_voice.py` 產生圖片與語音
- `generate_image.py`：圖片生成模組，採 Provider 架構，可切換不同生成方式
  - `DummyProvider`：把 prompt 寫成 .txt 檔，代表生成成功（用來跑通 pipeline）
  - `ComfyUIProvider`：透過本地 ComfyUI 的 HTTP API 生成圖片，規劃搭配 FLUX.1-schnell（Apache 2.0，可商用）。只需 Python 標準庫，不需安裝第三方套件；使用前需先安裝 ComfyUI 並匯出 workflow JSON 到 `workflows/`
- `generate_subtitle.py`：依 narration 文字與對應 mp3 產生標準 `.srt` 字幕（依標點切句、依音檔實際時長分配時間軸，純標準庫解析 MP3 header，不需要 ffmpeg）
- `generate_video.py`：影片合成模組，架構與 `generate_image.py` / `generate_voice.py` 一致（見下方 Video Pipeline）

## Voice Pipeline

- `generate_voice.py`：語音生成模組，架構與 `generate_image.py` 一致（Provider 介面 + 可切換實作），目前**尚未接任何真正的 TTS**
  - `VoiceProvider`：抽象介面，定義 `generate(text, output_path, language="zh-TW", voice=None) -> Path`
  - `DummyVoiceProvider`：不產生真正語音，只在 `output_path` 同名位置寫入 `.txt`（內容為傳入的文字），用來驗證 pipeline 是否跑得通，最後回傳 `output_path`
  - `ACTIVE_PROVIDER = "dummy"`：目前唯一可用選項；之後若要接真正 TTS，只需新增一個繼承 `VoiceProvider` 的類別，並修改這個常數即可切換，不需改動呼叫端
- `main.py` 的 `export_voice(story)`：讀取每個 scene 的 `narration_zh`，呼叫目前的 Provider，輸出到 `output/audio/`；可獨立呼叫測試，不影響圖片流程

## Video Pipeline

- `generate_video.py`：影片合成模組，架構與 `generate_image.py` / `generate_voice.py` 一致（Provider 介面 + 可切換實作），**目前只有骨架，尚未實作真正的影片合成，也還沒接 FFmpeg**
  - `VideoProvider`：抽象介面，定義 `generate(image_path, audio_path, subtitle_path, output_path) -> Path`
  - `DummyVideoProvider`：不產生真正影片，只在 `output_path` 同名位置寫入 `.txt`（內容為傳入的圖片/音訊/字幕路徑），用來驗證 pipeline 骨架可以正常呼叫，最後回傳 `output_path`
  - `ACTIVE_PROVIDER = "dummy"`：目前唯一可用選項；之後若要接真正的影片合成，只需新增一個繼承 `VideoProvider` 的類別（例如呼叫 FFmpeg 的 Provider），並修改這個常數即可切換

### 規劃中的資料流向（尚未實作）

```
images/scene{N}.png ─┐
audio/scene{N}.mp3  ─┼─> FFmpeg（圖片 + 音訊 + SRT 字幕燒錄）─> output/videos/scene{N}.mp4
subtitles/scene{N}.srt ┘
```

每個 scene 產生 mp4 之後，下一階段會再把所有 scene 的 mp4 串接成完整集數影片；這部分也還沒規劃實作細節，目前僅先建立 Provider 架構。
