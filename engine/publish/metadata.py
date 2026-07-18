from engine.prompt import PromptBuilder


def build_cover_scene(story_data: dict) -> dict:
    """從整部作品挑出具代表性的角色與畫面，組成一個「虛擬 scene」給
    PromptBuilder 用來產生封面 prompt。

    環境描述取第一個 scene 的 image_prompt 當作主視覺基礎（通常是整部作品
    的開場畫面），角色則彙整「所有出現過的角色」（去重、保留出現順序），
    構圖固定用 wide_shot，讓封面呈現較宏觀、適合當縮圖的畫面。
    """
    scenes = story_data.get("scenes", [])
    if not scenes:
        return {"image_prompt": "", "characters": [], "composition": "wide_shot"}

    all_characters = []
    for scene in scenes:
        for character_id in scene.get("characters", []):
            if character_id not in all_characters:
                all_characters.append(character_id)

    return {
        "image_prompt": scenes[0].get("image_prompt", ""),
        "characters": all_characters,
        "composition": "wide_shot",
    }


def generate_cover_prompt(story_data: dict, prompt_builder: PromptBuilder = None) -> str:
    builder = prompt_builder or PromptBuilder()
    cover_scene = build_cover_scene(story_data)
    return builder.build_positive_prompt(cover_scene)


def generate_youtube_metadata(story_data: dict) -> dict:
    """依故事內容自動組出 YouTube 上架用的 Title / Description / Tags 草稿。

    是給人工上架前參考用的草稿（draft），不是最終定稿——標題／描述的
    文案品質仍建議人工檢查一次再發佈。
    """
    title_zh = story_data.get("title_zh", "")
    title_en = story_data.get("title_en", "")
    book = story_data.get("book", "")
    episode = story_data.get("episode", "")
    scenes = story_data.get("scenes", [])

    if title_zh and title_en:
        title = f"{title_zh} | {title_en}"
    else:
        title = title_zh or title_en

    narrations_en = [scene.get("narration_en", "") for scene in scenes if scene.get("narration_en")]
    summary = " ".join(narrations_en)
    if len(summary) > 400:
        summary = summary[:400].rsplit(" ", 1)[0] + "..."

    description_lines = [
        title,
        "",
        summary,
        "",
        f"{book} — {episode}".strip(" —"),
        "",
        "A BibleAI original animated Bible story for kids.",
    ]
    description = "\n".join(line for line in description_lines if line is not None)

    tags = []
    for tag_source in (book, episode, "Bible stories for kids", "Bible for children", "animated Bible story"):
        if tag_source and tag_source not in tags:
            tags.append(tag_source)

    for scene in scenes:
        for character_id in scene.get("characters", []):
            if character_id not in tags:
                tags.append(character_id)

    return {
        "title": title,
        "description": description,
        "tags": tags,
    }


def build_upload_payload(story_id: str, youtube_metadata: dict) -> dict:
    """組出上傳到 YouTube 時要用的欄位（snippet/status），並預留
    upload_status／video_id／published_at／thumbnail_path 給
    `engine.publish.pipeline` 的 `upload_video()` 呼叫 UploadProvider
    後回填。
    """
    return {
        "story_id": story_id,
        "snippet": {
            "title": youtube_metadata["title"],
            "description": youtube_metadata["description"],
            "tags": youtube_metadata["tags"],
            "categoryId": "27",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": True,
        },
        "upload_status": "not_uploaded",
        "video_id": None,
        "published_at": None,
        "thumbnail_path": None,
    }
