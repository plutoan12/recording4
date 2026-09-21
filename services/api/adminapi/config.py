"""설정. 비밀은 환경 변수로만 받습니다. 기본값은 개발 환경 기준입니다."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

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

    # 더빙은 원본 오디오를 통째로 바꿉니다. 음악과 효과음도 같이 사라집니다.
    # 켜면 원본에서 목소리만 빼고 남은 소리를 대사 아래에 깝니다. 느려서
    # (CPU에서 1분 소리에 수십 초) 기본은 꺼 둡니다. 남는 목소리 흔적은
    # scripts/verify_separation.py가 잽니다.
    background_audio_enabled: bool = False
    background_gain_db: float = Field(default=-9.0, le=0)

    # 자막 싱크 보정(ffsubsync). 기본값의 근거는 docs/TECH_DECISIONS.md에 있습니다.
    # 프레임률 맞추기는 **끕니다.** 우리 대본은 이 원본에서 나왔으므로 원본과
    # 자막의 프레임률이 다를 수 없습니다. 켜 두면 보정기가 자막을 늘였다 줄이며
    # 없는 차이를 맞추려 듭니다(측정: 합성 음성에서 배율 0.999로 이미 맞는 자막을
    # 0.013초 흔들었고, 끄면 오차 0.000초).
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
    # 번역 경로: STT → 기계 번역(google | deepl | huggingface) → 용어집 → (선택) Claude
    # 문맥·말투 보정 → QA → SRT/VTT → TTS. 언어 목록은 pipeline.languages 한 곳입니다.
    # huggingface는 로컬 NLLB 모델이라 유료 예약 없이 돌지만 느리고 출발 언어가 필요합니다.
    translation_provider: Literal["google", "deepl", "huggingface"] = "google"
    deepl_api_key: str | None = None
    huggingface_translation_model: str = "facebook/nllb-200-distilled-600M"
    # 기계 번역 초안을 Claude가 앞뒤 문맥과 용어집을 보고 고칩니다. 단가가 비어 있으면
    # 돌지 않습니다. 실제 청구는 토큰 단위인데 글자 수로 잡으므로 넉넉한 상한을 적습니다.
    translation_refine_enabled: bool = False
    translation_refine_model: str = "claude-sonnet-5"
    refine_usd_per_1k_chars: Decimal | None = None
    # 묶음 나누기(LLM-Subtrans 기본값). 앞뒤 문맥 줄 수는 llm-subs 기본값(3)입니다.
    translate_scene_gap_seconds: float = Field(default=30.0, gt=0)
    translate_min_batch_lines: int = Field(default=1, ge=1)
    translate_max_batch_lines: int = Field(default=100, ge=1, le=100)
    translate_context_lines: int = Field(default=3, ge=0, le=20)
    tts_usd_per_1k_chars: Decimal | None = None
    lipsync_usd_per_second: Decimal | None = None
    # 하이라이트 추천(Claude). 실제 청구는 토큰 단위인데 여기는 글자 수로
    # 잡으므로 **넉넉한 상한**을 적습니다. 비어 있으면 추천이 돌지 않습니다.
    highlight_usd_per_1k_chars: Decimal | None = None
    # GitHub 저장소에서 하는 자막 검수. 켜야 쓰기(브랜치·커밋·PR)가 됩니다. 토큰은 그
    # 저장소의 contents·pull requests 쓰기 권한만 있으면 됩니다. **기본 브랜치에는 쓰지
    # 않고 병합하지 않습니다.** 병합은 사람이 합니다.
    github_review_enabled: bool = False
    github_token: str | None = None
    github_repository: str | None = None
    github_base_branch: str = "main"
    github_api_url: str = "https://api.github.com"
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
