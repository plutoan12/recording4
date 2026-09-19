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
    # 화자 분리(pyannote)는 Hugging Face 게이트 모델이라 토큰과 약관 동의가 필요합니다.
    hf_token: str | None = None

    # 자막 표시 규칙. 길이 단위는 글자 폭입니다(한글 1자, 라틴·공백·문장부호 0.5자).
    # 기본값은 Netflix 한국어 자막 지침 I부(일반 번역 자막, 성인물)입니다.
    # 14자/초는 SDH 상향값이라 쓰지 않습니다. 실제 화면 측정 후 조정합니다.
    subtitle_max_chars_per_line: int = 16
    subtitle_max_lines: int = 2
    subtitle_max_cps: float = 12.0
    subtitle_min_duration: float = 1.0
    subtitle_max_duration: float = 7.0

    # 자막 싱크 보정(ffsubsync). 기본값의 근거는 docs/TECH_DECISIONS.md에 있습니다.
    # 프레임률 맞추기는 **끕니다.** 우리 대본은 이 원본에서 나왔으므로 원본과
    # 자막의 프레임률이 다를 수 없습니다. 켜 두면 보정기가 자막을 늘였다 줄이며
    # 없는 차이를 맞추려 듭니다(측정: 합성 음성에서 배율 0.999로 이미 맞는 자막을
    # 0.013초 흔들었고, 끄면 오차 0.000초).
    # 자막 싱크를 다시 잡는 기본 방법.
    #
    # align = 대본 글자를 원본 음성에 단어 단위로 맞춥니다(강제 정렬). 자막마다
    #   시각을 따로 받으므로 문장별로 다르게 어긋난 자막과 말 속도가 달라진
    #   자막도 맞습니다. 대신 음성 인식 모델을 돌려 느립니다.
    # shift = ffsubsync로 전체를 통째로 옮깁니다. 빠르지만 이동값이 하나뿐이라
    #   위 경우를 원리상 맞출 수 없습니다. 대본 글자가 실제 발화와 다른
    #   번역 자막에는 이쪽만 쓸 수 있습니다.
    #
    # **기본값은 shift입니다.** 한국어 사람 목소리로 잰 값입니다.
    #
    # - 자막이 통째로 밀린 경우: 열 조건에서 shift 0.00~0.50초, align
    #   0.75~2.63초. shift가 열 번 다 이깁니다.
    # - 자막마다 어긋남이 쌓이는 경우: 자막당 0.3초부터 align이 낫습니다
    #   (1.22초 대 1.02초). 서로 다른 두 표본에서 같은 지점이 나왔습니다.
    # - 다만 그 자리에서도 둘 다 0.5초 한계를 넘습니다. align이 덜 틀릴 뿐입니다.
    #
    # 흔한 어긋남(녹화 시작 시각 차이, 앞부분 잘라내기)은 한 덩어리 모양이라
    # 기본값은 shift로 둡니다. 측정과 해석은 docs/TECH_DECISIONS.md에 있고
    # 표본 id까지 적혀 있습니다.
    sync_method: str = "shift"
    sync_fix_framerate: bool = False
    # 찾을 이동의 상한. 넓게 열어 두면 엉뚱한 최고점을 고릅니다. ffsubsync 기본값
    # 60초는 다른 판본에서 받은 자막을 위한 값이라 우리 쓰임에 맞지 않습니다.
    # 이 10초는 잰 값이 아니라 정한 값입니다. scripts/verify_sync.py --sweep으로
    # 실제 음성에서 다시 재세요.
    sync_max_offset_seconds: float = 10.0
    # 발화 검출기. None이면 ffsubsync 기본값입니다. 사람 목소리에서 어느 쪽이
    # 나은지는 아직 정하지 못했습니다(아래 문서의 측정 기록을 보세요).
    sync_vad: str | None = None

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
    # 선택 가능한 자막 트랙 업로드. 영상에는 자막이 이미 구워져 있으므로 켜면
    # 시청자 화면에 자막이 두 벌 보일 수 있습니다. 확인한 뒤 켜세요.
    youtube_captions_enabled: bool = False
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
