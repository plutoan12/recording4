"""설정. 비밀은 환경 변수로만 받습니다. 기본값은 개발 환경 기준입니다."""

from __future__ import annotations

from decimal import Decimal
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

    s3_public_endpoint_url: str | None = None
    whisper_model: str = "small"
    whisper_device: str = "cpu"

    # 자막 표시 규칙. 기본값은 한국어 기준 제안이며 실제 화면 측정 후 조정합니다.
    subtitle_max_chars_per_line: int = 20
    subtitle_max_lines: int = 2
    subtitle_max_cps: float = 20.0
    subtitle_min_duration: float = 1.0
    subtitle_max_duration: float = 7.0

    # Explicit deployment switches: tests and default installs never call paid APIs.
    paid_processing_enabled: bool = False
    max_job_budget_usd: Decimal | None = Field(default=None, ge=0)
    max_monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    google_cloud_project: str | None = None
    elevenlabs_api_key: str | None = None
    tts_model: str = "eleven_multilingual_v2"
    tts_model_version: str | None = None
    tts_voice_version: str | None = None
    sync_api_key: str | None = None
    translate_usd_per_1k_chars: Decimal | None = None
    tts_usd_per_1k_chars: Decimal | None = None
    lipsync_usd_per_second: Decimal | None = None
    youtube_upload_enabled: bool = False
    youtube_credentials_file: str | None = None
    youtube_channel_id: str | None = None

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
