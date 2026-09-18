"""설정. 비밀은 환경 변수로만 받습니다. 기본값은 개발 환경 기준입니다."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="R4_", extra="ignore")

    database_url: str = "postgresql+psycopg://recording4:devpass@localhost:5432/recording4"
    redis_url: str = "redis://localhost:6379/0"

    # 인증
    jwt_secret: str = Field(default="dev-only-not-a-secret", min_length=8)
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 60 * 8

    # 객체 저장소. 개발 환경은 MinIO 같은 S3 호환 서비스를 씁니다.
    s3_bucket: str = "recording4-dev"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key_id: str | None = "minioadmin"
    s3_secret_access_key: str | None = "minioadmin"
    s3_force_path_style: bool = True

    # 업로드 제한
    upload_url_ttl_seconds: int = 15 * 60
    max_source_bytes: int = 20 * 1024 * 1024 * 1024
    allowed_source_extensions: tuple[str, ...] = (".mp4", ".mov", ".mkv", ".webm", ".m4v")

    # 미리보기 서명 URL. 발급 주체는 항상 API입니다.
    preview_url_ttl_seconds: int = 5 * 60

    @property
    def is_production_secret(self) -> bool:
        return self.jwt_secret != "dev-only-not-a-secret"


@lru_cache
def get_settings() -> Settings:
    return Settings()
