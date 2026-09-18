"""화자 분리 연결. pyannote 모델은 부르지 않고 대역으로 바꿉니다."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from adminapi.models import Job, MediaTask, SourceAsset, TranscriptSegment, VoiceAssignment
from pipeline.speakers import SpeakerTurn


def verified_asset(session: Session, user) -> SourceAsset:  # noqa: ANN001
    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="interview.mp4",
        byte_size=4096,
        duration_seconds=60,
        upload_state="verified",
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()
    return asset


def with_transcript(session: Session, asset: SourceAsset) -> None:
    session.add_all(
        [
            TranscriptSegment(
                source_asset_id=asset.id,
                transcript_version=1,
                start_seconds=0,
                end_seconds=2,
                text="안녕하세요",
            ),
            TranscriptSegment(
                source_asset_id=asset.id,
                transcript_version=1,
                start_seconds=2,
                end_seconds=4,
                text="반갑습니다",
            ),
        ]
    )
    session.commit()


def test_diarize_requires_auth(client: TestClient) -> None:
    assert client.post(f"/source-assets/{uuid.uuid4()}/diarize", json={}).status_code == 401


def test_diarize_needs_a_transcript_first(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    response = client.post(f"/source-assets/{asset.id}/diarize", headers=auth_headers, json={})
    assert response.status_code == 409


def test_diarize_rejects_impossible_speaker_bounds(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    with_transcript(session, asset)
    response = client.post(
        f"/source-assets/{asset.id}/diarize",
        headers=auth_headers,
        json={"min_speakers": 4, "max_speakers": 2},
    )
    assert response.status_code == 422


def test_diarize_schedules_task_and_deduplicates(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    with_transcript(session, asset)
    first = client.post(
        f"/source-assets/{asset.id}/diarize", headers=auth_headers, json={"max_speakers": 2}
    )
    assert first.status_code == 202
    assert first.json()["kind"] == "diarize"

    second = client.post(f"/source-assets/{asset.id}/diarize", headers=auth_headers, json={})
    assert second.json()["id"] == first.json()["id"]
    assert session.query(MediaTask).filter_by(kind="diarize").count() == 1


def test_worker_labels_the_transcript_with_speakers(
    session: Session, user, storage, monkeypatch
) -> None:  # noqa: ANN001
    from worker import media_tasks

    asset = verified_asset(session, user)
    with_transcript(session, asset)
    task = MediaTask(
        source_asset_id=asset.id, kind="diarize", settings={"min_speakers": None, "max_speakers": 2}
    )
    session.add(task)
    session.commit()

    captured = {}

    def fake_diarize(source, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return [
            SpeakerTurn(start=0, end=2, speaker="SPEAKER_00"),
            SpeakerTurn(start=2, end=4, speaker="SPEAKER_01"),
        ]

    monkeypatch.setattr(media_tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(media_tasks, "diarize", fake_diarize)

    result = media_tasks.run_media.run(str(task.id))
    assert result["status"] == "succeeded"
    assert captured["max_speakers"] == 2
    # 대본 글자는 그대로 두고 화자만 붙인 새 버전을 만듭니다.
    assert result["transcript_version"] == 2
    assert result["labeled"] == 2
    assert result["speakers"] == {"SPEAKER_00": 2.0, "SPEAKER_01": 2.0}

    session.expire_all()
    rows = (
        session.query(TranscriptSegment)
        .filter_by(source_asset_id=asset.id, transcript_version=2)
        .order_by(TranscriptSegment.start_seconds)
        .all()
    )
    assert [(r.text, r.speaker) for r in rows] == [
        ("안녕하세요", "SPEAKER_00"),
        ("반갑습니다", "SPEAKER_01"),
    ]
    # 이전 버전은 그대로 남습니다.
    assert session.query(TranscriptSegment).filter_by(transcript_version=1).count() == 2


def test_missing_token_message_reaches_the_operator(
    session: Session, user, storage, monkeypatch
) -> None:  # noqa: ANN001
    from worker import media_tasks
    from worker.analysis import MissingDependency

    asset = verified_asset(session, user)
    with_transcript(session, asset)
    task = MediaTask(source_asset_id=asset.id, kind="diarize", settings={})
    session.add(task)
    session.commit()

    def missing(source, **kwargs):  # noqa: ANN001, ANN202
        raise MissingDependency("화자 분리에는 Hugging Face 토큰이 필요합니다. R4_HF_TOKEN")

    monkeypatch.setattr(media_tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(media_tasks, "diarize", missing)

    media_tasks.run_media.run(str(task.id))
    session.expire_all()
    assert "R4_HF_TOKEN" in session.get(MediaTask, task.id).error


def test_diarize_without_a_token_never_calls_the_model(tmp_path) -> None:  # noqa: ANN001
    """토큰이 없으면 모델을 내려받기 전에 막습니다."""
    import pytest

    from worker.analysis import MissingDependency, diarize

    with pytest.raises(MissingDependency) as error:
        diarize(tmp_path / "audio.wav", token=None)
    assert "R4_HF_TOKEN" in str(error.value)


def test_speakers_endpoint_summarizes_the_latest_version(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    session.add_all(
        [
            TranscriptSegment(
                source_asset_id=asset.id,
                transcript_version=2,
                start_seconds=0,
                end_seconds=3,
                text="첫 번째",
                speaker="SPEAKER_00",
            ),
            TranscriptSegment(
                source_asset_id=asset.id,
                transcript_version=2,
                start_seconds=3,
                end_seconds=4,
                text="두 번째",
                speaker="SPEAKER_01",
            ),
            TranscriptSegment(
                source_asset_id=asset.id,
                transcript_version=2,
                start_seconds=4,
                end_seconds=5,
                text="화자 없음",
            ),
        ]
    )
    session.commit()

    body = client.get(f"/source-assets/{asset.id}/speakers", headers=auth_headers).json()
    assert body["version"] == 2
    assert body["unlabeled"] == 1
    assert [s["speaker"] for s in body["speakers"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert body["speakers"][0]["seconds"] == 3.0


def test_voice_assignments_round_trip(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    job = Job(source_asset_id=asset.id, created_by_id=user.id, target_language="en")
    session.add(job)
    session.commit()

    first = client.put(
        f"/jobs/{job.id}/voice-assignments",
        headers=auth_headers,
        json={"assignments": {"SPEAKER_00": "voice-a", "SPEAKER_01": "voice-b"}},
    )
    assert first.status_code == 200
    assert first.json() == {"version": 1, "count": 2}

    second = client.put(
        f"/jobs/{job.id}/voice-assignments",
        headers=auth_headers,
        json={"assignments": {"SPEAKER_00": "voice-c"}},
    )
    assert second.json()["version"] == 2

    body = client.get(f"/jobs/{job.id}/voice-assignments", headers=auth_headers).json()
    # 최신 버전만 보여 주고 이전 버전은 감사용으로 남깁니다.
    assert body == {"version": 2, "assignments": {"SPEAKER_00": "voice-c"}}
    assert session.query(VoiceAssignment).filter_by(job_id=job.id).count() == 3


def test_voice_assignments_reject_empty_values(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = verified_asset(session, user)
    job = Job(source_asset_id=asset.id, created_by_id=user.id, target_language="en")
    session.add(job)
    session.commit()

    response = client.put(
        f"/jobs/{job.id}/voice-assignments",
        headers=auth_headers,
        json={"assignments": {"SPEAKER_00": "  "}},
    )
    assert response.status_code == 422
