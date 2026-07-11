# workflows/

存放從 ComfyUI 匯出的 API Format workflow JSON。

## 下一步安裝完 ComfyUI 後要做的事

1. 在 ComfyUI 介面組好 txt2img workflow（載入 FLUX.1-schnell）
2. 選單「Save (API Format)」匯出成 JSON，存到這個資料夾，例如：
   `workflows/flux_schnell_basic.json`
3. 打開這個 JSON，找出：
   - 正向 prompt 節點（`CLIPTextEncode`）的節點編號
   - 輸出節點（`SaveImage`）的節點編號
   - （選用）seed 節點編號，如果想每次生成都換一個隨機種子
4. 用這三個編號建立 `ComfyUIProvider`（見 `generate_image.py`），例如：

```python
from generate_image import ComfyUIProvider, generate_image_from_prompt

provider = ComfyUIProvider(
    workflow_path="workflows/flux_schnell_basic.json",
    positive_prompt_node_id="6",   # 依實際匯出的 JSON 調整
    save_image_node_id="9",        # 依實際匯出的 JSON 調整
)

generate_image_from_prompt("a friendly lion in a sunny meadow", "output/images/test.png", provider=provider)
```

節點編號會因為 workflow 組法不同而不一樣，一定要打開匯出的 JSON 實際確認。
