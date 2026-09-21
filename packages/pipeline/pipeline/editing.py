"""Validated edit decisions. Source media and transcript versions stay immutable."""

from __future__ import annotations

from typing import Literal

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


class TrimSettings(BaseModel):
    """무음 자동 컷의 세기. 기본값은 잰 것이 아니라 정한 것입니다.

    자르는 계산은 `pipeline.trimming`에 있습니다. 여기에는 값만 둡니다
    (그쪽이 이 파일을 읽으므로 반대로 읽으면 순환 참조가 됩니다).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    # 말 앞뒤로 남길 여유. 딱 붙여 자르면 첫 소리가 잘립니다.
    pad: float = Field(default=0.12, ge=0, le=2)
    # 이보다 짧은 침묵은 자르지 않습니다. 숨 쉬는 자리까지 없애면 듣기 나쁩니다.
    min_gap: float = Field(default=0.6, ge=0.05, le=10)
    # 이보다 짧은 토막은 버립니다. 한 프레임짜리 조각이 남지 않게.
    min_keep: float = Field(default=0.4, ge=0.05, le=10)


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
    # 말이 없는 구간을 잘라내고 남은 토막을 이어 붙입니다. 비우면 자르지 않습니다.
    # 자른 뒤에는 시간축이 달라지므로 자막·단어 시각·스티커를 함께 옮깁니다.
    silence: TrimSettings | None = None
    # 세로로 자를 때 얼굴을 따라 중심을 움직입니다. 비우면 `focus_x` 고정입니다.
    # `mode="crop"`에서만 씁니다(`pad`는 화면 전체를 남기므로 자를 것이 없습니다).
    reframe: ReframeSettings | None = None
    # 음성 잡음 제거. FFmpeg 내장 필터라 새 의존성이 없습니다. 비우면 건드리지
    # 않습니다. `strong`은 잡음을 더 깎지만 목소리도 같이 깎일 수 있습니다.
    denoise: Literal["soft", "strong"] | None = None

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
