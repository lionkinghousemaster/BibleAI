import json
from pathlib import Path

from character_manager import CharacterManager
from generate_image import ComfyUIProvider, DummyProvider, build_character_aware_prompt, generate_image_from_prompt
from generate_voice import get_provider as get_voice_provider

STORY_PATH = Path(__file__).parent / "stories" / "Genesis_001.json"
IMAGE_PROMPTS_DIR = Path(__file__).parent / "output" / "image_prompts"
IMAGES_DIR = Path(__file__).parent / "output" / "images"
AUDIO_DIR = Path(__file__).parent / "output" / "audio"
WORKFLOW_PATH = Path(__file__).parent / "workflows" / "flux_schnell_basic.json"

ACTIVE_PROVIDER = "comfyui"  # "comfyui" 或 "dummy"


def get_provider():
    if ACTIVE_PROVIDER == "comfyui":
        return ComfyUIProvider(
            workflow_path=str(WORKFLOW_PATH),
            positive_prompt_node_id="2",
            save_image_node_id="7",
            seed_node_id="5",
        )
    return DummyProvider()


def export_image_prompts(story):
    IMAGE_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        image_prompt = scene.get("image_prompt", "")

        file_path = IMAGE_PROMPTS_DIR / f"scene{scene_number:03d}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(image_prompt)
        count += 1

    return count


def generate_images(story):
    provider = get_provider()
    character_manager = CharacterManager()

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        image_prompt = scene.get("image_prompt", "")
        characters = scene.get("characters", [])

        final_prompt = build_character_aware_prompt(image_prompt, characters, character_manager)

        output_path = IMAGES_DIR / f"scene{scene_number:03d}.png"
        generate_image_from_prompt(final_prompt, str(output_path), provider=provider)
        count += 1

    return count


def export_voice(story):
    provider = get_voice_provider()

    count = 0
    for scene in story.get("scenes", []):
        scene_number = scene.get("scene_number")
        narration = scene.get("narration_zh", "")

        output_path = AUDIO_DIR / f"scene{scene_number:03d}.wav"
        provider.generate(narration, output_path, language="zh-TW")
        count += 1

    return count


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


if __name__ == "__main__":
    main()
