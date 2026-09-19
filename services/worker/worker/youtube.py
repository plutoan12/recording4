"""YouTube resumable upload adapter with explicit durable checkpoints.

Caller provides an authenticated google-api-python-client service and a checkpoint
persisted to the publication row. This adapter never approves an artifact itself.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path


class UploadNeedsReview(RuntimeError):
    pass


def upload_approved(
    service,
    path: Path,
    *,
    approval_id: str,
    title: str,
    description: str,
    checkpoint: dict,
    save: Callable[[dict], None],
    made_for_kids: bool,
    allow_upload: bool = False,
) -> str:
    if not allow_upload or not approval_id:
        raise ValueError("승인된 결과물과 명시적인 업로드 실행 설정이 필요합니다.")
    if checkpoint.get("approval_id") not in (None, approval_id):
        raise UploadNeedsReview("기존 업로드와 승인 버전이 다릅니다.")
    if checkpoint.get("video_id"):
        return checkpoint["video_id"]
    # Session creation may succeed remotely before its URI is saved. Do not create
    # a second video when that window is unresolved.
    if checkpoint.get("started") and not checkpoint.get("session_uri"):
        raise UploadNeedsReview("업로드 결과가 불명확합니다. 채널을 확인한 후 수동 복구하세요.")
    from googleapiclient.http import MediaFileUpload

    request = service.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": made_for_kids},
        },
        media_body=MediaFileUpload(
            str(path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True
        ),
    )
    state = {**checkpoint, "approval_id": approval_id, "started": True}
    save(dict(state))
    if state.get("session_uri"):
        request.resumable_uri = state["session_uri"]
        # The SDK queries server progress before resuming; never assume saved offset.
        request._in_error_state = True
    response = None
    while response is None:
        try:
            _, response = request.next_chunk(num_retries=0)
        finally:
            if request.resumable_uri:
                state["session_uri"] = request.resumable_uri
                save(dict(state))
        if response is not None:
            state["video_id"] = response["id"]
            save(dict(state))
    return state["video_id"]


def schedule_video(service, video_id: str, publish_at: datetime, *, made_for_kids: bool):
    if publish_at.tzinfo is None or publish_at <= datetime.now(UTC):
        raise ValueError("예약 시각은 시간대가 포함된 미래 시각이어야 합니다.")
    result = service.videos().list(part="status,processingDetails", id=video_id).execute()
    items = result.get("items", [])
    if not items or items[0].get("processingDetails", {}).get("processingStatus") != "succeeded":
        raise UploadNeedsReview("YouTube 처리가 완료된 뒤 예약하세요.")
    if items[0].get("status", {}).get("privacyStatus") != "private":
        raise UploadNeedsReview("비공개 영상만 예약할 수 있습니다.")
    return (
        service.videos()
        .update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": publish_at.astimezone(UTC).isoformat(),
                    "selfDeclaredMadeForKids": made_for_kids,
                },
            },
        )
        .execute()
    )


def upload_captions(
    service,
    video_id: str,
    *,
    path: Path,
    language: str,
    name: str = "",
    allow_upload: bool = False,
) -> tuple[str | None, str]:
    """자막 트랙을 올리고 (트랙 ID, 결과)를 돌려줍니다. 영상은 건드리지 않습니다.

    같은 언어 트랙이 이미 있으면 올리지 않습니다. 사람이 손으로 올린 트랙을
    덮어쓰거나 같은 언어를 두 벌 만들지 않기 위해서입니다. 이미 우리가 올린
    경우에도 같은 판정으로 걸러지므로 다시 실행해도 트랙이 늘지 않습니다.

    `sync=False`로 우리가 만든 시각을 그대로 씁니다. 켜면 YouTube가 음성에 맞춰
    타이밍을 다시 잡는데, 그러면 영상에 구워진 자막과 어긋납니다.
    """
    if not allow_upload:
        raise ValueError("자막 트랙 업로드 실행 설정이 필요합니다.")
    if not language:
        raise ValueError("자막 트랙에는 언어가 필요합니다.")
    existing = service.captions().list(part="snippet", videoId=video_id).execute()
    for item in existing.get("items", []):
        snippet = item.get("snippet", {})
        if snippet.get("language") == language:
            return item.get("id"), "exists"
    from googleapiclient.http import MediaFileUpload

    response = (
        service.captions()
        .insert(
            part="snippet",
            sync=False,
            body={"snippet": {"videoId": video_id, "language": language, "name": name}},
            media_body=MediaFileUpload(str(path), mimetype="application/octet-stream"),
        )
        .execute()
    )
    return response.get("id"), "uploaded"
