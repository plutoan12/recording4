"""워커. ffprobe 해석, 검사 태스크, outbox 디스패처."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from adminapi.models import OutboxMessage, SourceAsset
from adminapi.outbox import enqueue
from worker.dispatcher import dispatch_pending
from worker.media import ProbeError, parse_probe_output


def probe_json(duration: str = "12.500", width: int = 1920, height: int = 1080, audio: bool = True):  # noqa: ANN201
    streams = [{"codec_type": "video", "width": width, "height": height}]
    if audio:
        streams.append({"codec_type": "audio"})
    return json.dumps(
        {"format": {"duration": duration, "format_name": "mov,mp4"}, "streams": streams}
    )


def test_probe_output_is_parsed() -> None:
    info = parse_probe_output(probe_json())
    assert info.duration_seconds == 12.5
    assert (info.width, info.height) == (1920, 1080)
    assert info.has_audio


def test_probe_without_audio_track_is_reported() -> None:
    """트랙 존재만 기록합니다. 발화 여부는 이 검사로 판정하지 않습니다."""
    assert parse_probe_output(probe_json(audio=False)).has_audio is False


def test_probe_rejects_broken_output() -> None:
    with pytest.raises(ProbeError):
        parse_probe_output("not json")


def test_probe_rejects_missing_duration() -> None:
    with pytest.raises(ProbeError):
        parse_probe_output(json.dumps({"format": {}, "streams": []}))


def test_probe_rejects_zero_duration() -> None:
    with pytest.raises(ProbeError):
        parse_probe_output(probe_json(duration="0"))


def make_uploaded_asset(session: Session, user) -> SourceAsset:  # noqa: ANN001
    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="clip.mp4",
        byte_size=2048,
        upload_state="uploaded",
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()
    return asset


def test_verify_task_marks_asset_verified(session: Session, user, storage, monkeypatch) -> None:  # noqa: ANN001
    from worker import tasks

    asset = make_uploaded_asset(session, user)
    monkeypatch.setattr(tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(tasks, "probe", lambda _url: parse_probe_output(probe_json()))

    result = tasks.verify_source_asset.run(str(asset.id))
    assert result == {"status": "verified"}

    session.expire_all()
    stored = session.get(SourceAsset, asset.id)
    assert stored.upload_state == "verified"
    assert stored.duration_seconds == Decimal("12.500")
    assert (stored.width, stored.height) == (1920, 1080)


def test_verify_task_is_idempotent(session: Session, user, storage, monkeypatch) -> None:  # noqa: ANN001
    """재전달로 같은 태스크가 두 번 와도 결과가 같습니다."""
    from worker import tasks

    asset = make_uploaded_asset(session, user)
    monkeypatch.setattr(tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(tasks, "probe", lambda _url: parse_probe_output(probe_json()))

    assert tasks.verify_source_asset.run(str(asset.id)) == {"status": "verified"}
    assert tasks.verify_source_asset.run(str(asset.id)) == {"status": "already_verified"}


def test_verify_task_rejects_unreadable_file(session: Session, user, storage, monkeypatch) -> None:  # noqa: ANN001
    from worker import tasks

    asset = make_uploaded_asset(session, user)
    monkeypatch.setattr(tasks, "get_storage", lambda: storage)

    def broken(_url: str):  # noqa: ANN202
        raise ProbeError("ffprobe 실패: 형식을 알 수 없습니다")

    monkeypatch.setattr(tasks, "probe", broken)
    assert tasks.verify_source_asset.run(str(asset.id)) == {"status": "rejected"}

    session.expire_all()
    stored = session.get(SourceAsset, asset.id)
    assert stored.upload_state == "rejected"
    assert "ffprobe 실패" in stored.probe_error


def test_verify_task_rejects_too_short_video(session: Session, user, storage, monkeypatch) -> None:  # noqa: ANN001
    from worker import tasks

    asset = make_uploaded_asset(session, user)
    monkeypatch.setattr(tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(tasks, "probe", lambda _url: parse_probe_output(probe_json(duration="0.4")))
    assert tasks.verify_source_asset.run(str(asset.id)) == {"status": "rejected"}


def test_verify_task_handles_missing_asset(storage, monkeypatch) -> None:  # noqa: ANN001
    from worker import tasks

    monkeypatch.setattr(tasks, "get_storage", lambda: storage)
    assert tasks.verify_source_asset.run(str(uuid.uuid4())) == {"status": "missing"}


def test_dispatcher_sends_and_marks_published(session: Session) -> None:
    enqueue(
        session,
        topic="source_asset.verify",
        payload={"source_asset_id": str(uuid.uuid4())},
        dedupe_key="k1",
    )
    session.commit()

    sent: list[tuple[str, dict]] = []
    assert dispatch_pending(session, lambda name, payload: sent.append((name, payload))) == 1
    assert sent[0][0] == "worker.tasks.verify_source_asset"
    assert session.query(OutboxMessage).filter(OutboxMessage.published_at.is_(None)).count() == 0


def test_dispatcher_does_not_resend_published_messages(session: Session) -> None:
    enqueue(session, topic="source_asset.verify", payload={"a": "1"}, dedupe_key="k2")
    session.commit()
    dispatch_pending(session, lambda _n, _p: None)
    assert dispatch_pending(session, lambda _n, _p: None) == 0


def test_dispatcher_keeps_message_when_queue_send_fails(session: Session) -> None:
    """큐 전송에 실패하면 요청이 사라지지 않고 다음 주기에 다시 시도합니다."""
    enqueue(session, topic="source_asset.verify", payload={"a": "1"}, dedupe_key="k3")
    session.commit()

    def failing(_name: str, _payload: dict) -> None:
        raise RuntimeError("redis 연결 실패")

    assert dispatch_pending(session, failing) == 0
    message = session.query(OutboxMessage).one()
    assert message.published_at is None
    assert message.attempts == 1
    assert "redis 연결 실패" in message.last_error

    assert dispatch_pending(session, lambda _n, _p: None) == 1


def test_enqueue_is_deduplicated(session: Session) -> None:
    first = enqueue(session, topic="job.start", payload={"job_id": "1"}, dedupe_key="same")
    second = enqueue(session, topic="job.start", payload={"job_id": "1"}, dedupe_key="same")
    session.commit()
    assert first.id == second.id
    assert session.query(OutboxMessage).count() == 1


def test_dispatcher_skips_topics_without_task(session: Session) -> None:
    """아직 태스크가 연결되지 않은 주제는 보내지 않고 남겨 둡니다."""
    enqueue(session, topic="job.start", payload={"job_id": "1"}, dedupe_key="k4")
    session.commit()
    assert dispatch_pending(session, lambda _n, _p: None) == 0
    assert session.query(OutboxMessage).one().published_at is None
