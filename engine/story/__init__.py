"""Story Engine。

`StoryScanner` 掃描 `stories/` 底下既有的故事 JSON（見 scanner.py）；
`StoryGenerator` 依主題自動產生符合 `stories/*.json` 格式的新故事（見
generator.py），內容生成透過 `LLMProvider` 抽象介面（見 llm_provider.py：
`DummyLLMProvider` 離線測試用、`AnthropicProvider` 呼叫 Claude API），
`generate_story_report` 產生方便人工檢視的 story_report.txt（見
report.py）。呼叫端只需要 `from engine.story import StoryScanner, StoryGenerator, ...`，
不需要理會內部檔案如何切分。
"""

from .generator import StoryGenerator
from .llm_provider import AnthropicProvider, DummyLLMProvider, LLMProvider
from .report import generate_story_report
from .scanner import StoryScanner

__all__ = [
    "StoryScanner",
    "StoryGenerator",
    "LLMProvider",
    "DummyLLMProvider",
    "AnthropicProvider",
    "generate_story_report",
]
