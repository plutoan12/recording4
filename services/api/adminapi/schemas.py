"""요청·응답 형식."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from pipeline.states import JobState
from pipeline.workflow import WorkflowOptions


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    byte_size: int = Field(gt=0)


class UploadResponse(BaseModel):
    source_asset_id: uuid.UUID
    storage_key: str
    upload_url: str
    expires_in: int


class UploadCompleteRequest(BaseModel):
    checksum: str | None = Field(default=None, max_length=128)


class SourceAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    storage_key: str
    upload_state: str
    byte_size: int | None
    duration_seconds: Decimal | None
    width: int | None
    height: int | None
    probe_error: str | None
    created_at: datetime


class PreviewUrlResponse(BaseModel):
    url: str
    expires_in: int


class JobCreateRequest(BaseModel):
    source_asset_id: uuid.UUID
    target_language: str = Field(min_length=2, max_length=16, pattern=r"^[a-zA-Z-]+$")
    workflow: WorkflowOptions = Field(default_factory=WorkflowOptions)


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_asset_id: uuid.UUID
    target_language: str
    state: JobState
    current_stage: str | None
    state_reason: str | None
    created_at: datetime
    updated_at: datetime


class JobTransitionRequest(BaseModel):
    event: str = Field(min_length=1, max_length=32)
    reason: str | None = Field(default=None, max_length=1000)


class ErrorResponse(BaseModel):
    detail: str
