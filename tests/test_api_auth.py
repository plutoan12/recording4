"""인증. 미인증 접근은 모두 거부되어야 합니다."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adminapi.security import hash_password, verify_password


def test_login_returns_token(client: TestClient, user, test_password: str) -> None:  # noqa: ANN001
    response = client.post("/auth/login", json={"email": user.email, "password": test_password})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_with_wrong_password_is_rejected(client: TestClient, user) -> None:  # noqa: ANN001
    response = client.post("/auth/login", json={"email": user.email, "password": "wrong-password"})
    assert response.status_code == 401


def test_login_for_unknown_email_gives_same_error(client: TestClient, test_password: str) -> None:
    """계정 존재 여부를 응답으로 흘리지 않습니다."""
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": test_password}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "이메일 또는 비밀번호가 올바르지 않습니다."


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/auth/me"),
        ("get", "/jobs"),
        ("post", "/jobs"),
        ("get", "/source-assets"),
        ("post", "/source-assets"),
    ],
)
def test_unauthenticated_access_is_rejected(client: TestClient, method: str, path: str) -> None:
    caller = getattr(client, method)
    response = caller(path) if method == "get" else caller(path, json={})
    assert response.status_code == 401


def test_invalid_token_is_rejected(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_me_returns_current_user(client: TestClient, auth_headers, user) -> None:  # noqa: ANN001
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct-horse-battery")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("other-password-1234", encoded)


def test_short_password_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("short")


def test_corrupted_hash_does_not_raise() -> None:
    assert not verify_password("anything", "not-a-valid-hash")
