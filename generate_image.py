import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from character_manager import CharacterManager
from prompt_builder import PromptBuilder


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, output_path: str, negative_prompt: str = "") -> None:
        ...


class DummyProvider(ImageProvider):
    """假圖片生成器：把 prompt 寫入 output_path 同名的 .txt 檔案，代表圖片生成成功。"""

    def generate(self, prompt: str, output_path: str, negative_prompt: str = "") -> None:
        txt_path = Path(output_path).with_suffix(".txt")
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
            if negative_prompt:
                f.write(f"\n---NEGATIVE---\n{negative_prompt}")


class ComfyUIProvider(ImageProvider):
    """透過本地 ComfyUI 的 HTTP API 生成圖片。

    使用前必須完成：
    1. 安裝並啟動 ComfyUI（預設監聽 http://127.0.0.1:8188）
    2. 在 ComfyUI 介面中組好 txt2img workflow（例如載入 FLUX.1-schnell），
       用選單「Save (API Format)」匯出成 JSON，放到 workflow_path
    3. 打開匯出的 JSON，找出正向 prompt 節點（CLIPTextEncode）與
       輸出節點（SaveImage）的節點編號，分別填入 positive_prompt_node_id
       與 save_image_node_id。若 workflow 裡也有負向 prompt 節點，可另外
       填入 negative_prompt_node_id 讓負向提示詞生效；不填的話行為與過去
       完全一樣，只會設定正向 prompt。

    只依賴 Python 標準庫（urllib），不需要安裝任何第三方套件。
    """

    def __init__(
        self,
        workflow_path: str,
        positive_prompt_node_id: str,
        save_image_node_id: str,
        server_url: str = "http://127.0.0.1:8188",
        seed_node_id: str = None,
        negative_prompt_node_id: str = None,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ):
        self.workflow_path = Path(workflow_path)
        self.positive_prompt_node_id = positive_prompt_node_id
        self.save_image_node_id = save_image_node_id
        self.server_url = server_url.rstrip("/")
        self.seed_node_id = seed_node_id
        self.negative_prompt_node_id = negative_prompt_node_id
        self.poll_interval = poll_interval
        self.timeout = timeout

    def _build_workflow(self, prompt: str, negative_prompt: str = "") -> dict:
        if not self.workflow_path.exists():
            raise FileNotFoundError(
                f"找不到 workflow 檔案：{self.workflow_path}\n"
                "請先在 ComfyUI 組好 txt2img workflow，並用「Save (API Format)」匯出成 JSON。"
            )
        with open(self.workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        workflow[self.positive_prompt_node_id]["inputs"]["text"] = prompt

        if self.negative_prompt_node_id and negative_prompt:
            workflow[self.negative_prompt_node_id]["inputs"]["text"] = negative_prompt

        if self.seed_node_id:
            workflow[self.seed_node_id]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

        return workflow

    def _queue_prompt(self, workflow: dict, client_id: str) -> str:
        payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.server_url}/prompt",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                result = json.loads(response.read())
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"無法連線到 ComfyUI（{self.server_url}），請確認 ComfyUI 是否已啟動。原始錯誤：{e}"
            ) from e
        return result["prompt_id"]

    def _wait_for_result(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            with urllib.request.urlopen(f"{self.server_url}/history/{prompt_id}") as response:
                history = json.loads(response.read())
            if prompt_id in history:
                return history[prompt_id]
            time.sleep(self.poll_interval)
        raise TimeoutError(f"ComfyUI 在 {self.timeout} 秒內沒有完成生成（prompt_id={prompt_id}）")

    def _download_image(self, image_info: dict, output_path: Path) -> None:
        query = urllib.parse.urlencode(
            {
                "filename": image_info["filename"],
                "subfolder": image_info.get("subfolder", ""),
                "type": image_info.get("type", "output"),
            }
        )
        with urllib.request.urlopen(f"{self.server_url}/view?{query}") as response:
            data = response.read()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(data)

    def generate(self, prompt: str, output_path: str, negative_prompt: str = "") -> None:
        workflow = self._build_workflow(prompt, negative_prompt)
        client_id = str(uuid.uuid4())
        prompt_id = self._queue_prompt(workflow, client_id)
        result = self._wait_for_result(prompt_id)

        images = result.get("outputs", {}).get(self.save_image_node_id, {}).get("images", [])
        if not images:
            raise RuntimeError(f"ComfyUI 沒有回傳任何圖片（prompt_id={prompt_id}）")

        self._download_image(images[0], Path(output_path))


DEFAULT_PROVIDER = DummyProvider()


def generate_image_from_prompt(
    prompt: str,
    output_path: str,
    provider: ImageProvider = None,
    negative_prompt: str = "",
) -> None:
    active_provider = provider or DEFAULT_PROVIDER
    try:
        active_provider.generate(prompt, output_path, negative_prompt=negative_prompt)
    except TypeError:
        # 向下相容：Provider 若是舊介面（generate 只接受 prompt/output_path，
        # 不支援 negative_prompt 關鍵字參數），退回不帶負向 prompt 的呼叫方式。
        active_provider.generate(prompt, output_path)


def build_character_aware_prompt(
    base_prompt: str,
    character_ids: list,
    manager: CharacterManager = None,
) -> str:
    """（v0.2 起既有介面，簽章維持向下相容）組出 scene 的最終正向 prompt。

    Sprint 4 起改為內部委由 PromptBuilder 組合，除了原本的 environment
    （base_prompt）+ character 之外，也會疊上 lighting / composition / style
    三層模板（找不到對應模板時該層自動變空字串並被跳過，不影響其餘內容）。
    因此輸出比 v0.2/v0.3 時期更完整，但 base_prompt／character_ids 的
    對應關係與呼叫方式不變，main.py 既有呼叫端不需要修改。
    """
    builder = PromptBuilder(character_manager=manager or CharacterManager())
    scene = {"image_prompt": base_prompt, "characters": character_ids}
    return builder.build_positive_prompt(scene)


def generate_scene_image(
    scene: dict,
    output_path: str,
    provider: ImageProvider = None,
    prompt_builder: PromptBuilder = None,
) -> None:
    """Sprint 4 新入口：用 PromptBuilder 組出完整分層正向／負向 prompt 後交給 ImageProvider。

    與 build_character_aware_prompt 的差異：這個函式會一併組出並送出負向
    prompt（PromptBuilder.build_negative_prompt），讓 ComfyUI workflow 裡的
    負向 CLIPTextEncode 節點（若有設定 negative_prompt_node_id）真正生效。
    """
    builder = prompt_builder or PromptBuilder()
    positive_prompt = builder.build_positive_prompt(scene)
    negative_prompt = builder.build_negative_prompt(scene)
    generate_image_from_prompt(positive_prompt, output_path, provider=provider, negative_prompt=negative_prompt)
