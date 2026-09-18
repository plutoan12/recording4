"""상태 확인. 인증 없이 열어 둡니다."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from adminapi.deps import SessionDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(session: SessionDep) -> dict[str, str]:
    session.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
