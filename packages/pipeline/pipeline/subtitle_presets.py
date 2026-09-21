"""모션 프리셋: 여러 동작을 겹쳐 만든 자막 움직임 한 벌.

`subtitle_motion`의 움직임 12종은 종류마다 코드가 정해져 있습니다. 프리셋은 그 대신
**동작(step) 목록을 데이터로** 적어 둔 것이라, 코드를 고치지 않고 JSON만 써서 새 움직임을
만들 수 있습니다. 시중의 "모션 프리셋 팩"처럼 한 벌씩 골라 쓰는 방식입니다.

동작 하나는 "무엇을(kind) 언제(phase·ms) 얼마나(amount) 어느 쪽으로(direction)"입니다.
등장(in)·사라짐(out)·계속(hold) 세 구간이 있고, 같은 프리셋 안에서 여러 동작을 겹칩니다.
예를 들어 "블러+줌"은 `blur`(in) + `scale`(in) 두 동작입니다.

libass가 실제로 그릴 수 있는 명령만 만듭니다.

- 크기 `\\fscx`/`\\fscy`, 평면 회전 `\\frz`, 3D 회전 `\\frx`/`\\fry`, 기울임 `\\fax`/`\\fay`
- 투명도 `\\alpha`, 번짐 `\\blur`, 색 `\\1c`, 잘라내기 `\\clip`
- 이동 `\\move`(이벤트당 한 번만), 값 변화 `\\t(시작,끝,가속,명령)`

`\\pos`는 `\\t`로 바꿀 수 없어 **반복해서 떠다니는 움직임**은 `\\org`(회전 중심)을 글자에서
멀리 두고 `\\frz`를 아주 조금씩 흔드는 방법을 씁니다. 반지름이 크면 각도가 작아도 호가 거의
직선이라 위아래로 떠는 것처럼 보이고, 글자 기울기는 눈에 띄지 않습니다.

조각별(글자·단어) 동작은 `subtitle_motion`의 토큰 나누기를 그대로 씁니다.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.subtitle_motion import run_slots, state_before

__all__ = [
    "BUILTIN_PRESETS",
    "PACK_LABELS",
    "MotionPreset",
    "MotionStep",
    "PresetBox",
    "load_preset",
    "preset_labels",
    "preset_names",
    "preset_offset",
    "preset_runs",
    "preset_tags",
    "presets_by_pack",
    "register_preset",
    "resolve_preset",
    "user_presets_dir",
]

PRESET_NAME = r"^[a-z][a-z0-9-]{1,39}$"

StepKind = Literal[
    "fade",
    "scale",
    "move",
    "spin",
    "flip",
    "blur",
    "shear",
    "wipe",
    "flash",
    "shake",
    "float",
    "breathe",
    "glow",
    "reveal",
    "wave",
]

STEP_LABELS: dict[str, str] = {
    "fade": "투명도",
    "scale": "크기",
    "move": "이동",
    "spin": "평면 회전",
    "flip": "3D 회전",
    "blur": "번짐",
    "shear": "기울임",
    "wipe": "펼치기(잘라내기)",
    "flash": "색 번쩍",
    "shake": "계속 흔들림",
    "float": "계속 떠다님",
    "breathe": "계속 커졌다 작아짐",
    "glow": "계속 번쩍임",
    "reveal": "조각별 등장",
    "wave": "조각별 물결",
}

Phase = Literal["in", "out", "hold"]
Ease = Literal["linear", "in", "out", "in-out"]
Direction = Literal["none", "up", "down", "left", "right", "both", "vertical", "horizontal"]
Unit = Literal["char", "word"]
Reveal = Literal["type", "pop", "karaoke", "glitch"]
Pack = Literal["basic", "short", "user"]

PACK_LABELS: dict[str, str] = {
    "basic": "기본 팩",
    "short": "숏폼 팩",
    "user": "내 프리셋",
}

# 계속되는 움직임이 만드는 `\t` 명령 수의 한계. 자막이 길면 주기를 늘려 맞춥니다.
_MAX_SEGMENTS = 80
# 줄바꿈 위치는 표시 규칙이 미리 정하므로 크기가 변해도 libass가 다시 나누지 않게 합니다.
_NO_WRAP = "\\q2"
# `\org` 궤도 반지름(px). 크면 같은 거리를 더 작은 각도로 움직여 기울기가 덜 보입니다.
_ORBIT_RADIUS = 4000.0
# `\t`의 가속 값. 1이 일정한 속도입니다.
_ACCEL = {"linear": 1.0, "in": 1.8, "out": 0.55}


def _i(value: float) -> int:
    return int(round(value))


class MotionStep(BaseModel):
    """동작 하나. `kind`마다 쓰는 값이 다릅니다(쓰지 않는 값은 무시)."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    kind: StepKind
    # in=등장(앞에서부터), out=사라짐(끝에서 거꾸로), hold=자막이 있는 내내
    phase: Phase = "in"
    # 이 동작에 쓰는 시간(ms). 등장·사라짐은 길이, 계속은 한 주기입니다.
    ms: int = Field(default=320, ge=20, le=6000)
    # 크기(%), 각도(도), 거리(px), 번짐, 잘라낼 비율 등 `kind`에 따른 양입니다.
    amount: float = Field(default=0, ge=-4000, le=4000)
    direction: Direction = "none"
    ease: Ease = "linear"
    # 제자리를 지나 살짝 넘어갔다 돌아오는 정도(%). 크기·회전에서 씁니다.
    overshoot: float = Field(default=0, ge=0, le=80)
    # 시작을 늦춥니다(ms). 여러 동작을 차례로 이을 때 씁니다.
    delay: int = Field(default=0, ge=0, le=6000)
    # 조각별 동작의 단위와 조각 사이 간격(ms).
    unit: Unit = "char"
    stagger: int = Field(default=60, ge=0, le=1000)
    reveal: Reveal = "type"

    @model_validator(mode="after")
    def _check(self) -> MotionStep:
        if self.kind in ("shake", "float", "breathe", "glow", "wave") and self.phase != "hold":
            raise ValueError(f"{self.kind}은(는) phase=hold로만 쓸 수 있습니다.")
        if self.kind in ("reveal",) and self.phase != "in":
            raise ValueError("reveal은 phase=in으로만 쓸 수 있습니다.")
        if self.kind in ("move", "wipe", "float") and self.direction == "none":
            raise ValueError(f"{self.kind}에는 direction이 필요합니다.")
        return self

    @property
    def per_run(self) -> bool:
        """글자·단어마다 붙는 동작인지."""
        return self.kind in ("reveal", "wave")


class MotionPreset(BaseModel):
    """동작 여러 개를 묶은 움직임 한 벌. JSON으로 저장·복원할 수 있습니다."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    name: str = Field(pattern=PRESET_NAME)
    label: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    pack: Pack = "user"
    steps: list[MotionStep] = Field(min_length=1, max_length=8)

    @field_validator("steps")
    @classmethod
    def _one_move(cls, steps: list[MotionStep]) -> list[MotionStep]:
        # ASS는 이벤트 하나에 `\move`를 한 번만 씁니다.
        if sum(1 for step in steps if step.kind == "move") > 1:
            raise ValueError("이동(move) 동작은 프리셋 하나에 한 번만 쓸 수 있습니다.")
        if sum(1 for step in steps if step.per_run) > 1:
            raise ValueError("조각별 동작(reveal·wave)은 프리셋 하나에 한 번만 쓸 수 있습니다.")
        return steps

    @property
    def moves(self) -> bool:
        """`\\move`로 자리를 정하는지(그러면 `\\pos`를 쓰지 않습니다)."""
        return any(step.kind == "move" for step in self.steps)

    @property
    def run_step(self) -> MotionStep | None:
        return next((step for step in self.steps if step.per_run), None)

    @property
    def needs_block(self) -> bool:
        return any(step.kind == "wipe" for step in self.steps)

    @property
    def summary(self) -> str:
        return " + ".join(f"{STEP_LABELS[s.kind]}({s.phase})" for s in self.steps)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2) + "\n"


class PresetBox(BaseModel):
    """글자가 차지하는 사각형(펼치기가 씁니다). 화면 좌표 px."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(1.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


# ---------------------------------------------------------------- 명령 만들기


def _accel(ease: Ease) -> float:
    return _ACCEL.get(ease, 1.0)


def _change(t1: int, t2: int, tags: str, ease: Ease = "linear") -> list[str]:
    """`\\t` 한 구간. in-out은 절반씩 가속·감속 두 구간으로 나눕니다."""
    if not tags or t2 <= t1:
        return []
    if ease == "in-out":
        mid = (t1 + t2) // 2
        if mid <= t1:
            return [f"\\t({t1},{t2},{tags})"]
        return [
            f"\\t({t1},{mid},{_ACCEL['in']:g},{tags})",
            f"\\t({mid},{t2},{_ACCEL['out']:g},{tags})",
        ]
    accel = _accel(ease)
    body = f"{accel:g}," if abs(accel - 1.0) > 1e-9 else ""
    return [f"\\t({t1},{t2},{body}{tags})"]


def _scale_tag(value: float, direction: Direction) -> str:
    if direction == "horizontal":
        return f"\\fscx{value:g}"
    if direction == "vertical":
        return f"\\fscy{value:g}"
    return f"\\fscx{value:g}\\fscy{value:g}"


def _alpha_tag(value: int) -> str:
    return f"\\alpha&H{max(0, min(255, value)):02X}&"


def _window(step: MotionStep, duration_ms: int, hold_start: int) -> tuple[int, int]:
    """동작이 도는 구간 (시작, 끝) ms. 이벤트 시작 기준입니다."""
    if step.phase == "in":
        start = min(step.delay, duration_ms)
        return start, min(start + step.ms, duration_ms)
    if step.phase == "out":
        end = max(0, duration_ms - step.delay)
        return max(0, end - step.ms), end
    return min(hold_start, duration_ms), duration_ms


def _segment_limit(ease: Ease, limit: int) -> int:
    """만들 수 있는 반 주기 수. in-out은 한 주기가 `\\t` 두 개라 절반만 넣습니다."""
    return max(1, limit // 2) if ease == "in-out" else limit


def _half_period(step: MotionStep, span: int) -> int:
    """계속되는 움직임의 반 주기(ms). 명령 수가 한계를 넘지 않게 늘립니다."""
    limit = _segment_limit(step.ease, _MAX_SEGMENTS)
    half = max(40, step.ms // 2)
    if span / half > limit:
        half = -(-span // limit)
    return half


def _oscillate(start: int, end: int, half: int, first: str, second: str, ease: Ease) -> list[str]:
    """두 상태를 번갈아 오가는 `\\t` 목록."""
    out: list[str] = []
    at, flip = start, True
    while at < end:
        out += _change(at, min(at + half, end), first if flip else second, ease)
        at += half
        flip = not flip
    return out


def _orbit(anchor: tuple[float, float], direction: Direction) -> tuple[str, float]:
    """(`\\org` 명령, 1px 움직이는 데 필요한 각도). 반복 이동을 회전으로 흉내 냅니다."""
    x, y = anchor
    if direction in ("left", "right", "horizontal"):
        origin = f"\\org({x:.0f},{y + _ORBIT_RADIUS:.0f})"
    else:
        origin = f"\\org({x + _ORBIT_RADIUS:.0f},{y:.0f})"
    return origin, math.degrees(1.0 / _ORBIT_RADIUS)


def _move_offset(direction: Direction, amount: float, phase: Phase) -> tuple[float, float]:
    """(dx, dy) px. 등장은 그 방향에서 들어오고, 사라짐은 그 방향으로 나갑니다."""
    sign = -1.0 if phase == "in" else 1.0
    if direction == "up":
        return 0.0, -amount * sign
    if direction == "down":
        return 0.0, amount * sign
    if direction == "left":
        return -amount * sign, 0.0
    if direction == "right":
        return amount * sign, 0.0
    return 0.0, 0.0


def _wipe_rects(
    step: MotionStep, box: PresetBox, play: tuple[int, int]
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """(접힌 사각형, 펼친 사각형). 외곽선이 잘리지 않게 여유를 둡니다."""
    pad = 24.0
    width, height = play
    left, right = box.left - pad, box.right + pad
    top, bottom = box.top - pad, box.bottom + pad
    full = (0, _i(top), width, _i(bottom))
    if step.direction in ("left", "right", "horizontal", "both"):
        full = (_i(left), 0, _i(right), height)
        if step.direction == "right":
            closed = (_i(left), 0, _i(left), height)
        elif step.direction == "left":
            closed = (_i(right), 0, _i(right), height)
        else:
            mid = (left + right) / 2
            closed = (_i(mid), 0, _i(mid), height)
    elif step.direction == "up":
        closed = (0, _i(bottom), width, _i(bottom))
    elif step.direction == "down":
        closed = (0, _i(top), width, _i(top))
    else:
        mid = (top + bottom) / 2
        closed = (0, _i(mid), width, _i(mid))
    return closed, full


def _clip_tag(rect: tuple[int, int, int, int]) -> str:
    return "\\clip({},{},{},{})".format(*rect)


_SHAPING = frozenset({"scale", "spin", "flip", "shear", "breathe", "wave", "float", "shake"})


def preset_tags(
    preset: MotionPreset,
    *,
    duration_ms: int,
    anchor: tuple[float, float] | None,
    angle: float = 0.0,
    glow: float = 0.0,
    base_tag: str = "",
    box: PresetBox | None = None,
    play_size: tuple[int, int] = (1080, 1920),
) -> str:
    """이벤트 전체에 붙는 명령(중괄호 없이). 길이가 없으면 빈 문자열입니다.

    `anchor`는 글자가 정렬되는 점으로 이동·떠다님이 씁니다. `angle`·`glow`는 템플릿의
    기울기·번짐으로, 회전·번짐 동작이 그 값을 기준으로 돌아옵니다. `base_tag`는 색
    번쩍이 돌아갈 색 명령, `box`는 펼치기가 쓸 글자 사각형입니다.
    """
    if duration_ms <= 0:
        return ""
    statics: list[str] = []
    move = ""
    changes: list[tuple[int, str]] = []
    hold_start = 0
    for step in preset.steps:
        if step.phase == "in" and not step.per_run:
            hold_start = max(hold_start, min(step.delay + step.ms, duration_ms))
    if any(step.kind in _SHAPING for step in preset.steps):
        statics.append(_NO_WRAP)

    def add(at: int, tags: list[str]) -> None:
        changes.extend((at, tag) for tag in tags)

    for step in preset.steps:
        if step.per_run:
            continue
        start, end = _window(step, duration_ms, hold_start)
        if end <= start:
            continue
        kind, ease = step.kind, step.ease
        if kind == "fade":
            if step.phase == "in":
                statics.append(_alpha_tag(255))
                add(start, _change(start, end, _alpha_tag(0), ease))
            else:
                add(start, _change(start, end, _alpha_tag(255), ease))
        elif kind == "scale":
            begin = step.amount or 40.0
            if step.phase == "in":
                statics.append(_scale_tag(begin, step.direction))
                if step.overshoot:
                    peak = start + _i((end - start) * 0.62)
                    add(
                        start,
                        _change(
                            start, peak, _scale_tag(100 + step.overshoot, step.direction), ease
                        ),
                    )
                    add(peak, _change(peak, end, _scale_tag(100, step.direction), "out"))
                else:
                    add(start, _change(start, end, _scale_tag(100, step.direction), ease))
            else:
                add(start, _change(start, end, _scale_tag(begin, step.direction), ease))
        elif kind == "spin":
            if step.phase == "in":
                statics.append(f"\\frz{angle + step.amount:g}")
                if step.overshoot:
                    # 넘어감(%)을 도로 바꿉니다. 회전은 조금만 지나쳐도 눈에 띕니다.
                    peak = start + _i((end - start) * 0.72)
                    past = step.overshoot * 0.15 * (-1 if step.amount >= 0 else 1)
                    add(start, _change(start, peak, f"\\frz{angle + past:g}", ease))
                    add(peak, _change(peak, end, f"\\frz{angle:g}", "out"))
                else:
                    add(start, _change(start, end, f"\\frz{angle:g}", ease))
            else:
                add(start, _change(start, end, f"\\frz{angle + step.amount:g}", ease))
        elif kind == "flip":
            axis = "frx" if step.direction in ("up", "down", "vertical") else "fry"
            if step.phase == "in":
                statics.append(f"\\{axis}{step.amount:g}")
                add(start, _change(start, end, f"\\{axis}0", ease))
            else:
                add(start, _change(start, end, f"\\{axis}{step.amount:g}", ease))
        elif kind == "blur":
            if step.phase == "in":
                statics.append(f"\\blur{step.amount:g}")
                add(start, _change(start, end, f"\\blur{glow:g}", ease))
            else:
                add(start, _change(start, end, f"\\blur{step.amount:g}", ease))
        elif kind == "shear":
            axis = "fay" if step.direction in ("up", "down", "vertical") else "fax"
            if step.phase == "in":
                statics.append(f"\\{axis}{step.amount:g}")
                add(start, _change(start, end, f"\\{axis}0", ease))
            else:
                add(start, _change(start, end, f"\\{axis}{step.amount:g}", ease))
        elif kind == "flash":
            if base_tag:
                statics.append("\\1c&HFFFFFF&")
                add(start, _change(start, end, base_tag, ease))
        elif kind == "move":
            if anchor is None or move:
                continue
            x, y = anchor
            dx, dy = _move_offset(step.direction, step.amount or 70.0, step.phase)
            if step.phase == "in":
                move = f"\\move({x + dx:.0f},{y + dy:.0f},{x:.0f},{y:.0f},{start},{end})"
            else:
                move = f"\\move({x:.0f},{y:.0f},{x + dx:.0f},{y + dy:.0f},{start},{end})"
        elif kind == "wipe":
            if box is None:
                continue
            closed, full = _wipe_rects(step, box, play_size)
            if step.phase == "in":
                statics.append(_clip_tag(closed))
                add(start, _change(start, end, _clip_tag(full), ease))
            else:
                add(start, _change(start, end, _clip_tag(closed), ease))
        elif kind in ("shake", "float"):
            half = _half_period(step, end - start)
            if step.direction in ("none",) and kind == "shake":
                first, second = f"\\frz{angle + step.amount:g}", f"\\frz{angle - step.amount:g}"
                statics.append(first)
            else:
                if anchor is None:
                    continue
                origin, per_px = _orbit(anchor, step.direction)
                statics.append(origin)
                swing = per_px * (step.amount or 10.0)
                first, second = f"\\frz{angle + swing:g}", f"\\frz{angle - swing:g}"
                statics.append(first)
            add(start, _oscillate(start, end, half, second, first, ease))
        elif kind == "breathe":
            half = _half_period(step, end - start)
            up = _scale_tag(100 + (step.amount or 6), step.direction)
            add(start, _oscillate(start, end, half, up, _scale_tag(100, step.direction), ease))
        elif kind == "glow":
            half = _half_period(step, end - start)
            add(
                start,
                _oscillate(
                    start,
                    end,
                    half,
                    f"\\blur{glow + (step.amount or 4):g}",
                    f"\\blur{glow:g}",
                    ease,
                ),
            )
    changes.sort(key=lambda item: item[0])
    return "".join(statics) + move + "".join(tag for _, tag in changes)


def preset_offset(preset: MotionPreset) -> tuple[int, int] | None:
    """`\\move`로 움직이는 프리셋의 (시작 세로 오프셋 px, 도착까지 ms). 아니면 None.

    그라데이션 띠(`\\clip`)가 글자를 따라가는 데 씁니다. 가로 이동은 띠를 가로로 자르지
    않는 한 티가 나지 않아 세로만 봅니다.
    """
    for step in preset.steps:
        if step.kind != "move":
            continue
        _, dy = _move_offset(step.direction, step.amount or 70.0, step.phase)
        if step.phase != "in":
            return None
        return _i(dy), min(step.delay + step.ms, 100000)
    return None


# ---------------------------------------------------------------- 조각별 명령

# 조각 하나가 만드는 `\t` 수의 한계. 글자가 많은 자막에서 파일이 커지지 않게 합니다.
_MAX_RUN_SEGMENTS = 12
_REVEAL_KINDS = {"type": "typewriter", "pop": "word-pop", "karaoke": "karaoke"}


def preset_runs(
    preset: MotionPreset,
    ass_text: str,
    *,
    duration_ms: int,
    prefix: str = "",
    hollow: bool = False,
    accent: str = "",
    base: str = "",
    word_times: list[tuple[int, int]] | None = None,
) -> str:
    """글자·단어마다 붙는 동작을 본문에 넣습니다. 없으면 그대로 돌려줍니다."""
    from pipeline.subtitle_motion import animate_runs

    step = preset.run_step
    if step is None or duration_ms <= 0:
        return ass_text
    if step.kind == "reveal":
        if step.reveal in _REVEAL_KINDS:
            return animate_runs(
                _REVEAL_KINDS[step.reveal],
                ass_text,
                step.stagger,
                duration_ms=duration_ms,
                prefix=prefix,
                hollow=hollow,
                accent=accent,
                base=base,
                word_times=word_times,
            )
        return _glitch_runs(ass_text, step, duration_ms, prefix, hollow)
    return _wave_runs(ass_text, step, duration_ms, prefix)


def _stagger(count: int, step: MotionStep, duration_ms: int) -> int:
    """조각 사이 간격(ms). 자막 길이 안에 다 들어오게 줄입니다."""
    if count <= 1:
        return 0
    return max(1, min(step.stagger, int(duration_ms * 0.7 / count)))


def _glitch_runs(
    ass_text: str, step: MotionStep, duration_ms: int, prefix: str, hollow: bool
) -> str:
    """글자마다 깜빡이며 좌우로 튀었다가 제자리에 놓입니다."""
    items, slots = run_slots(ass_text, step.unit)
    if not slots:
        return ass_text
    gap = _stagger(len(slots), step, duration_ms)
    shift = step.amount or 12.0
    fill = "" if hollow else "\\1a&HFF&"
    lead: dict[int, str] = {}
    for order, index in enumerate(slots):
        at = order * gap
        lead[index] = (
            "{"
            + state_before(items, index, prefix)
            + f"\\3a&HFF&\\4a&HFF&{fill}\\fax{shift / 40:g}"
            + f"\\t({at},{at + 1},\\3a&H00&\\4a&H00&"
            + ("" if hollow else "\\1a&H00&")
            + f"\\fax{-shift / 60:g})"
            + f"\\t({at + 40},{at + 41},\\fax0)"
            + "}"
        )
    return "".join(lead.get(i, "") + token for i, token in enumerate(items))


def _wave_runs(ass_text: str, step: MotionStep, duration_ms: int, prefix: str) -> str:
    """조각마다 시작을 조금씩 늦춰 같은 흔들림을 돌려 물결처럼 보이게 합니다."""
    items, slots = run_slots(ass_text, step.unit)
    if not slots:
        return ass_text
    half = max(60, step.ms // 2)
    span = max(0, duration_ms)
    limit = _segment_limit(step.ease, _MAX_RUN_SEGMENTS)
    if span / half > limit:
        half = -(-span // limit)
    amount = step.amount or 14.0
    if step.direction in ("left", "right", "horizontal"):
        up, down = f"\\frz{amount:g}", f"\\frz{-amount:g}"
    elif step.direction == "both":
        up, down = f"\\fscx{100 + amount:g}\\fscy{100 - amount:g}", "\\fscx100\\fscy100"
    else:
        up, down = f"\\fscy{100 + amount:g}", "\\fscy100"
    gap = max(1, min(step.stagger, half))
    lead: dict[int, str] = {}
    for order, index in enumerate(slots):
        start = (order * gap) % (half * 2)
        tags = state_before(items, index, prefix) + _NO_WRAP
        tags += "".join(_oscillate(start, span, half, up, down, step.ease))
        lead[index] = "{" + tags + "}"
    return "".join(lead.get(i, "") + token for i, token in enumerate(items))


# ---------------------------------------------------------------- 프리셋 모음


def _step(kind: str, **values) -> MotionStep:  # noqa: ANN003
    return MotionStep.model_validate({"kind": kind, **values})


def _preset(
    name: str, label: str, pack: str, *steps: MotionStep, description: str = ""
) -> MotionPreset:
    return MotionPreset(
        name=name, label=label, pack=pack, steps=list(steps), description=description
    )


def _fade(ms: int = 260, **values) -> MotionStep:  # noqa: ANN003
    return _step("fade", ms=ms, **values)


def _scale(amount: float, ms: int = 320, **values) -> MotionStep:  # noqa: ANN003
    return _step("scale", amount=amount, ms=ms, **values)


def _move(direction: str, amount: float = 70, ms: int = 320, **values) -> MotionStep:  # noqa: ANN003
    return _step("move", direction=direction, amount=amount, ms=ms, **values)


def _blur(amount: float = 10, ms: int = 300, **values) -> MotionStep:  # noqa: ANN003
    return _step("blur", amount=amount, ms=ms, **values)


def _spin(amount: float, ms: int = 340, **values) -> MotionStep:  # noqa: ANN003
    return _step("spin", amount=amount, ms=ms, **values)


# 내장 프리셋. 순서가 목록과 미리보기 영상에 그대로 나옵니다. 이름은 영문 슬러그,
# 라벨은 화면에 보이는 한국어입니다. 새 프리셋은 여기에 적거나 JSON으로 넣습니다.
BUILTIN_PRESETS: list[MotionPreset] = [
    # ---------------------------------------------------------------- 기본 팩
    _preset("spin-quarter", "90도 회전", "basic", _spin(90), _fade(200)),
    _preset("center-in", "가운데 등장", "basic", _scale(46, overshoot=10), _fade(180)),
    _preset("squirm", "꾸물꾸물 자막", "basic", _step("wave", phase="hold", ms=620, amount=10)),
    _preset(
        "squiggle",
        "꾸불꾸불 자막",
        "basic",
        _step("wave", phase="hold", ms=520, amount=7, direction="horizontal"),
    ),
    _preset(
        "wriggle",
        "꿈틀꿈틀 자막",
        "basic",
        _step("wave", phase="hold", ms=700, amount=9, direction="both", stagger=90),
    ),
    _preset(
        "hover-high",
        "두둥실 뜨는",
        "basic",
        _step("float", phase="hold", ms=2200, amount=22, direction="vertical", ease="in-out"),
        _fade(320),
    ),
    _preset(
        "hover",
        "둥둥 뜨는",
        "basic",
        _step("float", phase="hold", ms=1500, amount=11, direction="vertical", ease="in-out"),
    ),
    _preset(
        "from-back", "뒤에서 등장", "basic", _scale(175, ms=380), _blur(12, ms=380), _fade(240)
    ),
    _preset("grow-back", "뒤에서 커지기", "basic", _scale(62, ms=620, ease="out"), _fade(300)),
    _preset("thud-back", "뒤에서 통!", "basic", _scale(150, ms=180), _blur(7, ms=180), _fade(120)),
    _preset(
        "half-spin", "반회전 뻑!", "basic", _spin(180, ms=380, overshoot=20), _scale(58, ms=380)
    ),
    _preset("click-soft", "살짝 클릭", "basic", _scale(92, ms=160, overshoot=4), _fade(120)),
    _preset("appear-slow", "서서히 나타남", "basic", _fade(760, ease="out")),
    _preset(
        "swoosh",
        "슈슉 등장",
        "basic",
        _move("right", 160, ms=260, ease="out"),
        _blur(9, ms=220),
        _fade(160),
    ),
    _preset("from-below", "아래 등장", "basic", _move("up", 90, ms=340, ease="out"), _fade(220)),
    _preset("slide-below", "아래 스르륵", "basic", _move("up", 56, ms=560, ease="out"), _fade(420)),
    _preset("jump-out", "튀어나오기", "basic", _scale(28, ms=340, overshoot=24), _fade(140)),
    _preset("push-right", "오른쪽 밀기", "basic", _move("right", 120, ms=320), _fade(200)),
    _preset("pencil-right", "오른쪽 연필", "basic", _step("wipe", direction="right", ms=620)),
    _preset(
        "wave-right",
        "오른쪽 파도",
        "basic",
        _move("right", 70, ms=300, ease="out"),
        _step("wave", phase="hold", ms=640, amount=12, stagger=70),
    ),
    _preset("push-left", "왼쪽 밀기", "basic", _move("left", 120, ms=320), _fade(200)),
    _preset("pencil-left", "왼쪽 연필", "basic", _step("wipe", direction="left", ms=620)),
    _preset(
        "wave-left",
        "왼쪽 파도",
        "basic",
        _move("left", 70, ms=300, ease="out"),
        _step("wave", phase="hold", ms=640, amount=12, stagger=70),
    ),
    _preset("from-above", "위 등장", "basic", _move("down", 90, ms=340, ease="out"), _fade(220)),
    _preset(
        "bob",
        "위아래 둥둥",
        "basic",
        _step("float", phase="hold", ms=1100, amount=14, direction="vertical", ease="in-out"),
    ),
    _preset(
        "sway-slow", "느리게 흔들림", "basic", _step("shake", phase="hold", ms=900, amount=2.5)
    ),
    _preset(
        "sway-fast", "빠르게 흔들림", "basic", _step("shake", phase="hold", ms=320, amount=3.5)
    ),
    _preset(
        "bounce-updown",
        "위아래 통통",
        "basic",
        _step("float", phase="hold", ms=520, amount=24, direction="vertical"),
    ),
    _preset("slide-above", "위 스르륵", "basic", _move("down", 56, ms=560, ease="out"), _fade(420)),
    _preset("light-sweep", "조명 스치는", "basic", _step("flash", ms=420, ease="out"), _fade(200)),
    _preset("chewy-in", "쫀쫀 등장", "basic", _scale(58, ms=420, overshoot=16, ease="in-out")),
    _preset(
        "crumple",
        "쭈글 자막",
        "basic",
        _step("shear", amount=0.22, ms=260),
        _step("wave", phase="hold", ms=520, amount=8, direction="both", stagger=80),
    ),
    _preset("slam-click", "쾅! 클릭", "basic", _scale(155, ms=140), _blur(6, ms=140), _fade(90)),
    _preset(
        "tension-click", "텐션 클릭", "basic", _scale(68, ms=300, overshoot=26), _spin(7, ms=300)
    ),
    _preset(
        "thud-click",
        "퉁 클릭",
        "basic",
        _scale(118, ms=200, overshoot=3),
        _move("down", 26, ms=200),
    ),
    _preset(
        "surf", "파도 타는", "basic", _step("wave", phase="hold", ms=760, amount=18, stagger=70)
    ),
    _preset(
        "drop-in",
        "뚝 떨어짐",
        "basic",
        _move("down", 130, ms=380, ease="in"),
        _scale(112, ms=420, overshoot=0),
    ),
    _preset(
        "sparkle-in",
        "반짝 등장",
        "basic",
        _fade(240),
        _step("glow", phase="hold", ms=900, amount=5),
    ),
    _preset("typewriter", "타자기", "basic", _step("reveal", reveal="type", stagger=70)),
    _preset(
        "word-in", "단어별 등장", "basic", _step("reveal", reveal="pop", stagger=200, unit="word")
    ),
    _preset("karaoke", "노래방 강조", "basic", _step("reveal", reveal="karaoke", unit="word")),
    # ---------------------------------------------------------------- 숏폼 팩
    _preset(
        "title-in-1", "타이틀 등장1", "short", _step("wipe", direction="both", ms=520), _fade(240)
    ),
    _preset(
        "title-in-2", "타이틀 등장2", "short", _scale(0, ms=420, direction="vertical"), _fade(200)
    ),
    _preset(
        "title-in-3",
        "타이틀 등장3",
        "short",
        _spin(9, ms=380),
        _scale(132, ms=380),
        _blur(10, ms=320),
    ),
    _preset(
        "light-blink",
        "조명 반짝",
        "short",
        _step("flash", ms=220),
        _step("glow", phase="hold", ms=700, amount=6),
    ),
    _preset(
        "light-slide",
        "조명+스르륵 등장",
        "short",
        _step("flash", ms=320),
        _move("up", 60, ms=420, ease="out"),
    ),
    _preset(
        "wiggle-left",
        "왼쪽 구불구불",
        "short",
        _move("left", 90, ms=300, ease="out"),
        _step("wave", phase="hold", ms=520, amount=7, direction="horizontal"),
    ),
    _preset(
        "unfold-left", "왼쪽 펼치기", "short", _step("wipe", direction="left", ms=460), _fade(200)
    ),
    _preset(
        "push-to-left",
        "왼쪽으로 밀기",
        "short",
        _fade(160),
        _step("move", phase="out", direction="left", amount=140, ms=300),
    ),
    _preset(
        "sticker-left",
        "왼쪽 스티커",
        "short",
        _spin(-12, ms=300, overshoot=10),
        _scale(44, ms=300, overshoot=12),
        _move("left", 40, ms=300),
    ),
    _preset(
        "sticker-left-back",
        "왼쪽 스티커 뒤",
        "short",
        _spin(-12, ms=300, overshoot=10),
        _scale(44, ms=300, overshoot=12),
        _step("scale", phase="out", amount=44, ms=260),
        _step("fade", phase="out", ms=260),
    ),
    _preset(
        "wiggle-right",
        "오른쪽 구불구불",
        "short",
        _move("right", 90, ms=300, ease="out"),
        _step("wave", phase="hold", ms=520, amount=7, direction="horizontal"),
    ),
    _preset(
        "unfold-right",
        "오른쪽 펼치기",
        "short",
        _step("wipe", direction="right", ms=460),
        _fade(200),
    ),
    _preset(
        "push-to-right",
        "오른쪽으로 밀기",
        "short",
        _fade(160),
        _step("move", phase="out", direction="right", amount=140, ms=300),
    ),
    _preset(
        "sticker-right",
        "오른쪽 스티커",
        "short",
        _spin(12, ms=300, overshoot=10),
        _scale(44, ms=300, overshoot=12),
        _move("right", 40, ms=300),
    ),
    _preset(
        "sticker-right-back",
        "오른쪽 스티커 뒤",
        "short",
        _spin(12, ms=300, overshoot=10),
        _scale(44, ms=300, overshoot=12),
        _step("scale", phase="out", amount=44, ms=260),
        _step("fade", phase="out", ms=260),
    ),
    _preset(
        "spin-3d",
        "3D 회전",
        "short",
        _step("flip", amount=92, direction="horizontal", ms=420),
        _fade(220),
    ),
    _preset("unfold-center", "가운데 펼치기", "short", _step("wipe", direction="both", ms=440)),
    _preset(
        "stamp",
        "팩 꽂기",
        "short",
        _step("flip", amount=72, direction="vertical", ms=240),
        _scale(134, ms=240),
        _fade(140),
    ),
    _preset("nod", "까딱까딱", "short", _step("shake", phase="hold", ms=620, amount=4)),
    _preset(
        "glitch-down",
        "글리치 아래",
        "short",
        _step("reveal", reveal="glitch", amount=14, stagger=45),
    ),
    _preset("in-down", "아래 in", "short", _move("up", 64, ms=380, ease="out"), _fade(240)),
    _preset(
        "in-down-fast", "빠르게 아래 in", "short", _move("up", 64, ms=170, ease="out"), _fade(120)
    ),
    _preset(
        "wave-down",
        "아래 파도",
        "short",
        _move("up", 50, ms=300, ease="out"),
        _step("wave", phase="hold", ms=700, amount=13, stagger=60),
    ),
    _preset("fill-up", "아래 차오르기", "short", _step("wipe", direction="up", ms=520)),
    _preset(
        "glitch-up",
        "글리치 위",
        "short",
        _step("reveal", reveal="glitch", amount=14, stagger=45),
        _move("down", 30, ms=220),
    ),
    _preset("in-up", "위 in", "short", _move("down", 64, ms=380, ease="out"), _fade(240)),
    _preset(
        "in-up-fast", "빠르게 위 in", "short", _move("down", 64, ms=170, ease="out"), _fade(120)
    ),
    _preset(
        "wave-up",
        "위 파도",
        "short",
        _move("down", 50, ms=300, ease="out"),
        _step("wave", phase="hold", ms=700, amount=13, stagger=60),
    ),
    _preset("fill-down", "위 차오르기", "short", _step("wipe", direction="down", ms=520)),
    _preset(
        "low-wave", "낮은 파도", "short", _step("wave", phase="hold", ms=1100, amount=7, stagger=90)
    ),
    _preset(
        "diagonal-wriggle",
        "대각선 꿈틀",
        "short",
        _step("shear", amount=0.18, ms=260),
        _step("wave", phase="hold", ms=600, amount=9, direction="both", stagger=70),
    ),
    _preset("jitter", "덜덜덜 떨리는", "short", _step("shake", phase="hold", ms=110, amount=1.4)),
    _preset(
        "heartbeat-fast", "두근 - 빠른", "short", _step("breathe", phase="hold", ms=520, amount=9)
    ),
    _preset(
        "heartbeat-slow", "두근 - 느린", "short", _step("breathe", phase="hold", ms=1200, amount=6)
    ),
    _preset(
        "zoom-through",
        "뒤에서 쑥 커지기",
        "short",
        _scale(36, ms=560, ease="out"),
        _blur(8, ms=360),
        _fade(220),
    ),
    _preset("blur-in", "블러 등장", "short", _blur(16, ms=420), _fade(260)),
    _preset("puff-in", "뽕뽕 등장", "short", _scale(52, ms=280, overshoot=20), _blur(8, ms=220)),
    _preset(
        "split-vertical", "상하 등장", "short", _scale(0, ms=360, direction="vertical"), _fade(180)
    ),
    _preset(
        "split-horizontal",
        "양쪽 나타내기",
        "short",
        _scale(0, ms=360, direction="horizontal"),
        _fade(180),
    ),
    _preset(
        "soul-out",
        "영혼 탈출",
        "short",
        _fade(160),
        _step("move", phase="out", direction="up", amount=150, ms=520),
        _step("blur", phase="out", amount=16, ms=520),
        _step("fade", phase="out", ms=520),
    ),
    _preset(
        "grow-fade-out",
        "커짐 + 사라짐",
        "short",
        _fade(160),
        _step("scale", phase="out", amount=168, ms=420),
        _step("fade", phase="out", ms=420),
    ),
    _preset(
        "spin-fade-out",
        "회전 사라짐",
        "short",
        _fade(160),
        _step("spin", phase="out", amount=120, ms=420),
        _step("scale", phase="out", amount=40, ms=420),
        _step("fade", phase="out", ms=420),
    ),
    _preset(
        "mochi",
        "쫀득 모찌",
        "short",
        _scale(58, ms=460, overshoot=30, ease="in-out"),
        _step("breathe", phase="hold", ms=900, amount=5),
    ),
    _preset("blur-zoom", "블러 + 줌", "short", _blur(18, ms=400), _scale(142, ms=400, ease="out")),
    _preset("quick-zoom", "퀵 줌", "short", _scale(58, ms=150)),
    _preset("quick-zoom-out", "퀵 줌아웃", "short", _scale(152, ms=150)),
    _preset(
        "blur-box",
        "블러 - 네모",
        "short",
        _blur(14, ms=380),
        _step("wipe", direction="both", ms=420),
    ),
    _preset(
        "blur-round",
        "블러 - 원형",
        "short",
        _blur(14, ms=420),
        _scale(74, ms=420, ease="out"),
        _fade(240),
    ),
    _preset("white-flash", "흰색 번쩍", "short", _step("flash", ms=260), _scale(112, ms=220)),
    _preset(
        "shrink-out",
        "작아지며 사라짐",
        "short",
        _fade(160),
        _step("scale", phase="out", amount=42, ms=340),
        _step("fade", phase="out", ms=340),
    ),
    _preset(
        "slide-out-left",
        "왼쪽으로 사라짐",
        "short",
        _fade(160),
        _step("move", phase="out", direction="left", amount=160, ms=320),
        _step("fade", phase="out", ms=320),
    ),
    _preset(
        "slide-out-right",
        "오른쪽으로 사라짐",
        "short",
        _fade(160),
        _step("move", phase="out", direction="right", amount=160, ms=320),
        _step("fade", phase="out", ms=320),
    ),
]


# ---------------------------------------------------------------- 찾기·불러오기

# 사용자 프리셋 디렉터리. 안의 `*.json` 하나가 프리셋 하나입니다.
PRESETS_DIR_ENV = "R4_PRESETS_DIR"


def user_presets_dir() -> Path | None:
    """`R4_PRESETS_DIR`이 가리키는 디렉터리. 없거나 비었으면 None."""
    value = os.environ.get(PRESETS_DIR_ENV, "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_dir() else None


def load_preset(path: Path) -> MotionPreset:
    """JSON 파일 하나를 프리셋으로 읽습니다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"프리셋을 읽지 못했습니다: {path} ({error})") from error
    data.setdefault("pack", "user")
    return MotionPreset.model_validate(data)


def user_presets() -> dict[str, MotionPreset]:
    """사용자 디렉터리의 프리셋. 읽지 못하는 파일은 건너뜁니다."""
    directory = user_presets_dir()
    if directory is None:
        return {}
    out: dict[str, MotionPreset] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            preset = load_preset(path)
        except ValueError:
            continue
        out[preset.name] = preset
    return out


# 이번 실행에서만 쓰는 프리셋(JSON 파일로 직접 준 것). 이름으로 찾을 수 있게 담아 둡니다.
_REGISTERED: dict[str, MotionPreset] = {}


def register_preset(preset: MotionPreset) -> MotionPreset:
    """프리셋을 이번 실행 동안 이름으로 찾을 수 있게 등록합니다."""
    _REGISTERED[preset.name] = preset
    return preset


def all_presets() -> dict[str, MotionPreset]:
    """내장 + 사용자 + 등록한 프리셋. 이름이 같으면 나중 것이 이깁니다."""
    out = {preset.name: preset for preset in BUILTIN_PRESETS}
    out.update(user_presets())
    out.update(_REGISTERED)
    return out


def preset_names() -> list[str]:
    return list(all_presets())


def preset_labels() -> dict[str, str]:
    return {name: preset.label for name, preset in all_presets().items()}


def presets_by_pack() -> dict[str, list[MotionPreset]]:
    """팩 이름 → 프리셋 목록. 목록·시트에 나오는 순서입니다."""
    out: dict[str, list[MotionPreset]] = {}
    for preset in all_presets().values():
        out.setdefault(preset.pack, []).append(preset)
    return {pack: out[pack] for pack in PACK_LABELS if pack in out}


def get_preset(name: str) -> MotionPreset:
    presets = all_presets()
    if name not in presets:
        raise ValueError(f"모르는 프리셋입니다: {name}. 쓸 수 있는 것: {', '.join(presets)}")
    return presets[name]


def resolve_preset(reference: str | Path | MotionPreset | None) -> MotionPreset | None:
    """이름, JSON 파일 경로, 프리셋 객체 중 아무거나 받아 프리셋으로 만듭니다."""
    if reference is None or reference == "":
        return None
    if isinstance(reference, MotionPreset):
        return reference
    if isinstance(reference, Path) or str(reference).endswith(".json"):
        return load_preset(Path(reference))
    return get_preset(str(reference))
