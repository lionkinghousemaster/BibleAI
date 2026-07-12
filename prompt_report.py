from prompt_builder import PromptBuilder

MODULE_ORDER = ["character", "environment", "lighting", "composition", "style", "negative"]


def generate_prompt_report(story_data: dict, prompt_builder: PromptBuilder = None) -> str:
    """產生整部作品的 prompt_report.txt 內容：逐 scene 列出各模組
    （Character/Environment/Lighting/Composition/Style/Negative）的字元數、
    token 數，以及 PromptOptimizer 的去重／Token Budget 裁剪紀錄，方便
    人工檢視 Prompt Engine 的運作狀況。
    """
    builder = prompt_builder or PromptBuilder()
    lines = ["BibleAI Prompt Engine Report", "=" * 60, ""]

    for scene in story_data.get("scenes", []):
        entry = builder.build_prompt_report_entry(scene)
        lines.append(f"Scene {entry['scene_number']:03d}")
        lines.append("-" * 40)

        for category in MODULE_ORDER:
            stats = entry["module_stats"].get(category, {"chars": 0, "tokens": 0})
            lines.append(f"  {category:<12} chars={stats['chars']:>5}  tokens={stats['tokens']:>4}")

        lines.append(
            f"  {'FINAL positive':<12} chars={entry['final_positive_chars']:>5}  "
            f"tokens={entry['final_positive_tokens']:>4}"
        )
        lines.append(
            f"  {'FINAL negative':<12} chars={entry['final_negative_chars']:>5}  "
            f"tokens={entry['final_negative_tokens']:>4}"
        )

        if entry["debug_log"]:
            lines.append("  Debug Log:")
            for log_line in entry["debug_log"]:
                lines.append(f"    {log_line}")

        lines.append("")

    return "\n".join(lines)
