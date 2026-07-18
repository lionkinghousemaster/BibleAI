"""Story Engine。

`StoryGenerator` 依主題自動產生符合 `stories/*.json` 格式的故事（見
generator.py），內容生成透過 `LLMProvider` 抽象介面（見 llm_provider.py：
`DummyLLMProvider` 離線測試用、`AnthropicProvider` 呼叫 Claude API），
`generate_story_report` 產生方便人工檢視的 story_report.txt（見
report.py）。呼叫端只需要 `from engine.story import StoryGenerator, ...`，
不需要理會內部檔案如何切分。

尚未遷入：目前故事「掃描」邏輯（讀取 stories/ 底下既有 JSON）仍在專案根
目錄的 `story_scanner.py`（`StoryScanner`）。未來遷入時會把它移到這裡，
並在此 re-export，維持與 `engine.prompt` 相同的對外介面風格。
"""

from .generator import StoryGenerator
from .llm_provider import AnthropicProvider, DummyLLMProvider, LLMProvider
from .report import generate_story_report

__all__ = [
    "StoryGenerator",
    "LLMProvider",
    "DummyLLMProvider",
    "AnthropicProvider",
    "generate_story_report",
]
