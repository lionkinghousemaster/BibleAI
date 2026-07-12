import json
from pathlib import Path


class PromptLibrary:
    """所有可替換 Prompt 模板來源（Lighting／Composition／Style／Negative）的
    集中管理入口，取代舊的 JSONPromptProvider。

    除了讀取 `prompts/<category>/*.json` 的模板內容之外，也讀取
    `prompts/manifest.json` 裡登記的每個分類 metadata：
      - `weight`：這個分類在 Token Budget 分配時的相對權重
        （PromptOptimizer 用來決定預算不足時誰先被裁）
      - `default_preset`：scene 沒有指定該分類 preset id 時的預設值

    這樣「有哪些分類」「各自的權重」「預設用哪個 preset」都是資料
    （`prompts/manifest.json`），不是寫死在 PromptBuilder／PromptOptimizer
    程式碼裡的常數；PromptBuilder 因此不需要保存任何固定的 Prompt 字串
    或分類設定，只負責呼叫 PromptLibrary 組裝。

    Character（CharacterManager）、Environment（scene 自己的
    `image_prompt`）、Camera（CameraManager）都不在這個 library 的管理
    範圍內——它們各自有獨立的 Manager／欄位，這裡刻意不重複管理，
    也不影響 `stories/*.json` 既有格式。

    找不到 manifest、分類資料夾、或 preset 檔案時一律回傳空值／預設值，
    不丟例外，維持與 CharacterManager／CameraManager 一致的容錯風格。

    `prompts/` 資料夾本身仍放在專案根目錄（跟 `characters/`／`camera/`
    一樣是資料，不隨程式碼一起搬進 `engine/`），因此預設路徑往上推三層
    （engine/prompt/library.py -> engine/prompt -> engine -> 專案根目錄）
    才是 `prompts/`。
    """

    DEFAULT_MANIFEST = {
        "categories": {
            "lighting": {"weight": 3, "default_preset": "default"},
            "composition": {"weight": 2, "default_preset": "default"},
            "style": {"weight": 1, "default_preset": "default"},
            "negative": {"weight": 1, "default_preset": "default"},
        }
    }

    def __init__(self, prompts_dir: Path = None):
        self.prompts_dir = Path(prompts_dir) if prompts_dir else Path(__file__).parent.parent.parent / "prompts"
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        manifest_path = self.prompts_dir / "manifest.json"
        if not manifest_path.exists():
            return dict(self.DEFAULT_MANIFEST)
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return dict(self.DEFAULT_MANIFEST)

    def categories(self) -> list:
        """回傳 manifest 裡登記的所有分類名稱。"""
        return list(self._manifest.get("categories", {}).keys())

    def default_preset(self, category: str) -> str:
        return self._manifest.get("categories", {}).get(category, {}).get("default_preset", "default")

    def weight(self, category: str) -> int:
        return self._manifest.get("categories", {}).get(category, {}).get("weight", 1)

    def category_weights(self) -> dict:
        """回傳 {category: weight}，供 PromptOptimizer 的 Token Budget 分配使用。"""
        return {category: self.weight(category) for category in self.categories()}

    def load_all(self, category: str) -> dict:
        category_dir = self.prompts_dir / category
        prompts = {}
        if not category_dir.exists():
            return prompts

        for file_path in sorted(category_dir.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            prompt_id = data.get("id", file_path.stem)
            prompts[prompt_id] = data

        return prompts

    def get(self, category: str, prompt_id: str) -> dict | None:
        file_path = self.prompts_dir / category / f"{prompt_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_text(self, category: str, prompt_id: str = None) -> str:
        """回傳指定分類/preset 的 prompt 文字。

        `prompt_id` 省略（或為 None／空字串）時，改用該分類在
        `prompts/manifest.json` 登記的 `default_preset`。找不到分類、
        preset 檔案，或檔案沒有 `prompt` 欄位，一律回傳空字串，不丟例外。
        """
        resolved_id = prompt_id or self.default_preset(category)
        if not resolved_id:
            return ""
        data = self.get(category, resolved_id)
        if not data:
            return ""
        return data.get("prompt", "")

    def resolve_preset_id(self, category: str, prompt_id: str = None) -> str:
        """回傳實際會被使用的 preset id（scene 指定的，或 manifest 的預設值），
        供 PromptReport 顯示「這個模組實際用了哪個來源」。
        """
        return prompt_id or self.default_preset(category)
