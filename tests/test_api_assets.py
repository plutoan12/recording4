"""원본 등록. 서명 URL 발급, 업로드 완료 검증, 잘못된 파일 거부."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from adminapi.models import OutboxMessage, SourceAsset


def request_upload(client: TestClient, headers: dict, name: str = "clip.mp4", size: int = 1024):  # noqa: ANN201
    return client.post(
        "/source-assets", headers=headers, json={"filename": name, "byte_size": size}
    )


def test_upload_request_returns_presigned_url(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    response = request_upload(client, auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["storage_key"].startswith("sources/")
    assert body["upload_url"].startswith("https://storage.test/put/")
    assert body["expires_in"] > 0


def test_storage_keys_are_unique_per_request(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    """같은 키를 덮어쓰지 않도록 요청마다 새 키를 만듭니다."""
    first = request_upload(client, auth_headers).json()["storage_key"]
    second = request_upload(client, auth_headers).json()["storage_key"]
    assert first != second


def test_unsupported_extension_is_rejected(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    response = request_upload(client, auth_headers, name="notes.txt")
    assert response.status_code == 400


def test_missing_extension_is_rejected(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    assert request_upload(client, auth_headers, name="clip").status_code == 400


def test_oversized_file_is_rejected(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    response = request_upload(client, auth_headers, size=21 * 1024 * 1024 * 1024)
    assert response.status_code == 413


def test_path_traversal_in_filename_is_not_used_as_key(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    body = request_upload(client, auth_headers, name="../../etc/passwd.mp4").json()
    assert ".." not in body["storage_key"]


def test_complete_without_uploaded_object_is_rejected(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    created = request_upload(client, auth_headers).json()
    response = client.post(
        f"/source-assets/{created['source_asset_id']}/complete", headers=auth_headers, json={}
    )
    assert response.status_code == 409


def test_complete_with_size_mismatch_is_rejected(
    client: TestClient, auth_headers, storage, session: Session
) -> None:  # noqa: ANN001
    created = request_upload(client, auth_headers, size=1024).json()
    storage.put(created["storage_key"], byte_size=999)
    response = client.post(
        f"/source-assets/{created['source_asset_id']}/complete", headers=auth_headers, json={}
    )
    assert response.status_code == 409
    asset = session.get(SourceAsset, __import__("uuid").UUID(created["source_asset_id"]))
    assert asset.upload_state == "rejected"


def test_complete_marks_uploaded_and_queues_verification(
    client: TestClient, auth_headers, storage, session: Session
) -> None:  # noqa: ANN001
    created = request_upload(client, auth_headers, size=2048).json()
    storage.put(created["storage_key"], byte_size=2048, checksum="abc123")
    response = client.post(
        f"/source-assets/{created['source_asset_id']}/complete", headers=auth_headers, json={}
    )
    assert response.status_code == 200
    assert response.json()["upload_state"] == "uploaded"

    messages = session.query(OutboxMessage).all()
    assert [m.topic for m in messages] == ["source_asset.verify"]
    assert messages[0].payload == {"source_asset_id": created["source_asset_id"]}
    assert messages[0].published_at is None


def test_complete_twice_does_not_duplicate_outbox(
    client: TestClient, auth_headers, storage, session: Session
) -> None:  # noqa: ANN001
    """재전달이나 두 번 누름에도 실행 요청은 하나만 남습니다."""
    created = request_upload(client, auth_headers, size=2048).json()
    storage.put(created["storage_key"], byte_size=2048)
    for _ in range(2):
        client.post(
            f"/source-assets/{created['source_asset_id']}/complete", headers=auth_headers, json={}
        )
    assert session.query(OutboxMessage).count() == 1


def test_preview_url_requires_upload(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    created = request_upload(client, auth_headers).json()
    response = client.get(
        f"/source-assets/{created['source_asset_id']}/preview-url", headers=auth_headers
    )
    assert response.status_code == 409


def test_preview_url_is_issued_by_api(client: TestClient, auth_headers, storage) -> None:  # noqa: ANN001
    created = request_upload(client, auth_headers, size=10).json()
    storage.put(created["storage_key"], byte_size=10)
    client.post(
        f"/source-assets/{created['source_asset_id']}/complete", headers=auth_headers, json={}
    )
    response = client.get(
        f"/source-assets/{created['source_asset_id']}/preview-url", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["url"].startswith("https://storage.test/get/")


def test_unknown_asset_returns_404(client: TestClient, auth_headers) -> None:  # noqa: ANN001
    import uuid

    response = client.get(f"/source-assets/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404
