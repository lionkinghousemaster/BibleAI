from .builder import PromptBuilder

MODULE_ORDER = ["character", "environment", "lighting", "composition", "style", "negative"]


def generate_prompt_report(story_data: dict, prompt_builder: PromptBuilder = None) -> str:
    """產生整部作品的 prompt_report.txt 內容：逐 scene 列出各模組
    （Character/Environment/Lighting/Composition/Style/Negative）的字元數、
    token 數、來源（preset 檔案路徑或 Manager 名稱）與 Token Budget 權重，
    以及 PromptOptimizer 的去重／裁剪紀錄，方便人工檢視 Prompt Engine
    的運作狀況，以及確認每個模組實際是從哪個來源載入的。
    """
    builder = prompt_builder or PromptBuilder()
    lines = ["BibleAI Prompt Engine Report", "=" * 60, ""]

    for scene in story_data.get("scenes", []):
        entry = builder.build_prompt_report_entry(scene)
        lines.append(f"Scene {entry['scene_number']:03d}")
        lines.append("-" * 40)

        for category in MODULE_ORDER:
            info = entry["module_info"].get(category, {"chars": 0, "tokens": 0, "source": "-", "weight": "-"})
            lines.append(
                f"  {category:<12} chars={info['chars']:>5}  tokens={info['tokens']:>4}  "
                f"weight={str(info['weight']):<9}  source={info['source']}"
            )

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
