"""로그인."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from adminapi.config import get_settings
from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import User
from adminapi.schemas import LoginRequest, TokenResponse, UserResponse
from adminapi.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    user = session.scalar(select(User).where(User.email == payload.email.lower()))
    # 사용자가 없을 때도 같은 응답을 주어 계정 존재 여부를 흘리지 않습니다.
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        expires_in=settings.access_token_ttl_seconds,
    )


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> User:
    return user
