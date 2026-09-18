"""2단계 완료 기준 확인.

로그인 → 원본 등록 → 워커의 파일 확인 → 관리화면 상태 표시까지 한 번에 잇습니다.
저장소와 ffprobe는 대역으로 바꾸고 외부 서비스는 부르지 않습니다.
"""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from adminapi.models import OutboxMessage
from pipeline.states import JobState
from worker.dispatcher import dispatch_pending
from worker.media import parse_probe_output

PROBE_OUTPUT = json.dumps(
    {
        "format": {"duration": "95.250", "format_name": "mov,mp4,m4a"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    }
)


def test_login_to_job_status(
    client: TestClient,
    session: Session,
    storage,
    user,
    monkeypatch,
) -> None:  # noqa: ANN001
    from tests.conftest import TEST_PASSWORD

    from worker import tasks

    # 1. 로그인
    token = client.post(
        "/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 업로드 URL 발급과 저장소 직접 업로드
    created = client.post(
        "/source-assets", headers=headers, json={"filename": "talk.mp4", "byte_size": 4096}
    ).json()
    storage.put(created["storage_key"], byte_size=4096, checksum="etag-1")

    # 3. 업로드 완료 검증. 실행 요청이 outbox에 쌓입니다.
    completed = client.post(
        f"/source-assets/{created['source_asset_id']}/complete", headers=headers, json={}
    ).json()
    assert completed["upload_state"] == "uploaded"

    # 4. 디스패처가 큐로 보냅니다. 큐에는 식별자만 들어갑니다.
    dispatched: list[tuple[str, dict]] = []
    assert dispatch_pending(session, lambda name, payload: dispatched.append((name, payload))) == 1
    assert dispatched == [
        ("worker.tasks.verify_source_asset", {"source_asset_id": created["source_asset_id"]})
    ]

    # 5. 워커가 파일을 검사합니다.
    monkeypatch.setattr(tasks, "get_storage", lambda: storage)
    monkeypatch.setattr(tasks, "probe", lambda _url: parse_probe_output(PROBE_OUTPUT))
    assert tasks.verify_source_asset.run(created["source_asset_id"]) == {"status": "verified"}

    # 6. 관리화면이 읽는 목록에 검사 결과가 보입니다.
    listed = client.get("/source-assets", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["upload_state"] == "verified"
    assert listed[0]["duration_seconds"] == "95.250"
    assert (listed[0]["width"], listed[0]["height"]) == (1920, 1080)

    # 7. 검사를 통과한 원본으로만 작업을 만듭니다.
    job = client.post(
        "/jobs",
        headers=headers,
        json={"source_asset_id": created["source_asset_id"], "target_language": "en"},
    ).json()
    assert job["state"] == JobState.QUEUED

    jobs = client.get("/jobs", headers=headers).json()
    assert [item["id"] for item in jobs] == [job["id"]]

    # 8. 작업 시작 요청도 outbox에 남아 있습니다.
    pending = session.query(OutboxMessage).filter(OutboxMessage.published_at.is_(None)).all()
    assert [message.topic for message in pending] == ["job.start"]


def test_rejected_file_blocks_job_creation(
    client: TestClient, session: Session, storage, auth_headers, monkeypatch
) -> None:  # noqa: ANN001
    """잘못된 파일은 거부되고 그 원본으로는 작업을 만들 수 없습니다."""
    from worker import tasks
    from worker.media import ProbeError

    created = client.post(
        "/source-assets", headers=auth_headers, json={"filename": "broken.mp4", "byte_size": 10}
    ).json()
    storage.put(created["storage_key"], byte_size=10)
    client.post(
        f"/source-assets/{created['source_asset_id']}/complete", headers=auth_headers, json={}
    )

    monkeypatch.setattr(tasks, "get_storage", lambda: storage)

    def broken(_url: str):  # noqa: ANN202
        raise ProbeError("ffprobe 실패: moov atom not found")

    monkeypatch.setattr(tasks, "probe", broken)
    assert tasks.verify_source_asset.run(created["source_asset_id"]) == {"status": "rejected"}

    listed = client.get("/source-assets", headers=auth_headers).json()
    assert listed[0]["upload_state"] == "rejected"
    assert "moov atom" in listed[0]["probe_error"]

    response = client.post(
        "/jobs",
        headers=auth_headers,
        json={"source_asset_id": created["source_asset_id"], "target_language": "en"},
    )
    assert response.status_code == 409


def test_unknown_job_is_not_leaked(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    assert client.get(f"/jobs/{uuid.uuid4()}", headers=auth_headers).status_code == 404
