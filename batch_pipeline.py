import json
from pathlib import Path

from character_manager import CharacterManager
from content_metadata import build_upload_payload, generate_cover_prompt, generate_youtube_metadata
from engine.prompt import PromptBuilder, generate_prompt_report
from engine.publish import DummyUploadProvider, YouTubeUploadProvider
from generate_image import ComfyUIProvider, DummyProvider, generate_image_from_prompt, generate_scene_image
from generate_subtitle import generate_subtitle_srt
from generate_video import DummyVideoProvider, FFmpegVideoProvider, concatenate_episode, get_episode_video_paths
from generate_voice import DummyVoiceProvider, EdgeTTSProvider
from story_scanner import StoryScanner

RELEASE_DIR = Path(__file__).parent / "release"
WORKFLOW_PATH = Path(__file__).parent / "workflows" / "flux_schnell_basic.json"

# 與 main.py 的 ACTIVE_* 常數各自獨立：main.py 是單一故事（Genesis_001）的
# 既有手動流程，不因為這次新增 Batch Pipeline 而改變；batch_pipeline.py 是
# 給「一次處理 stories/ 底下所有故事」用的新入口，兩者互不影響。
ACTIVE_IMAGE_PROVIDER = "comfyui"  # "comfyui" 或 "dummy"
ACTIVE_VOICE_PROVIDER = "edge-tts"  # "edge-tts" 或 "dummy"
ACTIVE_VIDEO_PROVIDER = "ffmpeg"  # "ffmpeg" 或 "dummy"
# 預設 "dummy"：真正上傳到 YouTube 需要事先完成 Google OAuth 設定（見
# engine/publish/uploader.py 的 YouTubeUploadProvider docstring），改成
# "youtube" 前請確認 youtube_client_secrets.json 已就緒。
ACTIVE_UPLOAD_PROVIDER = "dummy"  # "youtube" 或 "dummy"


def get_image_provider():
    if ACTIVE_IMAGE_PROVIDER == "comfyui":
        return ComfyUIProvider(
            workflow_path=str(WORKFLOW_PATH),
            positive_prompt_node_id="2",
            save_image_node_id="7",
            seed_node_id="5",
            negative_prompt_node_id="3",
        )
    return DummyProvider()


def get_voice_provider():
    if ACTIVE_VOICE_PROVIDER == "edge-tts":
        return EdgeTTSProvider()
    return DummyVoiceProvider()


def get_video_provider():
    if ACTIVE_VIDEO_PROVIDER == "ffmpeg":
        return FFmpegVideoProvider()
    return DummyVideoProvider()


def get_upload_provider():
    if ACTIVE_UPLOAD_PROVIDER == "youtube":
        return YouTubeUploadProvider()
    return DummyUploadProvider()


class ReleasePaths:
    """依 story_id 算出 release/<story_id>/ 底下統一的三大資料夾：
    video/、image/、metadata/，並負責建立它們（含必要子資料夾）。

    - video/：audio/、subtitles/（配音與字幕，最終影片的素材）、逐 scene
      的 mp4（扁平放在 video/ 底下）、以及整集影片 video/<story_id>.mp4
    - image/：prompts/（每個 scene 的 image_prompt debug 匯出）、逐 scene
      的最終 png（扁平放在 image/ 底下）、以及封面 image/cover_image.png
    - metadata/：cover_prompt.txt、metadata.json、title.txt、
      description.txt、tags.txt、upload.json
    """

    def __init__(self, story_id: str, release_dir: Path = None):
        base = Path(release_dir) if release_dir else RELEASE_DIR
        self.root = base / story_id

        self.video_dir = self.root / "video"
        self.image_dir = self.root / "image"
        self.metadata_dir = self.root / "metadata"

        self.audio = self.video_dir / "audio"
        self.subtitles = self.video_dir / "subtitles"
        self.episode_video = self.video_dir / f"{story_id}.mp4"

        self.image_prompts = self.image_dir / "prompts"
        self.cover_image = self.image_dir / "cover_image.png"

    def scene_video_path(self, scene_number: int) -> Path:
        return self.video_dir / f"scene{scene_number:03d}.mp4"

    def scene_image_path(self, scene_number: int) -> Path:
        return self.image_dir / f"scene{scene_number:03d}.png"

    def scene_audio_path(self, scene_number: int) -> Path:
        return self.audio / f"scene{scene_number:03d}.mp3"

    def scene_subtitle_path(self, scene_number: int) -> Path:
        return self.subtitles / f"scene{scene_number:03d}.srt"

    def ensure_dirs(self):
        for directory in (
            self.video_dir,
            self.image_dir,
            self.metadata_dir,
            self.audio,
            self.subtitles,
            self.image_prompts,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def export_image_prompts(story_data: dict, paths: ReleasePaths, prompt_builder: PromptBuilder) -> int:
    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        image_prompt = scene.get("image_prompt", "")

        (paths.image_prompts / f"scene{scene_number:03d}.txt").write_text(image_prompt, encoding="utf-8")

        positive_prompt, positive_log = prompt_builder.build_positive_prompt_with_debug(scene)
        negative_prompt, negative_log = prompt_builder.build_negative_prompt_with_debug(scene)

        (paths.image_prompts / f"scene{scene_number:03d}_positive_prompt.txt").write_text(
            positive_prompt, encoding="utf-8"
        )
        (paths.image_prompts / f"scene{scene_number:03d}_negative_prompt.txt").write_text(
            negative_prompt, encoding="utf-8"
        )

        final_lines = ["[POSITIVE]", positive_prompt, "", "[NEGATIVE]", negative_prompt]
        debug_log = positive_log + negative_log
        if debug_log:
            final_lines += ["", "[DEBUG LOG]"] + debug_log
        (paths.image_prompts / f"scene{scene_number:03d}_final_prompt.txt").write_text(
            "\n".join(final_lines), encoding="utf-8"
        )

        count += 1

    report_text = generate_prompt_report(story_data, prompt_builder)
    (paths.image_prompts / "prompt_report.txt").write_text(report_text, encoding="utf-8")

    return count


def generate_images(story_data: dict, paths: ReleasePaths, prompt_builder: PromptBuilder) -> int:
    provider = get_image_provider()

    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        output_path = paths.scene_image_path(scene_number)
        generate_scene_image(scene, str(output_path), provider=provider, prompt_builder=prompt_builder)
        count += 1

    return count


def export_voice(story_data: dict, paths: ReleasePaths) -> int:
    provider = get_voice_provider()

    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")
        output_path = paths.scene_audio_path(scene_number)
        provider.generate(narration, output_path, language="zh-TW")
        count += 1

    return count


def export_subtitles(story_data: dict, paths: ReleasePaths) -> int:
    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")
        audio_path = paths.scene_audio_path(scene_number)
        output_path = paths.scene_subtitle_path(scene_number)
        generate_subtitle_srt(narration, audio_path, output_path)
        count += 1

    return count


def generate_videos(story_data: dict, paths: ReleasePaths) -> int:
    provider = get_video_provider()

    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        camera_id = scene.get("camera")

        image_path = paths.scene_image_path(scene_number)
        audio_path = paths.scene_audio_path(scene_number)
        subtitle_path = paths.scene_subtitle_path(scene_number)
        output_path = paths.scene_video_path(scene_number)

        provider.generate(image_path, audio_path, subtitle_path, output_path, camera_id=camera_id)
        count += 1

    return count


def generate_episode_video(story_data: dict, paths: ReleasePaths):
    video_paths = get_episode_video_paths(story_data, paths.video_dir)
    return concatenate_episode(video_paths, paths.episode_video)


def generate_cover_image(story_data: dict, paths: ReleasePaths, prompt_builder: PromptBuilder, provider=None) -> str:
    """自動組出封面 prompt，並呼叫真正的 ImageProvider 產生 image/cover_image.png。"""
    cover_prompt = generate_cover_prompt(story_data, prompt_builder)
    image_provider = provider or get_image_provider()
    generate_image_from_prompt(cover_prompt, str(paths.cover_image), provider=image_provider)
    return cover_prompt


def load_previous_upload_result(paths: ReleasePaths) -> dict:
    """讀取上一次執行留下的 upload.json，若該故事已經真正上傳成功
    （`upload_status == "uploaded"`），回傳其 upload_status/video_id/
    published_at/thumbnail_path，讓 upload_video() 可以跳過重複上傳。
    找不到檔案、格式錯誤、或尚未上傳成功，一律回傳空 dict，不丟例外。
    """
    upload_json_path = paths.metadata_dir / "upload.json"
    if not upload_json_path.exists():
        return {}

    try:
        previous = json.loads(upload_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if previous.get("upload_status") != "uploaded":
        return {}

    return {
        "upload_status": previous.get("upload_status"),
        "video_id": previous.get("video_id"),
        "published_at": previous.get("published_at"),
        "thumbnail_path": previous.get("thumbnail_path"),
    }


def upload_video(paths: ReleasePaths, upload_payload: dict) -> dict:
    """把 upload_payload（snippet/status）連同整集影片與封面圖交給
    UploadProvider 實際上傳，回傳更新後的 upload_payload（補上
    upload_status/video_id/published_at/thumbnail_path）。

    若上一次執行已經成功上傳過（見 load_previous_upload_result），直接
    沿用舊有的 video_id 等欄位、不重複呼叫上傳 API，避免同一部作品被
    重複上傳。整集影片還不存在（例如影片合成失敗）時，同樣跳過上傳，
    upload_status 維持 build_upload_payload() 給的預設值 "not_uploaded"。
    """
    previous_result = load_previous_upload_result(paths)
    if previous_result:
        upload_payload.update(previous_result)
        return upload_payload

    if not paths.episode_video.exists():
        return upload_payload

    provider = get_upload_provider()
    thumbnail_path = paths.cover_image if paths.cover_image.exists() else None
    result = provider.upload(paths.episode_video, upload_payload, thumbnail_path=thumbnail_path)
    upload_payload.update(result)

    return upload_payload


def export_metadata(story_data: dict, paths: ReleasePaths, prompt_builder: PromptBuilder, story_id: str) -> tuple:
    cover_prompt = generate_cover_image(story_data, paths, prompt_builder)
    (paths.metadata_dir / "cover_prompt.txt").write_text(cover_prompt, encoding="utf-8")

    youtube_metadata = generate_youtube_metadata(story_data)

    metadata_json = {
        "story_id": story_id,
        "book": story_data.get("book", ""),
        "episode": story_data.get("episode", ""),
        "chapter": story_data.get("chapter", ""),
        "scene_count": len(story_data.get("scenes", [])),
        "title": youtube_metadata["title"],
        "description": youtube_metadata["description"],
        "tags": youtube_metadata["tags"],
    }
    (paths.metadata_dir / "metadata.json").write_text(
        json.dumps(metadata_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (paths.metadata_dir / "title.txt").write_text(youtube_metadata["title"], encoding="utf-8")
    (paths.metadata_dir / "description.txt").write_text(youtube_metadata["description"], encoding="utf-8")
    (paths.metadata_dir / "tags.txt").write_text("\n".join(youtube_metadata["tags"]), encoding="utf-8")

    upload_payload = build_upload_payload(story_id, youtube_metadata)
    upload_payload = upload_video(paths, upload_payload)
    (paths.metadata_dir / "upload.json").write_text(
        json.dumps(upload_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return cover_prompt, metadata_json, upload_payload


def process_story(story_entry: dict, release_dir: Path = None) -> dict:
    """處理單一故事的完整 pipeline（image/voice/subtitle/video/episode/metadata），
    回傳這個故事的產出統計，供 run_batch 彙整報告用。
    """
    story_id = story_entry["story_id"]
    story_data = story_entry["data"]

    paths = ReleasePaths(story_id, release_dir=release_dir)
    paths.ensure_dirs()

    character_manager = CharacterManager()
    prompt_builder = PromptBuilder(character_manager=character_manager)

    result = {"story_id": story_id, "release_dir": str(paths.root)}

    result["image_prompt_count"] = export_image_prompts(story_data, paths, prompt_builder)
    result["image_count"] = generate_images(story_data, paths, prompt_builder)
    result["voice_count"] = export_voice(story_data, paths)
    result["subtitle_count"] = export_subtitles(story_data, paths)

    try:
        result["video_count"] = generate_videos(story_data, paths)
        result["episode_video"] = str(generate_episode_video(story_data, paths))
    except Exception as e:
        # 影片失敗不影響已經完成的圖片／配音／字幕，也不該讓其他故事無法處理。
        result["video_error"] = str(e)

    cover_prompt, metadata_json, upload_payload = export_metadata(story_data, paths, prompt_builder, story_id)
    result["cover_prompt"] = cover_prompt
    result["cover_image"] = str(paths.cover_image)
    result["metadata"] = metadata_json
    result["upload_payload"] = upload_payload

    return result


def run_batch(stories_dir: Path = None, release_dir: Path = None) -> list:
    """掃描 stories_dir 底下所有故事，逐一跑完整 pipeline。

    單一故事處理失敗不會讓整批中斷——記錄錯誤後繼續處理下一個故事，
    最後在 release_dir/batch_report.json 留下這次批次執行的完整記錄。
    """
    scanner = StoryScanner(stories_dir)
    story_entries = scanner.scan()

    results = []
    for story_entry in story_entries:
        story_id = story_entry["story_id"]
        print(f"=== 開始處理故事：{story_id} ===")
        try:
            result = process_story(story_entry, release_dir=release_dir)
            print(f"=== 完成故事：{story_id} ===")
        except Exception as e:
            result = {"story_id": story_id, "error": str(e)}
            print(f"=== 故事處理失敗：{story_id}（{e}），略過，繼續處理下一個 ===")
        results.append(result)

    report_dir = Path(release_dir) if release_dir else RELEASE_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "batch_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    return results


if __name__ == "__main__":
    run_batch()
