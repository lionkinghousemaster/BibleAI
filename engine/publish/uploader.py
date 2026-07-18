import datetime
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class UploadProvider(ABC):
    @abstractmethod
    def upload(self, video_path, upload_payload: dict, thumbnail_path=None) -> dict:
        ...


class DummyUploadProvider(UploadProvider):
    """假上傳器：不會真的呼叫任何網路 API，只回傳一組可辨識的假 video_id
    （`DUMMY_` 開頭）與目前時間當作 published_at，用來在沒有設定 Google
    OAuth 憑證時，也能驗證「upload.json → 呼叫上傳 → 欄位回填」這條路徑
    是否正確，不會真的把任何內容送到 YouTube。
    """

    def upload(self, video_path, upload_payload: dict, thumbnail_path=None) -> dict:
        return {
            "upload_status": "dummy_uploaded",
            "video_id": f"DUMMY_{uuid.uuid4().hex[:11]}",
            "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        }


class YouTubeUploadProvider(UploadProvider):
    """透過 YouTube Data API v3（`videos.insert` + `thumbnails.set`）真正把
    整集影片上傳到 YouTube，並把封面圖設成縮圖。

    使用前必須完成：
    1. 在 Google Cloud Console 建立一個專案，啟用「YouTube Data API v3」。
    2. 建立 OAuth 2.0 用戶端 ID（應用程式類型選「桌面應用程式」），下載
       憑證 JSON，放到 client_secrets_path（預設 `youtube_client_secrets.json`）。
    3. 第一次執行 upload() 時，會跳出瀏覽器要求登入並同意授權（背後在本機
       開一個暫時的 local server 接收 OAuth 回呼），取得的憑證（含 refresh
       token）會存到 token_path（預設 `youtube_token.json`），之後執行會自動
       用 refresh token 續期，不需要再次互動登入。

    只依賴 google-api-python-client／google-auth-oauthlib／
    google-auth-httplib2（需要另外 `pip install`；本專案沒有維護
    requirements.txt，跟 generate_voice.py 的 edge-tts 做法一致，只在真正
    用到時才 import）。

    upload_payload 需要有 `snippet`（title/description/tags/categoryId/
    defaultLanguage）與 `status`（privacyStatus/selfDeclaredMadeForKids）
    兩個欄位——這正是 `content_metadata.build_upload_payload()` 產生的
    `upload.json` 結構，不需要額外轉換。
    """

    def __init__(
        self,
        client_secrets_path: str = "youtube_client_secrets.json",
        token_path: str = "youtube_token.json",
    ):
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)

    def _get_credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        credentials = None
        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                if not self.client_secrets_path.exists():
                    raise FileNotFoundError(
                        f"找不到 YouTube OAuth 用戶端設定檔：{self.client_secrets_path}\n"
                        "請先在 Google Cloud Console 建立 OAuth 2.0 用戶端（應用程式類型："
                        "桌面應用程式），下載 client_secrets.json 放到這個路徑，並確認該專案"
                        "已啟用 YouTube Data API v3。"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_path), SCOPES)
                credentials = flow.run_local_server(port=0)

            self.token_path.write_text(credentials.to_json(), encoding="utf-8")

        return credentials

    def upload(self, video_path, upload_payload: dict, thumbnail_path=None) -> dict:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        credentials = self._get_credentials()
        youtube = build("youtube", "v3", credentials=credentials)

        body = {
            "snippet": upload_payload["snippet"],
            "status": upload_payload["status"],
        }
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=-1)

        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _status, response = request.next_chunk()

        video_id = response["id"]
        published_at = response.get("snippet", {}).get("publishedAt") or datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()

        if thumbnail_path and Path(thumbnail_path).exists():
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))).execute()

        return {
            "upload_status": "uploaded",
            "video_id": video_id,
            "published_at": published_at,
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        }
