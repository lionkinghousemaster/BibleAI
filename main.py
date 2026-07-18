import json
from pathlib import Path

from character_manager import CharacterManager
from engine.image import ComfyUIProvider, DummyProvider, generate_scene_image
from engine.prompt import PromptBuilder, generate_prompt_report
from engine.video import DummyVideoProvider, FFmpegVideoProvider, concatenate_episode, get_episode_video_paths
from generate_subtitle import generate_subtitle_srt
from generate_voice import DummyVoiceProvider, EdgeTTSProvider

STORY_PATH = Path(__file__).parent / "stories" / "Genesis_001.json"
IMAGE_PROMPTS_DIR = Path(__file__).parent / "output" / "image_prompts"
IMAGES_DIR = Path(__file__).parent / "output" / "images"
AUDIO_DIR = Path(__file__).parent / "output" / "audio"
SUBTITLES_DIR = Path(__file__).parent / "output" / "subtitles"
VIDEOS_DIR = Path(__file__).parent / "output" / "videos"
WORKFLOW_PATH = Path(__file__).parent / "workflows" / "flux_schnell_basic.json"
EPISODE_OUTPUT_PATH = VIDEOS_DIR / "Genesis_EP01.mp4"

ACTIVE_PROVIDER = "comfyui"  # "comfyui" 或 "dummy"（圖片）
ACTIVE_VOICE_PROVIDER = "edge-tts"  # "edge-tts" 或 "dummy"（配音）
ACTIVE_VIDEO_PROVIDER = "ffmpeg"  # "ffmpeg" 或 "dummy"（影片合成）


def get_provider():
    if ACTIVE_PROVIDER == "comfyui":
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


def export_image_prompts(story):
    IMAGE_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    prompt_builder = PromptBuilder(character_manager=CharacterManager())

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        image_prompt = scene.get("image_prompt", "")

        file_path = IMAGE_PROMPTS_DIR / f"scene{scene_number:03d}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(image_prompt)

        positive_prompt, positive_log = prompt_builder.build_positive_prompt_with_debug(scene)
        negative_prompt, negative_log = prompt_builder.build_negative_prompt_with_debug(scene)

        positive_path = IMAGE_PROMPTS_DIR / f"scene{scene_number:03d}_positive_prompt.txt"
        with open(positive_path, "w", encoding="utf-8") as f:
            f.write(positive_prompt)

        negative_path = IMAGE_PROMPTS_DIR / f"scene{scene_number:03d}_negative_prompt.txt"
        with open(negative_path, "w", encoding="utf-8") as f:
            f.write(negative_prompt)

        final_path = IMAGE_PROMPTS_DIR / f"scene{scene_number:03d}_final_prompt.txt"
        with open(final_path, "w", encoding="utf-8") as f:
            f.write("[POSITIVE]\n")
            f.write(positive_prompt)
            f.write("\n\n[NEGATIVE]\n")
            f.write(negative_prompt)
            debug_log = positive_log + negative_log
            if debug_log:
                f.write("\n\n[DEBUG LOG]\n")
                f.write("\n".join(debug_log))

        count += 1

    report_text = generate_prompt_report(story, prompt_builder)
    (IMAGE_PROMPTS_DIR / "prompt_report.txt").write_text(report_text, encoding="utf-8")

    return count


def generate_images(story):
    provider = get_provider()
    prompt_builder = PromptBuilder(character_manager=CharacterManager())

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")

        output_path = IMAGES_DIR / f"scene{scene_number:03d}.png"
        generate_scene_image(scene, str(output_path), provider=provider, prompt_builder=prompt_builder)
        count += 1

    return count


def export_voice(story):
    provider = get_voice_provider()

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")

        output_path = AUDIO_DIR / f"scene{scene_number:03d}.mp3"
        provider.generate(narration, output_path, language="zh-TW")
        count += 1

    return count


def export_subtitles(story):
    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")

        audio_path = AUDIO_DIR / f"scene{scene_number:03d}.mp3"
        output_path = SUBTITLES_DIR / f"scene{scene_number:03d}.srt"
        generate_subtitle_srt(narration, audio_path, output_path)
        count += 1

    return count


def generate_videos(story):
    provider = get_video_provider()

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        camera_id = scene.get("camera")

        image_path = IMAGES_DIR / f"scene{scene_number:03d}.png"
        audio_path = AUDIO_DIR / f"scene{scene_number:03d}.mp3"
        subtitle_path = SUBTITLES_DIR / f"scene{scene_number:03d}.srt"
        output_path = VIDEOS_DIR / f"scene{scene_number:03d}.mp4"

        provider.generate(image_path, audio_path, subtitle_path, output_path, camera_id=camera_id)
        count += 1

    return count


def generate_episode_video(story):
    video_paths = get_episode_video_paths(story, VIDEOS_DIR)
    return concatenate_episode(video_paths, EPISODE_OUTPUT_PATH)


def main():
    try:
        with open(STORY_PATH, "r", encoding="utf-8") as f:
            story = json.load(f)
    except FileNotFoundError:
        print(f"錯誤：找不到檔案 {STORY_PATH}")
        return

    print("BibleAI 啟動成功")
    print("Genesis_001.json 已讀取")

    count = export_image_prompts(story)
    print(f"已輸出 {count} 個 image_prompt 到 {IMAGE_PROMPTS_DIR}")

    image_count = generate_images(story)
    print(f"已產生 {image_count} 張圖片到 {IMAGES_DIR}")

    voice_count = export_voice(story)
    print(f"已產生 {voice_count} 個語音檔到 {AUDIO_DIR}")

    subtitle_count = export_subtitles(story)
    print(f"已產生 {subtitle_count} 個字幕檔到 {SUBTITLES_DIR}")

    try:
        video_count = generate_videos(story)
        print(f"已產生 {video_count} 個 scene 影片到 {VIDEOS_DIR}")

        episode_path = generate_episode_video(story)
        print(f"已串接完整集數影片：{episode_path}")
    except Exception as e:
        print(f"影片產生失敗（不影響已完成的圖片／配音／字幕）：{e}")


if __name__ == "__main__":
    main()
