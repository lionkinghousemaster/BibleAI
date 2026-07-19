import re

SIGNAL_WEIGHTS = {
    "is_main": 0.4,
    "is_plot_core": 0.3,
    "has_action": 0.2,
    "has_dialogue": 0.1,
}

LEGACY_TIER_SCORES = {"main": 1.0, "secondary": 0.5, "background": 0.2}

_ZH_QUOTE_PATTERN = re.compile(r"[^，。！？；：\n]{0,8}(?=「)")
_EN_QUOTE_PATTERN = re.compile(r".{0,8}(?=[\"“])")


def _mentions_name(text: str, name: str) -> bool:
    """判斷 `name` 是否出現在 `text` 裡。英文名字用 `\\b` 字界比對（避免
    "Eve" 誤判命中 "reveal"／"even" 這類短名字剛好是其他單字子字串的
    情況）；中文名字维持子字串比對（中文沒有空白斷詞，且角色名字通常
    是專有詞彙，子字串誤判機率低很多）。
    """
    if not text or not name:
        return False
    if name.isascii():
        return re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE) is not None
    return name in text


def _has_dialogue_signal(name: str, narration: str) -> bool:
    """粗略偵測「這個角色在這段旁白裡有沒有被安排說話」：檢查角色名字是否
    緊接在一個引號（中文「...」或英文雙引號）前面幾個字之內，模擬「XX
    說：『...』」這種常見句型。這是啟發式判斷，不是真正的語意理解——
    找不到符合的位置一律回傳 False，不影響其餘信號的計算，也不會丟例外。
    """
    if not name or not narration:
        return False
    if "「" in narration:
        for match in _ZH_QUOTE_PATTERN.finditer(narration):
            if name in match.group(0):
                return True
    if '"' in narration or "“" in narration:
        for match in _EN_QUOTE_PATTERN.finditer(narration):
            if name.lower() in match.group(0).lower():
                return True
    return False


def compute_character_signals(character_id: str, character_data: dict, scene: dict) -> dict:
    """算出一個角色在這個 scene 裡的四個原始信號（皆為布林值）：

    - `is_main`：是否為 `scene["characters"]` 裡第一個角色。
    - `is_plot_core`：角色名字（`name_zh` 或 `name_en`）是否出現在
      `narration_zh`／`narration_en` 裡——有被旁白直接提到，通常代表這個
      角色是這段情節真正的主體，不只是畫面裡的背景存在。
    - `has_action`：角色名字是否出現在 `animation_prompt` 裡——代表這個
      角色在畫面裡有明確的動作／鏡頭語言描述。
    - `has_dialogue`：角色名字是否緊接在旁白引號之前，粗略代表「這個
      角色在這段旁白裡有台詞」（見 `_has_dialogue_signal`）。

    `character_data` 找不到（傳入 `None` 或空 dict）時，所有信號一律回傳
    `False`，不丟例外——跟 CharacterManager／CameraManager 一致的容錯風格。
    """
    character_data = character_data or {}
    name_zh = character_data.get("name_zh", "")
    name_en = character_data.get("name_en", "")

    characters_in_scene = scene.get("characters", []) or []
    narration_zh = scene.get("narration_zh", "") or ""
    narration_en = scene.get("narration_en", "") or ""
    animation_prompt = scene.get("animation_prompt", "") or ""

    is_main = bool(characters_in_scene) and characters_in_scene[0] == character_id
    is_plot_core = _mentions_name(narration_zh, name_zh) or _mentions_name(narration_en, name_en)
    has_action = _mentions_name(animation_prompt, name_zh) or _mentions_name(animation_prompt, name_en)
    has_dialogue = _has_dialogue_signal(name_zh, narration_zh) or _has_dialogue_signal(name_en, narration_en)

    return {
        "is_main": is_main,
        "is_plot_core": is_plot_core,
        "has_action": has_action,
        "has_dialogue": has_dialogue,
    }


def score_from_signals(signals: dict) -> float:
    """把四個布林信號依 `SIGNAL_WEIGHTS`（is_main 0.4、is_plot_core 0.3、
    has_action 0.2、has_dialogue 0.1）加總成 0.0～1.0 的 importance_score，
    四項信號全中封頂 1.0。
    """
    score = sum(weight for key, weight in SIGNAL_WEIGHTS.items() if signals.get(key))
    return round(min(score, 1.0), 2)


def compute_importance(character_id: str, character_data: dict, scene: dict) -> dict:
    """回傳這個角色在這個 scene 裡完整的重要性評分資料：四個原始信號、
    是否為單角色 scene（`solo`），以及最終的 `importance_score`。

    單角色 scene 時 `importance_score` 一律視為 1.0：畫面裡只有一個角色
    時，這個角色本身就是無庸置疑的主角，不需要再靠其他三個信號才能
    判斷，也讓既有的單角色 scene（多數 `stories/*.json` 的情況）維持
    「角色完整保護、不裁剪」的行為，不因為導入這個機制而改變。
    """
    characters_in_scene = scene.get("characters", []) or []
    solo = len(characters_in_scene) <= 1

    signals = compute_character_signals(character_id, character_data, scene)
    score = 1.0 if solo else score_from_signals(signals)

    return {**signals, "solo": solo, "importance_score": score}


def resolve_character_importance(character_id: str, character_data: dict, scene: dict) -> dict:
    """決定一個角色在這個 scene 裡最終採用的 importance_score，決定順序：

    1. `scene["character_importance"][character_id]`——明確的數值覆寫
       （0.0～1.0），例如 StoryGenerator 生成故事時直接算好寫進去，或人工
       手動調整。非數值（型別錯誤）的覆寫會被忽略，退回下一個順位，
       不丟例外。
    2. `scene["character_priority"][character_id]`——v0.9 Token Allocation
       Sprint 留下的舊版三段式 tier（`main`/`secondary`/`background`），
       映射成對應分數，向下相容既有 story JSON，不強迫遷移舊資料。
    3. 都沒有的話，呼叫 `compute_importance()` 現場計算。

    回傳值一律包含完整的信號拆解與最終 `importance_score`、`solo`，以及
    `source`（`explicit`/`legacy_priority`/`heuristic`），供
    prompt_report.txt 完整揭露決策依據，方便分析「這個角色的描述長度
    為什麼是這樣」。
    """
    computed = compute_importance(character_id, character_data, scene)

    explicit_scores = scene.get("character_importance", {}) or {}
    if character_id in explicit_scores:
        raw_score = explicit_scores[character_id]
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
            score = round(max(0.0, min(float(raw_score), 1.0)), 2)
            return {**computed, "importance_score": score, "source": "explicit"}

    legacy_tiers = scene.get("character_priority", {}) or {}
    if character_id in legacy_tiers and legacy_tiers[character_id] in LEGACY_TIER_SCORES:
        score = LEGACY_TIER_SCORES[legacy_tiers[character_id]]
        return {**computed, "importance_score": score, "source": "legacy_priority"}

    return {**computed, "source": "heuristic"}
