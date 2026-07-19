"""Director（視覺語意決策層）：依 scene 的敘事語意自動決定 lighting／
composition／camera_shot／camera_angle／mood，取代 PromptBuilder 過去單純
依賴 PromptLibrary 固定 default preset 的做法（v0.9 Director Intelligence
Sprint 新增）。詳見 `director.py` 的模組說明。
"""

from .director import (
    DEFAULT_DECISION,
    THEME_PRIORITY,
    THEMES,
    classify_scene_theme,
    decide_visual_plan,
    resolve_visual_plan,
)

__all__ = [
    "THEMES",
    "THEME_PRIORITY",
    "DEFAULT_DECISION",
    "classify_scene_theme",
    "decide_visual_plan",
    "resolve_visual_plan",
]
