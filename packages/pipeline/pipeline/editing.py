"""Validated edit decisions. Source media and transcript versions stay immutable."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Cue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("자막 종료는 시작보다 뒤여야 합니다.")
        return self


class EditSpec(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    mode: Literal["crop", "pad"] = "pad"
    focus_x: float = Field(default=0.5, ge=0, le=1)
    focus_y: float = Field(default=0.5, ge=0, le=1)
    width: int = Field(default=1080, ge=180, le=2160, multiple_of=2)
    height: int = Field(default=1920, ge=320, le=3840, multiple_of=2)
    title: str = Field(default="", max_length=120)
    burn_subtitles: bool = True
    caption_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    # 자막 모양은 템플릿(pipeline.subtitle_templates)이 정합니다. 이름만 두고 실제
    # 확인은 렌더와 API가 합니다(순환 참조를 피합니다). 글자 크기는 비우면 템플릿
    # 값이고, 적으면 그 값이 템플릿보다 우선합니다.
    subtitle_template: str = Field(default="default", pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    font_size: int | None = Field(default=None, ge=20, le=120)
    cues: list[Cue] = Field(default_factory=list, max_length=3000)

    @model_validator(mode="after")
    def valid_range(self):
        if not 0 < self.end - self.start <= 180:
            raise ValueError("숏폼 길이는 0초 초과, 180초 이하여야 합니다.")
        if self.height * 9 != self.width * 16:
            raise ValueError("출력 화면은 9:16이어야 합니다.")
        return self


def clip_cues(cues: list[Cue], start: float, end: float) -> list[Cue]:
    """Intersect source cues with clip bounds and rebase onto output timeline."""
    return [
        Cue(start=max(c.start, start) - start, end=min(c.end, end) - start, text=c.text)
        for c in sorted(cues, key=lambda c: c.start)
        if c.end > start and c.start < end
    ]


def suggest_clips(
    cues: list[Cue], *, duration: float, target: float = 45, limit: int = 5
) -> list[dict]:
    """Deterministic transcript windows, not an AI popularity score.

    Never splits a sentence. Selected windows do not overlap. Works offline.
    """
    ordered = sorted(cues, key=lambda c: c.start)
    result: list[dict] = []
    cursor = 0.0
    for i, cue in enumerate(ordered):
        if cue.start < cursor or cue.end > duration:
            continue
        window = []
        for following in ordered[i:]:
            if following.end > duration or following.end - cue.start > min(target, 180):
                break
            window.append(following)
        if not window:
            continue
        end = window[-1].end
        if end - cue.start < min(5, duration):
            continue
        result.append(
            {
                "start": cue.start,
                "end": end,
                "title": cue.text[:100],
                "reason": "문장 경계를 유지한 대본 구간",
            }
        )
        cursor = end
        if len(result) >= limit:
            break
    return result
