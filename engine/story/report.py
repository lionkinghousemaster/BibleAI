MODULE_ORDER = ["characters", "camera", "lighting", "composition", "style"]


def generate_story_report(story_data: dict) -> str:
    """產生 StoryGenerator 生成結果的 story_report.txt 內容：逐 scene 列出
    角色／鏡頭／lighting／composition／style 的實際取值（省略的欄位顯示
    "(default)"，代表交由 PromptLibrary 的 manifest 預設值決定），以及
    narration／image_prompt／animation_prompt／subtitle 的字數與內容，
    方便在丟進 batch_pipeline.py 之前，人工檢視生成內容是否合理。

    刻意不重算 PromptBuilder 才有的 token/去重資訊——那是 image_prompt
    真正組裝時的事，story_report.txt 只檢視 StoryGenerator 自己產出的
    原始故事結構。
    """
    lines = ["BibleAI Story Generator Report", "=" * 60, ""]

    lines.append(f"Book: {story_data.get('book', '')}")
    lines.append(f"Episode: {story_data.get('episode', '')}")
    lines.append(f"Title: {story_data.get('title_zh', '')} / {story_data.get('title_en', '')}")
    lines.append(f"Duration: {story_data.get('duration', '')}")
    lines.append(f"Language: {', '.join(story_data.get('language', []))}")

    scenes = story_data.get("scenes", [])
    lines.append(f"Scene count: {len(scenes)}")
    lines.append("")

    for scene in scenes:
        lines.append(f"Scene {scene.get('scene_number', 0):03d}: {scene.get('title', '')}")
        lines.append("-" * 40)

        module_values = {
            "characters": ", ".join(scene.get("characters", [])) or "(none)",
            "camera": scene.get("camera") or "(none)",
            "lighting": scene.get("lighting") or "(default)",
            "composition": scene.get("composition") or "(default)",
            "style": scene.get("style") or "(default)",
        }
        for category in MODULE_ORDER:
            lines.append(f"  {category:<12} {module_values[category]}")

        narration_zh = scene.get("narration_zh", "")
        narration_en = scene.get("narration_en", "")
        lines.append(f"  {'narration_zh':<12} chars={len(narration_zh):>4}  {narration_zh}")
        lines.append(f"  {'narration_en':<12} chars={len(narration_en):>4}  {narration_en}")
        lines.append(f"  {'image_prompt':<12} {scene.get('image_prompt', '')}")
        lines.append(f"  {'animation':<12} {scene.get('animation_prompt', '')}")
        lines.append(f"  {'subtitle':<12} {scene.get('subtitle', '')}")
        lines.append(f"  {'duration':<12} {scene.get('duration', 0)}s")
        lines.append("")

    return "\n".join(lines)
