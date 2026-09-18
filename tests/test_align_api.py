"""타이밍 없는 대본 정렬. 실제 모델은 부르지 않고 대역으로 바꿉니다."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from adminapi.models import MediaTask, SourceAsset, TranscriptSegment
from pipeline.editing import Cue


def verified_asset(session: Session, user) -> SourceAsset:  # noqa: ANN001
    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="talk.mp4",
        byte_size=2048,
        duration_seconds=30,
        upload_state="verified",
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()
    return asset


def test_align_requires_auth(client: TestClient) -> None:
    assert (
        client.post(f"/source-assets/{uuid.uuid4()}/align", json={"text": "가"}).status_code == 401
    )


def test_align_rejects_empty_text(client: TestClient, auth_headers, session, user) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    response = client.post(
        f"/source-assets/{asset.id}/align", headers=auth_headers, json={"text": ""}
    )
    assert response.status_code == 422


def test_align_schedules_task_and_deduplicates(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    first = client.post(
        f"/source-assets/{asset.id}/align",
        headers=auth_headers,
        json={"text": "안녕하세요 반갑습니다", "language": "ko"},
    )
    assert first.status_code == 202
    assert first.json()["kind"] == "align"

    second = client.post(
        f"/source-assets/{asset.id}/align", headers=auth_headers, json={"text": "다른 대본"}
    )
    # 이미 대기 중인 정렬이 있으면 새로 만들지 않습니다.
    assert second.json()["id"] == first.json()["id"]
    assert session.query(MediaTask).filter_by(kind="align").count() == 1


def test_align_worker_stores_new_transcript_version(
    session: Session, user, storage, monkeypatch
) -> None:  # noqa: ANN001
    from worker import media_tasks

    asset = verified_asset(session, user)
    task = MediaTask(
        source_asset_id=asset.id,
        kind="align",
        settings={"text": "첫 문장. 두 번째 문장.", "language": "ko"},
    )
    session.add(task)
    session.commit()

    captured = {}

    def fake_align(source, text, **kwargs):  # noqa: ANN001, ANN202
        captured["text"] = text
        captured["language"] = kwargs.get("language")
        return [
            Cue(start=0.0, end=1.5, text="첫 문장."),
            Cue(start=1.6, end=3.0, text="두 번째 문장."),
        ]

    monkeypatch.setattr(media_tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(media_tasks, "align_text", fake_align)

    result = media_tasks.run_media.run(str(task.id))
    assert result["status"] == "succeeded"
    assert result["transcript_version"] == 1
    assert captured == {"text": "첫 문장. 두 번째 문장.", "language": "ko"}

    session.expire_all()
    rows = session.query(TranscriptSegment).filter_by(source_asset_id=asset.id).all()
    assert [r.text for r in rows] == ["첫 문장.", "두 번째 문장."]


def test_align_failure_is_recorded_without_leaking_details(
    session: Session, user, storage, monkeypatch
) -> None:  # noqa: ANN001
    from worker import media_tasks

    asset = verified_asset(session, user)
    task = MediaTask(source_asset_id=asset.id, kind="align", settings={"text": "대본"})
    session.add(task)
    session.commit()

    def broken(source, text, **kwargs):  # noqa: ANN001, ANN202
        raise RuntimeError("s3://bucket/secret-key?signature=abc")

    monkeypatch.setattr(media_tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(media_tasks, "align_text", broken)

    assert media_tasks.run_media.run(str(task.id))["status"] == "failed"
    session.expire_all()
    stored = session.get(MediaTask, task.id)
    assert stored.state == "failed"
    assert "signature" not in stored.error
    assert stored.error.startswith("RuntimeError")


def test_transcript_put_reports_violations(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    response = client.put(
        f"/source-assets/{asset.id}/transcript",
        headers=auth_headers,
        json={"cues": [{"start": 0, "end": 1, "text": "가" * 60}]},
    )
    assert response.status_code == 200
    kinds = {v["kind"] for v in response.json()["violations"]}
    assert {"lines", "cps"} <= kinds


def test_subtitle_check_reads_latest_version(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    client.put(
        f"/source-assets/{asset.id}/transcript",
        headers=auth_headers,
        json={"cues": [{"start": 0, "end": 1, "text": "가" * 60}]},
    )
    client.put(
        f"/source-assets/{asset.id}/transcript",
        headers=auth_headers,
        json={"cues": [{"start": 0, "end": 3, "text": "짧은 자막"}]},
    )
    body = client.get(f"/source-assets/{asset.id}/subtitle-check", headers=auth_headers).json()
    assert body["count"] == 1
    assert body["violations"] == []


def test_missing_dependency_message_reaches_the_operator(
    session: Session, user, storage, monkeypatch
) -> None:  # noqa: ANN001
    """설치 안내는 고정 문구라 그대로 보여 줍니다. 공급자 예외는 여전히 감춥니다."""
    from worker import media_tasks
    from worker.analysis import MissingDependency

    asset = verified_asset(session, user)
    task = MediaTask(source_asset_id=asset.id, kind="align", settings={"text": "대본"})
    session.add(task)
    session.commit()

    def missing(source, text, **kwargs):  # noqa: ANN001, ANN202
        raise MissingDependency(
            "자막 정렬 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        )

    monkeypatch.setattr(media_tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(media_tasks, "align_text", missing)

    media_tasks.run_media.run(str(task.id))
    session.expire_all()
    assert "[subtitles]" in session.get(MediaTask, task.id).error


def test_align_keeps_line_breaks_as_cue_boundaries() -> None:
    """줄바꿈이 있는 대본은 그 줄을 자막 경계로 유지하도록 옵션을 켭니다."""
    from worker.analysis import align_options

    def with_option(audio, text, *, language=None, original_split=False):  # noqa: ANN001, ANN202
        return None

    def without_option(audio, text, *, language=None):  # noqa: ANN001, ANN202
        return None

    assert align_options(with_option, "첫 줄\n두 번째 줄") == {"original_split": True}
    # 한 줄짜리 대본은 정렬기가 알아서 나눕니다.
    assert align_options(with_option, "한 줄짜리 대본") == {}
    # 옵션이 없는 버전에서도 정렬 자체는 그대로 진행합니다.
    assert align_options(without_option, "첫 줄\n두 번째 줄") == {}


def test_align_options_survive_unreadable_signatures() -> None:
    """서명을 못 읽는 호출체여도 정렬을 막지 않습니다."""
    from worker.analysis import align_options

    assert align_options(print, "첫 줄\n두 번째 줄") == {}
