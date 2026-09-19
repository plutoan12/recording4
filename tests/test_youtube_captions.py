"""자막 트랙 업로드. 계정도 네트워크도 쓰지 않고 어댑터 규약만 봅니다.

영상에 구운 자막과 같은 내용을 시청자가 켜고 끌 수 있는 트랙으로 올립니다.
여기서 확인하는 것은 두 가지입니다. 같은 언어 트랙을 두 벌 만들지 않는 것과,
자막을 올리지 못해도 게시를 실패로 만들지 않는 것입니다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from worker.youtube import upload_captions


class Captions:
    """captions.list/insert만 흉내 내는 대역. 올린 요청을 그대로 모읍니다."""

    def __init__(self, existing: list[dict] | None = None) -> None:
        self.existing = existing or []
        self.inserted: list[dict] = []

    def list(self, **kwargs):  # noqa: A003 - YouTube API 이름을 그대로 씁니다.
        self.listed = kwargs
        return SimpleNamespace(execute=lambda: {"items": self.existing})

    def insert(self, **kwargs):
        self.inserted.append(kwargs)
        return SimpleNamespace(execute=lambda: {"id": "caption-1"})


def service_with(captions: Captions):
    return SimpleNamespace(captions=lambda: captions)


def test_upload_needs_explicit_switch_and_language(tmp_path):
    path = tmp_path / "captions.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\n자막\n\n", encoding="utf-8")
    captions = Captions()
    with pytest.raises(ValueError):
        upload_captions(service_with(captions), "video", path=path, language="ko")
    with pytest.raises(ValueError):
        upload_captions(service_with(captions), "video", path=path, language="", allow_upload=True)
    assert captions.inserted == []


def test_existing_track_in_the_same_language_is_not_replaced(tmp_path):
    """사람이 올린 트랙을 덮어쓰지 않고, 다시 실행해도 트랙이 늘지 않습니다."""
    path = tmp_path / "captions.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\n자막\n\n", encoding="utf-8")
    captions = Captions([{"id": "already", "snippet": {"language": "ko", "name": "손으로 올림"}}])
    caption_id, outcome = upload_captions(
        service_with(captions), "video", path=path, language="ko", allow_upload=True
    )
    assert (caption_id, outcome) == ("already", "exists")
    assert captions.inserted == []


def test_upload_sends_our_timings_and_the_requested_language(tmp_path):
    pytest.importorskip(
        "googleapiclient", reason="providers extra가 있어야 업로드 본문을 만듭니다."
    )
    path = tmp_path / "captions.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\n자막\n\n", encoding="utf-8")
    captions = Captions([{"id": "other", "snippet": {"language": "en"}}])
    caption_id, outcome = upload_captions(
        service_with(captions), "video", path=path, language="ko", allow_upload=True
    )
    assert (caption_id, outcome) == ("caption-1", "uploaded")
    sent = captions.inserted[0]
    assert sent["body"]["snippet"] == {"videoId": "video", "language": "ko", "name": ""}
    # sync를 켜면 YouTube가 타이밍을 다시 잡아 구워진 자막과 어긋납니다.
    assert sent["sync"] is False
