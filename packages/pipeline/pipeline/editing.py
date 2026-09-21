"""Validated edit decisions. Source media and transcript versions stay immutable."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

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


class TimeSpan(BaseModel):
    """이어 붙일 구간 하나. `speed`는 재생 속도입니다(2.0이면 두 배 빠르게)."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    speed: float = Field(default=1.0, ge=0.5, le=4.0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("구간 끝은 시작보다 뒤여야 합니다.")
        return self

    @property
    def output_seconds(self) -> float:
        """이 구간이 결과에서 차지하는 시간."""
        return (self.end - self.start) / self.speed


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
    font_size: int = Field(default=64, ge=20, le=120)
    cues: list[Cue] = Field(default_factory=list, max_length=3000)
    # 이어 붙일 구간들. 비어 있으면 지금까지처럼 start~end 한 구간입니다.
    segments: list[TimeSpan] = Field(default_factory=list, max_length=50)
    fade_in: float = Field(default=0.0, ge=0, le=5)
    fade_out: float = Field(default=0.0, ge=0, le=5)
    # 배경음악으로 쓸 원본. 그 원본의 소리만 가져다 깝니다.
    music_asset_id: UUID | None = None
    music_gain_db: float = Field(default=-18.0, ge=-60, le=0)
    # 말할 때 배경음악 음량을 자동으로 낮춥니다.
    music_duck: bool = True

    @property
    def output_seconds(self) -> float:
        """결과 영상의 길이. 구간을 골랐으면 그것들을 이어 붙인 길이입니다."""
        if self.segments:
            return sum(span.output_seconds for span in self.segments)
        return self.end - self.start

    @property
    def spans(self) -> list[TimeSpan]:
        """실제로 쓸 구간. 고르지 않았으면 start~end 하나입니다."""
        return self.segments or [TimeSpan(start=self.start, end=self.end)]

    @model_validator(mode="after")
    def valid_range(self):
        if self.height * 9 != self.width * 16:
            raise ValueError("출력 화면은 9:16이어야 합니다.")
        previous: float | None = None
        for span in self.segments:
            if span.start < self.start or span.end > self.end:
                raise ValueError("이어 붙일 구간은 시작~끝 안에 있어야 합니다.")
            if previous is not None and span.start < previous:
                raise ValueError("이어 붙일 구간은 시간 순서대로, 겹치지 않게 주세요.")
            previous = span.end
        if not 0 < self.output_seconds <= 180:
            raise ValueError("숏폼 길이는 0초 초과, 180초 이하여야 합니다.")
        if self.fade_in + self.fade_out > self.output_seconds:
            raise ValueError("페이드 길이가 결과 길이를 넘습니다.")
        return self


def clip_cues(cues: list[Cue], start: float, end: float) -> list[Cue]:
    """Intersect source cues with clip bounds and rebase onto output timeline."""
    return [
        Cue(start=max(c.start, start) - start, end=min(c.end, end) - start, text=c.text)
        for c in sorted(cues, key=lambda c: c.start)
        if c.end > start and c.start < end
    ]


def concat_cues(cues: list[Cue], segments: list[TimeSpan]) -> list[Cue]:
    """이어 붙인 시간축으로 자막을 옮깁니다.

    구간에 걸친 자막은 그 구간 안쪽만 남습니다. 배속을 걸면 그만큼 짧아집니다.
    한 프레임(0.04초)보다 짧아진 조각은 화면에 보이지 않으므로 버립니다.
    """
    moved: list[Cue] = []
    offset = 0.0
    for span in segments:
        for cue in clip_cues(cues, span.start, span.end):
            start, end = offset + cue.start / span.speed, offset + cue.end / span.speed
            if end - start >= 0.04:
                moved.append(Cue(start=start, end=end, text=cue.text))
        offset += span.output_seconds
    return moved


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
