import json
from abc import ABC, abstractmethod
from pathlib import Path


class CharacterProvider(ABC):
    @abstractmethod
    def load_all(self) -> dict:
        ...

    @abstractmethod
    def get(self, character_id: str) -> dict | None:
        ...


class JSONCharacterProvider(CharacterProvider):
    """從 characters/ 資料夾讀取角色設定 JSON 檔案（一個角色一個檔案，檔名即 character_id）。"""

    def __init__(self, characters_dir: Path = None):
        self.characters_dir = Path(characters_dir) if characters_dir else Path(__file__).parent / "characters"

    def load_all(self) -> dict:
        characters = {}
        if not self.characters_dir.exists():
            return characters

        for file_path in sorted(self.characters_dir.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            character_id = data.get("id", file_path.stem)
            characters[character_id] = data

        return characters

    def get(self, character_id: str) -> dict | None:
        file_path = self.characters_dir / f"{character_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)


class CharacterManager:
    """角色資料的存取入口，包裝 CharacterProvider。

    目前是獨立模組，尚未被 generate_image.py / main.py 引用，不影響任何既有 pipeline。
    """

    def __init__(self, provider: CharacterProvider = None):
        self.provider = provider or JSONCharacterProvider()

    def get_character(self, character_id: str) -> dict | None:
        return self.provider.get(character_id)

    def list_characters(self) -> dict:
        return self.provider.load_all()

    def get_visual_prompt(self, character_id: str) -> str:
        """回傳角色的視覺描述片段，未來給 generate_image.py 組 image_prompt 時引用，維持角色一致性。"""
        character = self.get_character(character_id)
        if not character:
            return ""
        return character.get("visual_prompt", "")
