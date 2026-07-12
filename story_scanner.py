import json
from pathlib import Path


class StoryScanner:
    """掃描 stories/ 資料夾，找出所有故事 JSON 檔案並解析基本 metadata。

    設計目標：新增一部作品只需要在 stories/ 底下多丟一個 JSON 檔案，
    不需要改任何程式碼——Batch Pipeline 會自動掃到它、自動處理。

    無法解析的 JSON、或缺少有效 scenes 的檔案會被跳過並印出警告，不會讓
    整批掃描中斷（一個壞檔案不該讓其他正常故事也掃不到）。
    """

    def __init__(self, stories_dir: Path = None):
        self.stories_dir = Path(stories_dir) if stories_dir else Path(__file__).parent / "stories"

    def scan(self) -> list:
        """回傳所有可解析故事的 metadata 列表（依檔名排序）。"""
        stories = []
        if not self.stories_dir.exists():
            return stories

        for file_path in sorted(self.stories_dir.glob("*.json")):
            entry = self._load_entry(file_path)
            if entry:
                stories.append(entry)

        return stories

    def get(self, story_id: str) -> dict | None:
        file_path = self.stories_dir / f"{story_id}.json"
        if not file_path.exists():
            return None
        return self._load_entry(file_path)

    def _load_entry(self, file_path: Path) -> dict | None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[StoryScanner] 略過無法解析的檔案：{file_path.name}（{e}）")
            return None

        scenes = data.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            print(f"[StoryScanner] 略過沒有有效 scenes 的檔案：{file_path.name}")
            return None

        story_id = file_path.stem
        return {
            "story_id": story_id,
            "path": file_path,
            "episode": data.get("episode", ""),
            "book": data.get("book", ""),
            "chapter": data.get("chapter", ""),
            "title_zh": data.get("title_zh", ""),
            "title_en": data.get("title_en", ""),
            "duration": data.get("duration", ""),
            "scene_count": len(scenes),
            "data": data,
        }
