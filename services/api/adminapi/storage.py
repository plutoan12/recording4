"""객체 저장소.

서명 URL 발급 주체는 항상 API입니다. 브라우저는 저장소에 직접 올리고 내려받지만
URL은 API가 권한을 확인한 뒤에만 만듭니다. 로그에는 서명 URL을 남기지 않습니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Protocol

import boto3
from botocore.config import Config

from adminapi.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    byte_size: int
    checksum: str | None


class ObjectStorage(Protocol):
    """테스트에서 가짜 구현으로 바꿀 수 있도록 프로토콜로 둡니다."""

    def presigned_put_url(self, key: str, ttl_seconds: int) -> str: ...

    def presigned_get_url(self, key: str, ttl_seconds: int) -> str: ...

    def head(self, key: str) -> ObjectInfo | None: ...


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
            ),
        )

    def presigned_put_url(self, key: str, ttl_seconds: int) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )

    def presigned_get_url(self, key: str, ttl_seconds: int) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )

    def head(self, key: str) -> ObjectInfo | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except self._client.exceptions.ClientError:
            return None
        return ObjectInfo(
            byte_size=int(response["ContentLength"]),
            checksum=(response.get("ETag") or "").strip('"') or None,
        )


@lru_cache
def get_storage() -> ObjectStorage:
    return S3Storage(get_settings())


def build_source_key(original_filename: str, *, now: datetime | None = None) -> str:
    """원본 저장 키.

    같은 키를 덮어쓰지 않도록 항상 새 UUID를 붙입니다. 파일 이름은 확장자만
    사용하고 경로 요소는 버립니다.
    """
    moment = now or datetime.now(UTC)
    suffix = PurePosixPath(original_filename.replace("\\", "/")).suffix.lower()
    return f"sources/{moment:%Y/%m/%d}/{uuid.uuid4()}{suffix}"
