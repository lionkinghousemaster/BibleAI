import json
from pathlib import Path

from engine.story import AnthropicProvider, DummyLLMProvider, StoryGenerator, generate_story_report

# "dummy"（離線測試，不需要 API 金鑰）或 "anthropic"（呼叫 Claude API，
# 需要設定 ANTHROPIC_API_KEY）。與 main.py／batch_pipeline.py 的
# ACTIVE_* 常數是同一種切換方式。
ACTIVE_LLM_PROVIDER = "dummy"

STORIES_DIR = Path(__file__).parent / "stories"

THEME = "亞當和夏娃在伊甸園裡，因禁不起蛇的誘惑吃了禁果，第一次感到害怕和羞愧，神仍然愛他們、也為他們預備衣服。"
EPISODE = "EP02"
BOOK = "創世記 (Genesis)"
CHAPTER = "3"
TITLE_ZH = "禁果的誘惑"
TITLE_EN = "The Forbidden Fruit"
SCENE_COUNT = 6


def get_llm_provider():
    if ACTIVE_LLM_PROVIDER == "anthropic":
        return AnthropicProvider()
    return DummyLLMProvider()


def generate_and_export(output_dir: Path = None) -> Path:
    """產生一部故事，輸出 <output_dir>/<episode 對應檔名>.json 與
    story_report.txt，回傳寫入的故事 JSON 路徑。output_dir 省略時預設寫入
    專案根目錄的 stories/，與 batch_pipeline.py 掃描的位置一致。
    """
    output_dir = Path(output_dir) if output_dir else STORIES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    generator = StoryGenerator(llm_provider=get_llm_provider())
    story = generator.generate(
        theme=THEME,
        episode=EPISODE,
        book=BOOK,
        chapter=CHAPTER,
        title_zh=TITLE_ZH,
        title_en=TITLE_EN,
        scene_count=SCENE_COUNT,
    )

    story_path = output_dir / f"Genesis_{EPISODE.replace('EP', '').zfill(3)}.json"
    story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = output_dir / "story_report.txt"
    report_path.write_text(generate_story_report(story), encoding="utf-8")

    return story_path


def main():
    story_path = generate_and_export()
    print(f"已產生故事：{story_path}")
    print(f"已輸出 story_report.txt 到 {story_path.parent}")


if __name__ == "__main__":
    main()
