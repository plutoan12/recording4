"""DB 세션. DB가 상태의 기준이므로 쓰기는 항상 트랜잭션 안에서 합니다."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from adminapi.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _connect_args(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        _engine = create_engine(
            url, pool_pre_ping=True, future=True, connect_args=_connect_args(url)
        )
        if url.startswith("sqlite"):
            # 테스트에서 외래 키 제약이 실제로 걸리도록 합니다.
            event.listen(_engine, "connect", _sqlite_pragma)
    return _engine


def _sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def reset_engine() -> None:
    """테스트에서 설정을 바꾼 뒤 엔진을 다시 만들 때 씁니다."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def session_scope() -> Iterator[Session]:
    """FastAPI 의존성. 요청 하나가 트랜잭션 하나입니다."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
