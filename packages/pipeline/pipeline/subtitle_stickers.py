"""스티커: 화살표·반짝이·말풍선 같은 장식을 자막 위에 얹습니다.

두 종류입니다.

- **내장 벡터 스티커**: ASS 드로잉(`\\p1`)으로 자막 문서에 이벤트로 들어갑니다. 자막과
  같은 경로(libass)로 그려지므로 색·외곽선·기울기·움직임(팝·바운스·흔들림 등)이 자막과
  같은 명령으로 붙고, 브라우저 정확 미리보기에도 그대로 나옵니다.
- **이미지 스티커**(`kind="image"`): 스티커 디렉터리(`R4_STICKERS_DIR`)의 PNG를 FFmpeg
  `overlay`로 얹습니다. libass는 이미지를 못 그리므로 영상 합성 단계에서 처리하고,
  움직임은 붙지 않습니다(자리와 시간만).

좌표 `x`·`y`는 화면 폭·높이에 대한 비율(0~1)이고 스티커의 가운데가 그 자리에 옵니다.
`size`는 스티커 폭(px)입니다. 시각 `start`·`end`는 자막과 같은 시간축(초)입니다.
"""

from __future__ import annotations

import math
from pathlib import Path

import pysubs2
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.subtitle_motion import ANIMATION_DEFAULT_MS, MOVING, Animation, motion_tags

__all__ = [
    "IMAGE_KIND",
    "STICKER_LABELS",
    "STICKER_SHAPES",
    "ImageOverlay",
    "Sticker",
    "add_sticker_events",
    "clip_stickers",
    "image_overlays",
    "overlay_filter_graph",
    "sticker_event_text",
]

IMAGE_KIND = "image"
STICKER_STYLE = "Sticker"
_UNIT = 100  # 도형은 100x100 상자 안에 그리고 좌표를 곱해 크기를 맞춥니다.
_K = 0.5523  # 원을 베지어 넷으로 그릴 때의 손잡이 길이 비율


def _num(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _circle(cx: float, cy: float, r: float) -> str:
    k = _K * r
    return (
        f"m {_num(cx + r)} {_num(cy)} "
        f"b {_num(cx + r)} {_num(cy + k)} {_num(cx + k)} {_num(cy + r)} {_num(cx)} {_num(cy + r)} "
        f"b {_num(cx - k)} {_num(cy + r)} {_num(cx - r)} {_num(cy + k)} {_num(cx - r)} {_num(cy)} "
        f"b {_num(cx - r)} {_num(cy - k)} {_num(cx - k)} {_num(cy - r)} {_num(cx)} {_num(cy - r)} "
        f"b {_num(cx + k)} {_num(cy - r)} {_num(cx + r)} {_num(cy - k)} {_num(cx + r)} {_num(cy)}"
    )


def scaled_path(path: str, factor: float) -> str:
    """드로잉 좌표에 배율을 곱합니다. `\\fscx`는 팝·맥박 같은 크기 움직임과 겹치므로 안 씁니다."""
    out = []
    for token in path.split():
        try:
            out.append(_num(float(token) * factor))
        except ValueError:
            out.append(token)
    return " ".join(out)


def _star(points: int, outer: float, inner: float) -> str:
    coords = []
    for index in range(points * 2):
        radius = outer if index % 2 == 0 else inner
        angle = -math.pi / 2 + index * math.pi / points
        coords.append((50 + radius * math.cos(angle), 50 + radius * math.sin(angle)))
    return "m " + " l ".join(f"{_num(x)} {_num(y)}" for x, y in coords)


# 100x100 상자 안의 도형. 이름은 편집기·API·CLI가 그대로 씁니다.
STICKER_SHAPES: dict[str, str] = {
    "arrow-right": "m 0 35 l 55 35 l 55 12 l 100 50 l 55 88 l 55 65 l 0 65",
    "arrow-down": "m 35 0 l 35 55 l 12 55 l 50 100 l 88 55 l 65 55 l 65 0",
    "sparkle": (
        "m 50 0 b 54 38 62 46 100 50 b 62 54 54 62 50 100 b 46 62 38 54 0 50 b 38 46 46 38 50 0"
    ),
    "star": _star(5, 50, 21),
    "heart": (
        "m 50 100 b 20 75 0 55 0 34 b 0 14 14 4 28 4 b 39 4 47 10 50 20 "
        "b 53 10 61 4 72 4 b 86 4 100 14 100 34 b 100 55 80 75 50 100"
    ),
    "circle": _circle(50, 50, 46),
    "speech-bubble": (
        "m 12 0 l 88 0 b 94.6 0 100 5.4 100 12 l 100 62 b 100 68.6 94.6 74 88 74 "
        "l 42 74 l 24 96 l 28 74 l 12 74 b 5.4 74 0 68.6 0 62 l 0 12 b 0 5.4 5.4 0 12 0"
    ),
    "check": "m 8 55 l 22 41 l 40 59 l 78 14 l 93 27 l 40 84",
    "wave-underline": (
        "m 0 40 b 25 18 25 62 50 40 b 75 18 75 62 100 40 l 100 58 "
        "b 75 80 75 36 50 58 b 25 80 25 36 0 58"
    ),
}

STICKER_LABELS: dict[str, str] = {
    "arrow-right": "화살표 →",
    "arrow-down": "화살표 ↓",
    "sparkle": "반짝이",
    "star": "별",
    "heart": "하트",
    "circle": "동그라미(테두리)",
    "speech-bubble": "말풍선",
    "check": "체크",
    "wave-underline": "물결 밑줄",
    IMAGE_KIND: "이미지(PNG)",
}

# 속이 빈 채로 테두리만 그리는 도형.
_HOLLOW = frozenset({"circle"})

_COLOR = r"^#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?$"
_IMAGE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,118}\.(?:png|PNG)$"


class Sticker(BaseModel):
    """스티커 하나. 편집본(EditSpec)에 여러 개 붙습니다."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    kind: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    # kind가 image일 때 스티커 디렉터리 안의 파일 이름. 경로는 받지 않습니다.
    image: str | None = Field(default=None, pattern=_IMAGE_NAME)
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.3, ge=0, le=1)
    size: int = Field(default=160, ge=16, le=1080)
    start: float = Field(default=0, ge=0)
    end: float | None = Field(default=None, gt=0)
    color: str = "#FFE14D"
    outline_color: str = "#111111"
    outline: float = Field(default=2, ge=0, le=20)
    angle: float = Field(default=0, ge=-180, le=180)
    animation: Animation = "none"
    animation_ms: int | None = Field(default=None, ge=40, le=3000)

    @field_validator("color", "outline_color")
    @classmethod
    def _valid_color(cls, value: str) -> str:
        import re

        if not re.match(_COLOR, value):
            raise ValueError("색은 #RRGGBB 또는 #RRGGBBAA 형식이어야 합니다.")
        return value.upper()

    @model_validator(mode="after")
    def _known_kind(self):
        if self.kind == IMAGE_KIND:
            if not self.image:
                raise ValueError("이미지 스티커에는 image(파일 이름)가 필요합니다.")
        elif self.kind not in STICKER_SHAPES:
            raise ValueError(
                f"모르는 스티커입니다: {self.kind}. 쓸 수 있는 것: {', '.join(STICKER_LABELS)}"
            )
        if self.end is not None and self.end <= self.start:
            raise ValueError("스티커 종료는 시작보다 뒤여야 합니다.")
        if self.animation in ("typewriter", "word-pop", "karaoke"):
            raise ValueError(
                "스티커에는 글자 단위 움직임(타자기·단어별·노래방)을 붙일 수 없습니다."
            )
        return self

    @property
    def is_image(self) -> bool:
        return self.kind == IMAGE_KIND

    @property
    def motion_ms(self) -> int:
        return self.animation_ms or ANIMATION_DEFAULT_MS[self.animation]


def clip_stickers(stickers: list[Sticker], start: float, end: float) -> list[Sticker]:
    """구간에 걸친 스티커만 남기고 시각을 구간 시작이 0초가 되게 옮깁니다."""
    kept = []
    for sticker in stickers:
        finish = sticker.end if sticker.end is not None else end
        if finish <= start or sticker.start >= end:
            continue
        kept.append(
            sticker.model_copy(
                update={
                    "start": max(sticker.start, start) - start,
                    "end": min(finish, end) - start,
                }
            )
        )
    return kept


def _ass_color(color: str) -> str:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _ass_alpha(color: str) -> str:
    opacity = int(color[7:9], 16) if len(color) == 9 else 255
    return f"&H{255 - opacity:02X}&"


def sticker_event_text(sticker: Sticker, width: int, height: int, duration_ms: int) -> str:
    """벡터 스티커 이벤트의 글자(명령 + 드로잉). 이미지 스티커에는 쓰지 않습니다."""
    if sticker.is_image:
        raise ValueError("이미지 스티커는 ASS로 그리지 않습니다.")
    cx, cy = sticker.x * width, sticker.y * height
    motion = motion_tags(
        sticker.animation,
        sticker.motion_ms,
        duration_ms=duration_ms,
        anchor=(cx, cy),
        angle=sticker.angle,
    )
    tags = ""
    if not (motion and sticker.animation in MOVING):
        tags += f"\\pos({cx:.0f},{cy:.0f})"
    tags += "\\an5\\p1\\shad0"
    if sticker.kind in _HOLLOW:
        tags += f"\\1a&HFF&\\3c{_ass_color(sticker.color)}\\3a{_ass_alpha(sticker.color)}"
        tags += f"\\bord{max(sticker.outline, 1):g}"
    else:
        tags += f"\\1c{_ass_color(sticker.color)}\\1a{_ass_alpha(sticker.color)}"
        tags += f"\\3c{_ass_color(sticker.outline_color)}\\bord{sticker.outline:g}"
    if sticker.angle and sticker.animation != "wiggle":
        tags += f"\\frz{sticker.angle:g}"
    return (
        "{" + tags + motion + "}" + scaled_path(STICKER_SHAPES[sticker.kind], sticker.size / _UNIT)
    )


def add_sticker_events(
    subs: pysubs2.SSAFile,
    stickers: list[Sticker],
    *,
    width: int,
    height: int,
    duration: float,
    layer: int = 50,
) -> int:
    """벡터 스티커를 문서에 넣고 넣은 수를 돌려줍니다. 자막보다 위 층에 둡니다."""
    vectors = [s for s in stickers if not s.is_image]
    if not vectors:
        return 0
    if STICKER_STYLE not in subs.styles:
        style = pysubs2.SSAStyle(outline=0, shadow=0, alignment=pysubs2.Alignment.MIDDLE_CENTER)
        style.marginl = style.marginr = style.marginv = 0
        subs.styles[STICKER_STYLE] = style
    limit_ms = round(duration * 1000)
    for sticker in vectors:
        start_ms = round(sticker.start * 1000)
        end_ms = min(round((sticker.end if sticker.end is not None else duration) * 1000), limit_ms)
        if start_ms >= limit_ms or end_ms <= start_ms:
            continue
        subs.append(
            pysubs2.SSAEvent(
                start=start_ms,
                end=end_ms,
                layer=layer,
                style=STICKER_STYLE,
                text=sticker_event_text(sticker, width, height, end_ms - start_ms),
            )
        )
    return len(vectors)


class ImageOverlay(BaseModel):
    """FFmpeg overlay 하나. 위치는 px, 시각은 초입니다."""

    path: Path
    center_x: float
    center_y: float
    width: int
    start: float
    end: float


def image_overlays(
    stickers: list[Sticker],
    directory: Path | None,
    *,
    width: int,
    height: int,
    duration: float,
) -> list[ImageOverlay]:
    """이미지 스티커를 overlay 목록으로. 디렉터리나 파일이 없으면 ValueError입니다."""
    images = [s for s in stickers if s.is_image]
    if not images:
        return []
    if directory is None or not directory.is_dir():
        raise ValueError("이미지 스티커를 쓰려면 스티커 디렉터리(R4_STICKERS_DIR)가 필요합니다.")
    found = []
    for sticker in images:
        path = (directory / str(sticker.image)).resolve()
        if path.parent != directory.resolve() or not path.is_file():
            raise ValueError(f"스티커 이미지가 없습니다: {sticker.image}")
        end = sticker.end if sticker.end is not None else duration
        if end <= sticker.start:
            continue
        found.append(
            ImageOverlay(
                path=path,
                center_x=sticker.x * width,
                center_y=sticker.y * height,
                width=sticker.size,
                start=sticker.start,
                end=end,
            )
        )
    return found


def overlay_filter_graph(
    base_chain: str, overlays: list[ImageOverlay], *, first_input: int = 1
) -> tuple[list[str], str, str]:
    """(추가 `-i` 인자, filter_complex 문자열, 출력 라벨).

    `base_chain`은 `[0:v]`에 적용할 기존 `-vf` 체인(크기·자막·format)입니다. 이미지는
    `first_input`번 입력부터 차례로 붙습니다. 정지 이미지는 한 프레임뿐이지만 overlay의
    기본 eof_action(repeat)이 마지막 프레임을 유지하므로 `-loop`가 필요 없습니다.
    """
    inputs: list[str] = []
    parts = [f"[0:v]{base_chain}[base0]"]
    current = "base0"
    for index, item in enumerate(overlays):
        inputs += ["-i", str(item.path)]
        stream = first_input + index
        scaled = f"s{index}"
        parts.append(f"[{stream}:v]scale={item.width}:-1[{scaled}]")
        out = f"base{index + 1}"
        parts.append(
            f"[{current}][{scaled}]overlay=x={item.center_x:.0f}-w/2:y={item.center_y:.0f}-h/2"
            f":enable='between(t,{item.start:.3f},{item.end:.3f})'[{out}]"
        )
        current = out
    return inputs, ";".join(parts), current
