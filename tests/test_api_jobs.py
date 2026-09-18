"""작업 생성·목록·상태와 전이."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from adminapi.models import Job, OutboxMessage, SourceAsset
from pipeline.states import JobState


def make_verified_asset(session: Session, user) -> SourceAsset:  # noqa: ANN001
    asset = SourceAsset(
        storage_key=f"sources/2026/09/18/{uuid.uuid4()}.mp4",
        original_filename="clip.mp4",
        byte_size=2048,
        upload_state="verified",
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()
    return asset


def test_job_creation_requires_verified_asset(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="clip.mp4",
        upload_state="uploaded",
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()

    response = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "target_language": "en"},
    )
    assert response.status_code == 409


def test_job_creation_queues_start_request(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = make_verified_asset(session, user)
    response = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "target_language": "en"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == JobState.QUEUED
    messages = session.query(OutboxMessage).filter_by(topic="job.start").all()
    assert len(messages) == 1
    assert messages[0].payload == {"job_id": body["id"]}


def test_job_creation_with_unknown_asset_returns_404(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    response = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": str(uuid.uuid4()), "target_language": "en"},
    )
    assert response.status_code == 404


def test_job_list_and_filter(client: TestClient, auth_headers, session: Session, user) -> None:  # noqa: ANN001
    asset = make_verified_asset(session, user)
    for language in ("en", "ja"):
        client.post(
            "/jobs",
            headers=auth_headers,
            json={"source_asset_id": str(asset.id), "target_language": language},
        )
    assert len(client.get("/jobs", headers=auth_headers).json()) == 2
    assert len(client.get("/jobs?state=queued", headers=auth_headers).json()) == 2
    assert client.get("/jobs?state=approved", headers=auth_headers).json() == []


def test_worker_only_transition_is_rejected(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    asset = make_verified_asset(session, user)
    job_id = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "target_language": "en"},
    ).json()["id"]

    response = client.post(
        f"/jobs/{job_id}/transitions", headers=auth_headers, json={"event": "start"}
    )
    assert response.status_code == 409

    stored = session.get(Job, uuid.UUID(job_id))
    session.refresh(stored)
    assert stored.state is JobState.QUEUED


def test_transition_outside_table_is_rejected(
    client: TestClient, auth_headers, session: Session, user
) -> None:  # noqa: ANN001
    """전이표에 없는 전이는 409로 거부합니다."""
    asset = make_verified_asset(session, user)
    job_id = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "target_language": "en"},
    ).json()["id"]

    response = client.post(
        f"/jobs/{job_id}/transitions", headers=auth_headers, json={"event": "approve"}
    )
    assert response.status_code == 409
    assert "허용되지 않은 전이" in response.json()["detail"]


def test_reject_records_reason(client: TestClient, auth_headers, session: Session, user) -> None:  # noqa: ANN001
    asset = make_verified_asset(session, user)
    job_id = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "target_language": "en"},
    ).json()["id"]
    session.get(Job, uuid.UUID(job_id)).state = JobState.REVIEW_REQUIRED
    session.commit()

    response = client.post(
        f"/jobs/{job_id}/transitions",
        headers=auth_headers,
        json={"event": "reject", "reason": "자막 시간이 어긋납니다"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == JobState.REJECTED
    assert response.json()["state_reason"] == "자막 시간이 어긋납니다"
