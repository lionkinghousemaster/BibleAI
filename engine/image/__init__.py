"""Image Engine。

圖片生成邏輯（`ImageProvider`/`DummyProvider`/`ComfyUIProvider`/
`generate_image_from_prompt`/`build_character_aware_prompt`/
`generate_scene_image`，見 provider.py）本次 v0.9 Engine Migration Sprint
從專案根目錄的 `generate_image.py` 遷入。呼叫端只需要
`from engine.image import ComfyUIProvider, DummyProvider, generate_scene_image`
這樣的頂層 import，不需要知道內部檔案是怎麼拆的，維持與 `engine.prompt`
相同的對外介面風格。
"""

from .provider import (
    ComfyUIProvider,
    DummyProvider,
    ImageProvider,
    build_character_aware_prompt,
    generate_image_from_prompt,
    generate_scene_image,
)

__all__ = [
    "ImageProvider",
    "DummyProvider",
    "ComfyUIProvider",
    "generate_image_from_prompt",
    "build_character_aware_prompt",
    "generate_scene_image",
]
