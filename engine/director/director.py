"""Director（視覺語意決策層）：依 scene 的敘事語意（narration／animation_prompt／
title）自動判斷這是哪一種戲劇情境——建立（creation）、衝突（conflict）、
高潮（climax）、悲傷（sadness）、喜樂（joy）、神顯現（divine_appearance）——
再依判斷結果決定這個 scene 該用哪個 lighting／composition／camera_shot／
camera_angle／mood。

跟 `engine.prompt.importance` 是同一種設計風格：不讀寫任何檔案、不保存狀態，
單純的規則函式，PromptBuilder／StoryGenerator 直接呼叫即可。theme 判斷規則
（關鍵字表）刻意用程式碼常數表示，而不是外部 JSON——這些是「導演邏輯」，
不是像 prompts/*.json 那樣單純的文字模板，跟 importance.py 的 SIGNAL_WEIGHTS
是同樣的取捨（規則本身需要跟著程式邏輯一起版本控制與測試，不是純資料）。
"""

import re

#: 判斷優先順序：一個 scene 可能同時命中多個 theme（例如「神生氣地審判」
#: 同時符合 divine_appearance 與 conflict），依這個順序取第一個命中的當作
#: 主導 theme。divine_appearance 優先權最高——這系列故事的核心角色是神，
#: 神顯現的場景理應優先用最莊嚴的視覺語言呈現，即使同時帶有其他情緒。
THEME_PRIORITY = ["divine_appearance", "climax", "conflict", "sadness", "joy", "creation"]

THEMES = {
    "divine_appearance": {
        "keywords_zh": ["神說", "神看", "神的靈", "神造", "神顯現", "神同在", "神的榮耀", "神愛", "神賜福", "神照著自己的樣式"],
        "keywords_en": [
            "god said", "god saw", "god's spirit", "god made", "god appeared",
            "god's presence", "god's glory", "the lord", "god loved", "god blessed",
        ],
        "lighting": "golden_hour",
        "composition": "wide_shot",
        "camera_shot": "slow_zoom_out",
        "camera_angle": "low_angle",
        "mood": "awe",
    },
    "climax": {
        "keywords_zh": ["終於", "就在這時", "突然", "沒想到", "關鍵的一刻", "決定性"],
        "keywords_en": ["suddenly", "at last", "finally", "the moment", "everything changed", "turning point"],
        "lighting": "dramatic",
        "composition": "close_up",
        "camera_shot": "slow_zoom_in",
        "camera_angle": "low_angle",
        "mood": "dramatic",
    },
    "conflict": {
        "keywords_zh": ["爭吵", "生氣", "嫉妒", "打", "違背", "犯罪", "誘惑", "欺騙", "搶奪"],
        "keywords_en": ["angry", "jealous", "fight", "argu", "disobey", "sin", "tempt", "deceiv", "quarrel"],
        "lighting": "night",
        "composition": "close_up",
        "camera_shot": "pan_left",
        "camera_angle": "high_angle",
        "mood": "tense",
    },
    "sadness": {
        "keywords_zh": ["哭", "傷心", "難過", "眼淚", "失去", "孤單", "痛苦", "後悔"],
        "keywords_en": ["cry", "cried", "sad", "tears", "sorrow", "lonely", "lost", "grief", "weep"],
        "lighting": "night",
        "composition": "close_up",
        "camera_shot": "slow_zoom_in",
        "camera_angle": "eye_level",
        "mood": "somber",
    },
    "joy": {
        "keywords_zh": ["開心", "快樂", "歡喜", "笑", "慶祝", "喜樂"],
        "keywords_en": ["happy", "joy", "joyful", "laugh", "celebrat", "delight"],
        "lighting": "golden_hour",
        "composition": "default",
        "camera_shot": "pan_right",
        "camera_angle": "eye_level",
        "mood": "joyful",
    },
    "creation": {
        "keywords_zh": ["創造", "造了", "出現了", "誕生", "長出", "分開", "充滿"],
        "keywords_en": ["created", "appeared", "formed", "separated", "brought forth", "filled with"],
        "lighting": "golden_hour",
        "composition": "wide_shot",
        "camera_shot": "slow_zoom_out",
        "camera_angle": "eye_level",
        "mood": "wonder",
    },
}

#: 沒有任何 theme 命中時的中性預設值——刻意跟 PromptLibrary／manifest.json
#: 原本的 default preset id 一致，維持「沒有語意信號時行為不變」的相容性。
DEFAULT_DECISION = {
    "lighting": "default",
    "composition": "default",
    "camera_shot": "static",
    "camera_angle": "eye_level",
    "mood": "neutral",
}

#: Director 會依 scene 內容自動決定、但 scene 仍可手動覆寫的欄位。
#: `camera_shot` 對應的是 scene["camera"]（獨立欄位名稱，見 resolve_visual_plan）。
OVERRIDABLE_FIELDS = ("lighting", "composition", "camera_angle", "mood")


def _find_matches(text: str, keywords: list) -> list:
    """回傳 `keywords` 裡有出現在 `text` 的關鍵字列表（依原順序，不去重）。

    英文關鍵字用「左邊字界」regex（`\\bKEYWORD`，只要求關鍵字開頭前是字界，
    結尾不要求）比對，而不是單純子字串——關鍵字表裡有些故意只寫詞幹
    （`argu`／`tempt`／`celebrat`／`deceiv`）以涵蓋 arguing/argument、
    tempted/tempting、celebrate/celebration 等變化形，所以不能用完整
    `\\bKEYWORD\\b` 字界（會漏掉這些變化形），但也不能用純子字串（曾經
    抓到 `sin` 誤判命中 `pulsing` 這個單字中間的問題，跟 importance.py 的
    "Eve"/"reveal" 是同一類 bug）。只要求左邊界即可同時避免子字串誤判、
    又保留詞幹前綴比對的彈性。中文關鍵字維持子字串比對（中文沒有字界
    概念，跟 importance.py 對中文名字的處理一致）。
    """
    if not text:
        return []
    text_lower = text.lower()
    matched = []
    for keyword in keywords:
        if keyword.isascii():
            if re.search(r"\b" + re.escape(keyword.lower()), text_lower) is not None:
                matched.append(keyword)
        elif keyword in text:
            matched.append(keyword)
    return matched


def classify_scene_theme(scene: dict) -> dict:
    """分析這個 scene 的敘事語意，回傳 `{"theme": 主導 theme 或 None,
    "scores": {theme_id: 命中關鍵字數}, "matched_keywords": [主導 theme
    命中的關鍵字]}`。

    比對範圍：`narration_zh`／`title`（中文關鍵字）與 `narration_en`／
    `animation_prompt`（英文關鍵字）。找不到符合任何 theme 的關鍵字時，
    `theme` 為 `None`，交由呼叫端套用 `DEFAULT_DECISION`。
    """
    narration_zh = scene.get("narration_zh", "") or ""
    narration_en = scene.get("narration_en", "") or ""
    animation_prompt = scene.get("animation_prompt", "") or ""
    title = scene.get("title", "") or ""

    combined_zh = f"{narration_zh} {title}"
    combined_en = f"{narration_en} {animation_prompt}"

    scores = {}
    matches = {}
    for theme_id, rule in THEMES.items():
        matched = _find_matches(combined_zh, rule["keywords_zh"]) + _find_matches(combined_en, rule["keywords_en"])
        if matched:
            scores[theme_id] = len(matched)
            matches[theme_id] = matched

    dominant_theme = next((theme_id for theme_id in THEME_PRIORITY if theme_id in scores), None)

    return {
        "theme": dominant_theme,
        "scores": scores,
        "matched_keywords": matches.get(dominant_theme, []),
    }


def decide_visual_plan(scene: dict) -> dict:
    """依 `classify_scene_theme` 的判斷結果，回傳這個 scene 的完整視覺決策：
    `lighting`／`composition`／`camera_shot`／`camera_angle`／`mood`（皆為
    preset id 或 camera id），以及 `theme`／`matched_keywords`／`theme_scores`
    供 prompt_report.txt 顯示決策依據。沒有命中任何 theme 時套用
    `DEFAULT_DECISION`（等同這個機制導入之前的固定 "default" 行為）。
    """
    classification = classify_scene_theme(scene)
    theme = classification["theme"]

    if theme:
        rule = THEMES[theme]
        plan = {key: rule[key] for key in ("lighting", "composition", "camera_shot", "camera_angle", "mood")}
    else:
        plan = dict(DEFAULT_DECISION)

    return {
        **plan,
        "theme": theme,
        "matched_keywords": classification["matched_keywords"],
        "theme_scores": classification["scores"],
    }


def resolve_visual_plan(scene: dict) -> dict:
    """決定一個 scene 最終採用的視覺決策，決定順序：

    1. scene 自己明確指定的欄位（`scene["lighting"]`／`["composition"]`／
       `["camera_angle"]`／`["mood"]`／`["camera"]`）——人工／StoryGenerator
       已經指定的值一律優先，Director 不覆蓋既有的明確設定。
    2. 都沒指定的欄位，改用 `decide_visual_plan()` 依語意自動決定。

    回傳值除了 5 個視覺欄位（`camera_shot` 對應 scene 的 `camera` 欄位）之外，
    還有 `sources`（`{field: "explicit"/"director"}`）供 prompt_report.txt
    揭露每個欄位是人工指定還是 Director 自動判斷、`theme`／`matched_keywords`／
    `theme_scores` 供分析判斷依據。
    """
    decision = decide_visual_plan(scene)
    resolved = dict(decision)
    sources = {field: "director" for field in OVERRIDABLE_FIELDS}
    sources["camera_shot"] = "director"

    for field in OVERRIDABLE_FIELDS:
        if scene.get(field):
            resolved[field] = scene[field]
            sources[field] = "explicit"

    if scene.get("camera"):
        resolved["camera_shot"] = scene["camera"]
        sources["camera_shot"] = "explicit"

    resolved["sources"] = sources
    return resolved
