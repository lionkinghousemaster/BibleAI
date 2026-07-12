"""Prompt Engine：Prompt 組裝與最佳化。

對外只需要從這裡 import，不需要知道內部檔案是 library.py／builder.py／
optimizer.py／report.py 這樣拆的：

    from engine.prompt import PromptBuilder, generate_prompt_report

- `PromptLibrary`（library.py）：Style/Lighting/Composition/Negative
  模板與權重的集中管理入口（讀 `prompts/*.json` + `prompts/manifest.json`）
- `PromptOptimizer`（optimizer.py）：去重 + Priority Token Budget 裁剪
- `PromptBuilder`（builder.py）：組裝層，串接 CharacterManager +
  PromptLibrary + PromptOptimizer
- `generate_prompt_report`（report.py）：產生人工可讀的 prompt_report.txt
"""

from .builder import PromptBuilder
from .library import PromptLibrary
from .optimizer import PromptOptimizer
from .report import generate_prompt_report

__all__ = ["PromptBuilder", "PromptLibrary", "PromptOptimizer", "generate_prompt_report"]
