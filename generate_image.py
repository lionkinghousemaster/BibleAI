import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, output_path: str) -> None:
        ...


class DummyProvider(ImageProvider):
    """假圖片生成器：把 prompt 寫入 output_path 同名的 .txt 檔案，代表圖片生成成功。"""

    def generate(self, prompt: str, output_path: str) -> None:
        txt_path = Path(output_path).with_suffix(".txt")
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(prompt)


class ComfyUIProvider(ImageProvider):
    """透過本地 ComfyUI 的 HTTP API 生成圖片。

    使用前必須完成：
    1. 安裝並啟動 ComfyUI（預設監聽 http://127.0.0.1:8188）
    2. 在 ComfyUI 介面中組好 txt2img workflow（例如載入 FLUX.1-schnell），
       用選單「Save (API Format)」匯出成 JSON，放到 workflow_path
    3. 打開匯出的 JSON，找出正向 prompt 節點（CLIPTextEncode）與
       輸出節點（SaveImage）的節點編號，分別填入 positive_prompt_node_id
       與 save_image_node_id

    只依賴 Python 標準庫（urllib），不需要安裝任何第三方套件。
    """

    def __init__(
        self,
        workflow_path: str,
        positive_prompt_node_id: str,
        save_image_node_id: str,
        server_url: str = "http://127.0.0.1:8188",
        seed_node_id: str = None,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ):
        self.workflow_path = Path(workflow_path)
        self.positive_prompt_node_id = positive_prompt_node_id
        self.save_image_node_id = save_image_node_id
        self.server_url = server_url.rstrip("/")
        self.seed_node_id = seed_node_id
        self.poll_interval = poll_interval
        self.timeout = timeout

    def _build_workflow(self, prompt: str) -> dict:
        if not self.workflow_path.exists():
            raise FileNotFoundError(
                f"找不到 workflow 檔案：{self.workflow_path}\n"
                "請先在 ComfyUI 組好 txt2img workflow，並用「Save (API Format)」匯出成 JSON。"
            )
        with open(self.workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        workflow[self.positive_prompt_node_id]["inputs"]["text"] = prompt

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

    def generate(self, prompt: str, output_path: str) -> None:
        workflow = self._build_workflow(prompt)
        client_id = str(uuid.uuid4())
        prompt_id = self._queue_prompt(workflow, client_id)
        result = self._wait_for_result(prompt_id)

        images = result.get("outputs", {}).get(self.save_image_node_id, {}).get("images", [])
        if not images:
            raise RuntimeError(f"ComfyUI 沒有回傳任何圖片（prompt_id={prompt_id}）")

        self._download_image(images[0], Path(output_path))


DEFAULT_PROVIDER = DummyProvider()


def generate_image_from_prompt(prompt: str, output_path: str, provider: ImageProvider = None) -> None:
    (provider or DEFAULT_PROVIDER).generate(prompt, output_path)
