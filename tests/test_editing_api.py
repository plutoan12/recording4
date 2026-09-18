import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from adminapi.models import Approval, Artifact, SourceAsset


@pytest.fixture
def asset(session, user):
    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="test.mp4",
        created_by_id=user.id,
        duration_seconds=Decimal("120"),
        width=1920,
        height=1080,
        upload_state="verified",
    )
    session.add(asset)
    session.commit()
    return asset


def test_auth_required(client):
    assert client.get("/media-tasks").status_code == 401
    assert client.post("/clips", json={}).status_code == 401


def test_range_validation_and_independent_clips(client, auth_headers, asset):
    data = {"source_asset_id": str(asset.id), "start": 100, "end": 130}
    assert client.post("/clips", headers=auth_headers, json=data).status_code == 422
    data.update(start=10, end=40)
    a = client.post("/clips", headers=auth_headers, json=data)
    b = client.post("/clips", headers=auth_headers, json=data)
    assert a.status_code == b.status_code == 202
    assert a.json()["clip_edit_id"] != b.json()["clip_edit_id"]
    assert a.json()["state"] == "pending"
    assert (
        client.post(f"/media-tasks/{a.json()['id']}/retry", headers=auth_headers).status_code == 409
    )


def test_transcript_snapshots_and_suggestions(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/transcript"
    cues = [{"start": 2, "end": 10, "text": "hello"}]
    assert client.put(path, headers=auth_headers, json={"cues": cues}).json()["version"] == 1
    assert client.get(path, headers=auth_headers).json() == cues
    assert (
        client.get(f"/source-assets/{asset.id}/suggestions", headers=auth_headers).json()[0][
            "start"
        ]
        == 2
    )
    assert client.put(path, headers=auth_headers, json={"cues": cues}).json()["version"] == 2
    cues[0]["end"] = 200
    assert client.put(path, headers=auth_headers, json={"cues": cues}).status_code == 422


def test_analysis_deduplicates_active_requests(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/analyze"
    a = client.post(path, headers=auth_headers, json={"kind": "scenes"}).json()
    b = client.post(path, headers=auth_headers, json={"kind": "scenes"}).json()
    assert a["id"] == b["id"]


def test_render_worker_and_version_approval(
    client, auth_headers, asset, session, tmp_path, monkeypatch
):
    import worker.media_tasks as module
    from adminapi.db import get_session_factory

    class Storage:
        def download_file(self, key, path):
            path.write_bytes(b"input")

        def upload_file(self, key, path, content_type):
            assert path.read_bytes() == b"rendered"

    monkeypatch.setattr(module, "get_storage", lambda: Storage())
    monkeypatch.setattr(
        module, "render_clip", lambda source, output, spec, **_: output.write_bytes(b"rendered")
    )
    data = {"source_asset_id": str(asset.id), "start": 0, "end": 10}
    created = client.post("/clips", headers=auth_headers, json=data).json()
    result = module.run_media.run(created["id"])
    assert result["status"] == "succeeded"
    assert module.run_media.run(created["id"])["status"] == "already_claimed"
    artifact_id = result["artifact_id"]
    first = client.post(f"/artifacts/{artifact_id}/approve", headers=auth_headers).json()
    second = client.post(f"/artifacts/{artifact_id}/approve", headers=auth_headers).json()
    assert first == second
    another = client.post("/clips", headers=auth_headers, json={**data, "title": "new"}).json()
    result2 = module.run_media.run(another["id"])
    with get_session_factory()() as db:
        assert (
            db.scalar(
                select(Approval).where(Approval.artifact_id == uuid.UUID(result2["artifact_id"]))
            )
            is None
        )
        assert len(list(db.scalars(select(Artifact)))) == 2


def test_failed_worker_can_retry(client, auth_headers, asset, monkeypatch):
    import worker.media_tasks as module

    class BrokenStorage:
        def download_file(self, *args):
            raise RuntimeError("secret-token-in-url")

    monkeypatch.setattr(module, "get_storage", lambda: BrokenStorage())
    created = client.post(
        "/clips",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "start": 0, "end": 10},
    ).json()
    assert module.run_media.run(created["id"])["status"] == "failed"
    tasks = client.get("/media-tasks", headers=auth_headers).json()
    assert "secret-token" not in str(tasks)
    retry = client.post(f"/media-tasks/{created['id']}/retry", headers=auth_headers)
    assert retry.status_code == 202 and retry.json()["state"] == "pending"
