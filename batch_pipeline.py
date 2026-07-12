import json
from pathlib import Path

from character_manager import CharacterManager
from content_metadata import generate_cover_prompt, generate_youtube_metadata
from generate_image import ComfyUIProvider, DummyProvider, generate_scene_image
from generate_subtitle import generate_subtitle_srt
from generate_video import DummyVideoProvider, FFmpegVideoProvider, concatenate_episode, get_episode_video_paths
from generate_voice import DummyVoiceProvider, EdgeTTSProvider
from prompt_builder import PromptBuilder
from story_scanner import StoryScanner

RELEASE_DIR = Path(__file__).parent / "release"
WORKFLOW_PATH = Path(__file__).parent / "workflows" / "flux_schnell_basic.json"

# 與 main.py 的 ACTIVE_* 常數各自獨立：main.py 是單一故事（Genesis_001）的
# 既有手動流程，不因為這次新增 Batch Pipeline 而改變；batch_pipeline.py 是
# 給「一次處理 stories/ 底下所有故事」用的新入口，兩者互不影響。
ACTIVE_IMAGE_PROVIDER = "comfyui"  # "comfyui" 或 "dummy"
ACTIVE_VOICE_PROVIDER = "edge-tts"  # "edge-tts" 或 "dummy"
ACTIVE_VIDEO_PROVIDER = "ffmpeg"  # "ffmpeg" 或 "dummy"


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


class ReleasePaths:
    """依 story_id 算出 release/<story_id>/ 底下每個子資料夾的路徑，並負責建立它們。"""

    def __init__(self, story_id: str, release_dir: Path = None):
        base = Path(release_dir) if release_dir else RELEASE_DIR
        self.root = base / story_id
        self.image_prompts = self.root / "image_prompts"
        self.images = self.root / "images"
        self.audio = self.root / "audio"
        self.subtitles = self.root / "subtitles"
        self.videos = self.root / "videos"
        self.metadata = self.root / "metadata"
        self.episode_video = self.videos / f"{story_id}.mp4"

    def ensure_dirs(self):
        for directory in (
            self.image_prompts,
            self.images,
            self.audio,
            self.subtitles,
            self.videos,
            self.metadata,
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

    return count


def generate_images(story_data: dict, paths: ReleasePaths, prompt_builder: PromptBuilder) -> int:
    provider = get_image_provider()

    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        output_path = paths.images / f"scene{scene_number:03d}.png"
        generate_scene_image(scene, str(output_path), provider=provider, prompt_builder=prompt_builder)
        count += 1

    return count


def export_voice(story_data: dict, paths: ReleasePaths) -> int:
    provider = get_voice_provider()

    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")
        output_path = paths.audio / f"scene{scene_number:03d}.mp3"
        provider.generate(narration, output_path, language="zh-TW")
        count += 1

    return count


def export_subtitles(story_data: dict, paths: ReleasePaths) -> int:
    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")
        audio_path = paths.audio / f"scene{scene_number:03d}.mp3"
        output_path = paths.subtitles / f"scene{scene_number:03d}.srt"
        generate_subtitle_srt(narration, audio_path, output_path)
        count += 1

    return count


def generate_videos(story_data: dict, paths: ReleasePaths) -> int:
    provider = get_video_provider()

    count = 0
    for scene in story_data.get("scenes", []):
        scene_number = scene.get("scene_number")
        camera_id = scene.get("camera")

        image_path = paths.images / f"scene{scene_number:03d}.png"
        audio_path = paths.audio / f"scene{scene_number:03d}.mp3"
        subtitle_path = paths.subtitles / f"scene{scene_number:03d}.srt"
        output_path = paths.videos / f"scene{scene_number:03d}.mp4"

        provider.generate(image_path, audio_path, subtitle_path, output_path, camera_id=camera_id)
        count += 1

    return count


def generate_episode_video(story_data: dict, paths: ReleasePaths):
    video_paths = get_episode_video_paths(story_data, paths.videos)
    return concatenate_episode(video_paths, paths.episode_video)


def export_metadata(story_data: dict, paths: ReleasePaths, prompt_builder: PromptBuilder) -> tuple:
    cover_prompt = generate_cover_prompt(story_data, prompt_builder)
    (paths.metadata / "cover_prompt.txt").write_text(cover_prompt, encoding="utf-8")

    youtube_metadata = generate_youtube_metadata(story_data)
    (paths.metadata / "youtube_metadata.json").write_text(
        json.dumps(youtube_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return cover_prompt, youtube_metadata


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

    cover_prompt, youtube_metadata = export_metadata(story_data, paths, prompt_builder)
    result["cover_prompt"] = cover_prompt
    result["youtube_metadata"] = youtube_metadata

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
