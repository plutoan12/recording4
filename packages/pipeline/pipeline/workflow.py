"""Immutable job options; credentials remain in server configuration."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeline.editing import Cue, EditSpec


class WorkflowOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    audio_mode: Literal["original", "subtitles", "dub"] = "dub"
    burn_subtitles: bool = True
    source_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    voice_id: str | None = Field(default=None, max_length=128)
    lipsync: bool = False
    reuse_from_job_id: UUID | None = None
    clip: EditSpec | None = None
    transcript: list[Cue] | None = Field(default=None, max_length=5000)
    translated_cues: list[Cue] | None = Field(default=None, max_length=5000)
    # 한 문장이 여러 자막으로 잘려 있으면 합쳐서 번역하고 다시 나눕니다.
    # 글자 수가 늘지 않아 요금은 그대로여서 기본으로 켭니다. 더빙에는 쓰지
    # 않습니다(아래에서 꺼집니다). 문장부호가 거의 없는 대본에서도 묶지
    # 않습니다(`pipeline.translation_context.punctuated`).
    translate_context: bool = True
    # 기계 번역이 어색한 자막만 골라 LLM으로 다시 번역합니다. 유료입니다.
    # 기본으로 켜 두되 서버에 LLM 키·모델 이름이 없으면 조용히 건너뜁니다.
    translate_polish: bool = True
    budget_usd: Decimal = Field(default=Decimal("0"), ge=0, le=10000, decimal_places=4)

    @model_validator(mode="after")
    def consistent(self):
        if self.audio_mode != "dub" and self.lipsync:
            raise ValueError("립싱크는 더빙 작업에만 사용할 수 있습니다.")
        if self.audio_mode == "dub":
            # 더빙은 자막 조각이 곧 그 구간의 발화라 문장을 다시 나누면 말이
            # 어긋납니다. 기본값이므로 막지 않고 끕니다.
            object.__setattr__(self, "translate_context", False)
        return self


def rendered_cues(data: dict) -> list[dict]:
    """영상에 구운 자막.

    더빙 음성에 맞춰 재정렬한 자막이 있으면 그것, 없으면 번역본, 없으면 원본
    대본입니다. 렌더와 내보내기가 같은 자막을 쓰도록 이 순서를 한곳에 둡니다.
    키가 있으면 그 값을 씁니다. 빈 목록도 렌더가 쓴 값이므로 건너뛰지 않습니다.
    """
    for key in ("aligned", "translated", "cues"):
        if key in data:
            return data[key]
    return []


def rendered_language(data: dict, options: WorkflowOptions) -> str | None:
    """구운 자막의 언어. 번역 단계를 지난 자막은 목표 언어입니다.

    번역 전 자막은 원본 언어인데, 자동 감지에 맡겼다면 알 수 없어 None입니다.
    """
    if "aligned" in data or "translated" in data:
        return data.get("target")
    return options.source_language
