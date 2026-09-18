"""테스트 공통 준비.

기본은 SQLite입니다. R4_DATABASE_URL이 PostgreSQL을 가리키면 그쪽에 붙고
postgres 표시가 붙은 테스트도 함께 실행합니다. 외부 공급자는 호출하지 않습니다.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

TEST_PASSWORD = "test-password-1234"


def _database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    configured = os.environ.get("R4_DATABASE_URL")
    if configured:
        return configured
    path = tmp_path_factory.mktemp("db") / "test.db"
    return f"sqlite:///{path}"


@pytest.fixture(scope="session", autouse=True)
def _environment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    os.environ["R4_DATABASE_URL"] = _database_url(tmp_path_factory)
    os.environ.setdefault("R4_JWT_SECRET", "test-secret-value")
    yield


@pytest.fixture(scope="session")
def test_password() -> str:
    """테스트 계정 비밀번호. conftest를 모듈로 import하지 않도록 픽스처로 제공합니다."""
    return TEST_PASSWORD


@pytest.fixture(scope="session")
def is_postgres() -> bool:
    return os.environ["R4_DATABASE_URL"].startswith("postgresql")


@pytest.fixture(scope="session")
def _schema(_environment: None) -> Iterator[None]:
    from adminapi.config import get_settings
    from adminapi.db import get_engine, reset_engine
    from adminapi.models import Base

    get_settings.cache_clear()
    reset_engine()
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def session(_schema: None) -> Iterator[Session]:
    from adminapi.db import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        yield session
        session.rollback()


@pytest.fixture(autouse=True)
def _clean_tables(_schema: None) -> Iterator[None]:
    yield
    from adminapi.db import get_engine
    from adminapi.models import Base

    with get_engine().begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@dataclass
class FakeObject:
    byte_size: int
    checksum: str | None = "fake-checksum"


class FakeStorage:
    """저장소 대역. 실제 S3를 부르지 않습니다."""

    def __init__(self) -> None:
        self.objects: dict[str, FakeObject] = {}

    def presigned_put_url(self, key: str, ttl_seconds: int) -> str:
        return f"https://storage.test/put/{key}?ttl={ttl_seconds}"

    def presigned_get_url(self, key: str, ttl_seconds: int) -> str:
        return f"https://storage.test/get/{key}?ttl={ttl_seconds}"

    def head(self, key: str) -> FakeObject | None:
        return self.objects.get(key)

    def put(self, key: str, byte_size: int, checksum: str | None = "fake-checksum") -> None:
        self.objects[key] = FakeObject(byte_size=byte_size, checksum=checksum)


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client(_schema: None, storage: FakeStorage) -> Iterator[TestClient]:
    from adminapi.main import app
    from adminapi.storage import get_storage

    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user(session: Session):  # noqa: ANN201
    from adminapi.models import User
    from adminapi.security import hash_password

    record = User(
        id=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(TEST_PASSWORD),
    )
    session.add(record)
    session.commit()
    return record


@pytest.fixture
def auth_headers(client: TestClient, user) -> dict[str, str]:  # noqa: ANN001
    response = client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
