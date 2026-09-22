"""Validated edit decisions. Source media and transcript versions stay immutable."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeline.subtitle_stickers import Sticker


class Word(BaseModel):
    """자막 안 단어 하나의 시각. 정렬기(whisper)가 준 값이며 노래방·단어별 움직임이 씁니다."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("단어 종료는 시작보다 앞일 수 없습니다.")
        return self


class Cue(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=2000)
    # 단어 시각. 정렬·전사 결과에만 있고 사람이 글자를 고치면 비웁니다(맞지 않으므로).
    # 렌더는 없거나 글자와 맞지 않으면 자막 길이를 고르게 나눠 씁니다.
    words: list[Word] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("자막 종료는 시작보다 뒤여야 합니다.")
        return self


# xfade 전환 가운데 자막·세로 화면에서 무난한 것만 엽니다. FFmpeg에는 50여
# 종이 있지만 화려한 것은 숏폼에서 산만합니다.
TRANSITIONS = (
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "smoothleft",
    "smoothright",
    "circleopen",
    "circleclose",
)


class TransitionSettings(BaseModel):
    """이어 붙인 자리에 넣을 전환. 비우면 딱 붙입니다(지금까지와 같음)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: Literal[TRANSITIONS] = "fade"  # type: ignore[valid-type]
    # 겹치는 길이. 길면 부드럽지만 그만큼 영상이 짧아지고 말이 겹칩니다.
    seconds: float = Field(default=0.25, ge=0.05, le=2)


class ReframeSettings(BaseModel):
    """자동 리프레이밍의 세기. 기본값은 잰 것이 아니라 정한 것입니다.

    경로를 만드는 계산은 `pipeline.reframe`에 있습니다(그쪽이 이 파일을
    읽으므로 반대로 읽으면 순환 참조가 됩니다).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # 이보다 작게 움직이면 화면을 움직이지 않습니다(화면 폭 대비 비율).
    # 고개만 까딱일 때 화면이 따라 흔들리지 않게 합니다.
    deadzone: float = Field(default=0.06, ge=0, le=0.5)
    # 초당 따라갈 수 있는 최대 거리(화면 폭 대비 비율). 크면 홱 돌고 작으면 놓칩니다.
    max_speed: float = Field(default=0.25, ge=0.01, le=2)


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
    # 자막 모양은 템플릿(pipeline.subtitle_templates)이 정합니다. 이름만 두고 실제
    # 확인은 렌더와 API가 합니다(순환 참조를 피합니다). 글자 크기는 비우면 템플릿
    # 값이고, 적으면 그 값이 템플릿보다 우선합니다.
    subtitle_template: str = Field(default="default", pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    font_size: int | None = Field(default=None, ge=20, le=120)
    # 자막 움직임(pipeline.subtitle_motion.ANIMATION_LABELS의 이름). 비우면 템플릿 값,
    # 적으면 그 값이 템플릿보다 우선합니다. `none`이면 움직임을 뺍니다.
    subtitle_animation: str | None = Field(default=None, pattern=r"^[a-z][a-z-]{0,19}$")
    # 모션 프리셋 이름(pipeline.subtitle_presets). 움직임보다 먼저 쓰며, 비우면 템플릿
    # 값입니다. 빈 문자열이면 템플릿의 프리셋을 떼고 `subtitle_animation`을 씁니다.
    subtitle_preset: str | None = Field(default=None, pattern=r"^$|^[a-z][a-z0-9-]{1,39}$")
    # 자막을 끊는 방식(pipeline.subtitles.PACING_LABELS). 비우면 서버 설정 그대로이고,
    # `shortform`이면 말한 시각(Cue.words)에 맞춰 한 줄로 짧게 끊습니다.
    subtitle_pacing: str | None = Field(default=None, pattern=r"^(broadcast|shortform)$")
    cues: list[Cue] = Field(default_factory=list, max_length=3000)
    # 스티커(화살표·반짝이·말풍선·PNG). 시각은 자막과 같은 원본 시간축이며 구간에 맞춰 옮깁니다.
    stickers: list[Sticker] = Field(default_factory=list, max_length=20)
    # 세로로 자를 때 얼굴을 따라 중심을 움직입니다. 비우면 `focus_x` 고정입니다.
    # `mode="crop"`에서만 씁니다(`pad`는 화면 전체를 남기므로 자를 것이 없습니다).
    reframe: ReframeSettings | None = None
    # 음성 잡음 제거. FFmpeg 내장 필터라 새 의존성이 없습니다. 비우면 건드리지
    # 않습니다. `strong`은 잡음을 더 깎지만 목소리도 같이 깎일 수 있습니다.
    denoise: Literal["soft", "strong"] | None = None
    # 이어 붙인 자리의 전환. 비우면 딱 붙입니다. 전환을 넣으면 토막이 서로
    # 겹치므로 영상이 (토막 수 - 1) × seconds 만큼 짧아집니다.
    transition: TransitionSettings | None = None
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
        Cue(
            start=max(c.start, start) - start,
            end=min(c.end, end) - start,
            text=c.text,
            words=_clip_words(c.words, start, end),
        )
        for c in sorted(cues, key=lambda c: c.start)
        if c.end > start and c.start < end
    ]


def _clip_words(words: list[Word] | None, start: float, end: float) -> list[Word] | None:
    """단어 시각을 구간에 맞춰 옮깁니다. 구간 밖 단어가 있으면 글자와 맞지 않으므로 비웁니다."""
    if not words:
        return None
    if any(w.end < start or w.start > end for w in words):
        return None
    return [
        Word(
            start=max(0.0, w.start - start),
            end=max(0.0, min(w.end, end) - start),
            text=w.text,
        )
        for w in words
    ]


def concat_cues(cues: list[Cue], segments: list[TimeSpan]) -> list[Cue]:
    """이어 붙인 시간축으로 자막을 옮깁니다.

    구간에 걸친 자막은 그 구간 안쪽만 남습니다. 배속을 걸면 그만큼 짧아집니다.
    한 프레임(0.04초)보다 짧아진 조각은 화면에 보이지 않으므로 버립니다.

    **단어 시각도 같이 옮깁니다.** `clip_cues`가 살려 둔 것을 여기서 버리면
    노래방·단어별 등장이 말과 어긋납니다.
    """
    moved: list[Cue] = []
    offset = 0.0
    for span in segments:
        for cue in clip_cues(cues, span.start, span.end):
            start, end = offset + cue.start / span.speed, offset + cue.end / span.speed
            if end - start >= 0.04:
                moved.append(
                    Cue(
                        start=start,
                        end=end,
                        text=cue.text,
                        words=_shift_words(cue.words, offset, span.speed),
                    )
                )
        offset += span.output_seconds
    return moved


def _shift_words(words: list[Word] | None, offset: float, speed: float) -> list[Word] | None:
    """단어 시각을 이어 붙인 시간축으로. 배속을 걸면 그만큼 당겨집니다."""
    if not words:
        return None
    return [
        Word(start=offset + w.start / speed, end=offset + w.end / speed, text=w.text) for w in words
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
