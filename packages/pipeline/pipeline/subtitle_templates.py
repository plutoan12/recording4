"""자막 템플릿: 영상에 굽는 자막의 모양(글꼴·색·외곽선·위치)을 이름 붙여 둡니다.

순수 계산만 둡니다. 템플릿은 JSON으로 읽고 쓰는 값 객체이고, 렌더가 쓰는
pysubs2 스타일로 바꾸는 일만 합니다. 어떤 자막을 언제 보일지(줄바꿈·분할·
구간 자르기)는 `pipeline.subtitles`와 `pipeline.editing`이 정합니다. 여기서는
그렇게 정해진 자막을 어떤 모양으로 그릴지만 정합니다.

내장 템플릿 `default`는 템플릿이 생기기 전 렌더가 쓰던 값과 같습니다. 기존
편집본은 템플릿 이름 없이 저장돼 있으므로 이 값으로 그대로 렌더됩니다.

색은 CSS처럼 `#RRGGBB` 또는 `#RRGGBBAA`(AA는 불투명도, FF가 불투명)로 적습니다.
ASS는 알파를 반대로(0이 불투명) 두므로 여기서 바꿔 줍니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

import pysubs2
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipeline.editing import Cue
from pipeline.subtitle_files import plain_ass

TEMPLATE_NAME = r"^[a-z0-9][a-z0-9-]{0,39}$"
"""템플릿 이름 규칙. 편집본 설정과 URL에 그대로 들어가므로 소문자·숫자·하이픈만 둡니다."""

Position = Literal["bottom", "middle", "top"]
Horizontal = Literal["left", "center", "right"]
BorderStyle = Literal["outline", "box"]

_COLOR = re.compile(r"^#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?$")
# ASS 스타일 줄은 쉼표로 나뉘고 중괄호·역슬래시는 명령으로 읽힙니다. 글꼴 이름에
# 그런 글자가 들어가면 파일이 깨지거나 명령이 주입되므로 받지 않습니다.
_FONT_NAME = re.compile(r"^[^,{}\\\r\n\t]+$")


def parse_color(value: str) -> pysubs2.Color:
    """`#RRGGBB[AA]`를 pysubs2 색으로 바꿉니다. AA는 불투명도이고 ASS 알파는 그 반대입니다."""
    match = _COLOR.match(value)
    if not match:
        raise ValueError(f"색은 #RRGGBB 또는 #RRGGBBAA 형식이어야 합니다: {value!r}")
    rgb, alpha = match.groups()
    r, g, b = (int(rgb[i : i + 2], 16) for i in (0, 2, 4))
    opacity = int(alpha, 16) if alpha else 255
    return pysubs2.Color(r, g, b, 255 - opacity)


def format_color(color: pysubs2.Color) -> str:
    """pysubs2 색을 `#RRGGBB` 또는 `#RRGGBBAA`로 돌립니다. 불투명이면 AA를 생략합니다."""
    base = f"#{color.r:02X}{color.g:02X}{color.b:02X}"
    return base if color.a == 0 else f"{base}{255 - color.a:02X}"


# ASS 정렬은 숫자 키패드 배치입니다. 1·2·3 아래, 4·5·6 가운데, 7·8·9 위.
_ROW = {"bottom": 1, "middle": 4, "top": 7}
_COLUMN = {"left": 0, "center": 1, "right": 2}


def alignment_for(position: Position, horizontal: Horizontal = "center") -> pysubs2.Alignment:
    return pysubs2.Alignment(_ROW[position] + _COLUMN[horizontal])


class SubtitleTemplate(BaseModel):
    """자막 모양 한 벌. 값은 모두 검증되며 JSON으로 저장·복원할 수 있습니다."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    name: str = Field(pattern=TEMPLATE_NAME)
    label: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    font_name: str = Field(default="Noto Sans CJK KR", min_length=1, max_length=80)
    font_size: int = Field(default=64, ge=20, le=120)
    bold: bool = False
    italic: bool = False
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    # 외곽선 방식이면 그림자 색, 상자 방식이면 상자 색입니다.
    back_color: str = "#000000"
    outline: float = Field(default=3, ge=0, le=20)
    shadow: float = Field(default=1, ge=0, le=20)
    border_style: BorderStyle = "outline"
    position: Position = "bottom"
    horizontal: Horizontal = "center"
    margin_horizontal: int = Field(default=50, ge=0, le=500)
    # 화면 높이에 대한 비율입니다. 화면 크기가 달라도 같은 자리에 놓이게 합니다.
    margin_vertical_ratio: float = Field(default=0.13, ge=0, le=0.5)
    letter_spacing: float = Field(default=0, ge=-5, le=20)

    @field_validator("primary_color", "outline_color", "back_color")
    @classmethod
    def _valid_color(cls, value: str) -> str:
        parse_color(value)
        return value.upper()

    @field_validator("font_name")
    @classmethod
    def _valid_font_name(cls, value: str) -> str:
        value = value.strip()
        if not _FONT_NAME.match(value):
            raise ValueError("글꼴 이름에 쉼표·중괄호·역슬래시·줄바꿈을 쓸 수 없습니다.")
        return value

    def margin_vertical(self, height: int) -> int:
        return int(height * self.margin_vertical_ratio)

    def style(self, height: int, *, font_size: int | None = None) -> pysubs2.SSAStyle:
        """렌더가 쓰는 pysubs2 스타일. `font_size`를 주면 템플릿 값보다 우선합니다."""
        return pysubs2.SSAStyle(
            fontname=self.font_name,
            fontsize=font_size or self.font_size,
            bold=self.bold,
            italic=self.italic,
            primarycolor=parse_color(self.primary_color),
            outlinecolor=parse_color(self.outline_color),
            backcolor=parse_color(self.back_color),
            outline=self.outline,
            shadow=self.shadow,
            borderstyle=3 if self.border_style == "box" else 1,
            alignment=alignment_for(self.position, self.horizontal),
            marginl=self.margin_horizontal,
            marginr=self.margin_horizontal,
            marginv=self.margin_vertical(height),
            spacing=self.letter_spacing,
        )

    def title_style(self, height: int, *, font_size: int | None = None) -> pysubs2.SSAStyle:
        """화면 제목 스타일. 자막과 같은 모양이되 자막의 반대쪽 끝에 놓습니다.

        자막이 아래(기본)면 제목은 위, 자막이 위면 제목은 아래입니다. 가운데
        자막이면 제목은 위입니다. 같은 쪽에 두면 줄이 늘 때 서로 겹칩니다.
        """
        style = self.style(height, font_size=font_size)
        style.alignment = alignment_for("bottom" if self.position == "top" else "top")
        style.marginv = int(height * 0.08)
        return style

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2) + "\n"


def _builtin(**values) -> SubtitleTemplate:  # noqa: ANN003
    return SubtitleTemplate.model_validate(values)


BUILTIN_TEMPLATES: dict[str, SubtitleTemplate] = {
    t.name: t
    for t in (
        # 템플릿이 생기기 전 렌더 값 그대로입니다. 바꾸면 기존 편집본의 모양이 바뀝니다.
        _builtin(
            name="default",
            label="기본",
            description="흰 글자에 검은 외곽선. 템플릿 도입 전과 같은 모양입니다.",
        ),
        _builtin(
            name="shorts-bold",
            label="숏폼 강조",
            description="굵고 큰 글자에 두꺼운 외곽선. 작은 화면에서 잘 읽힙니다.",
            font_size=72,
            bold=True,
            outline=4,
            shadow=0,
        ),
        _builtin(
            name="yellow",
            label="예능 노랑",
            description="노란 굵은 글자에 검은 외곽선.",
            bold=True,
            primary_color="#FFE14D",
            outline=4,
            shadow=0,
        ),
        _builtin(
            name="box",
            label="반투명 상자",
            description="검은 반투명 상자 위에 흰 글자. 배경이 밝거나 복잡할 때 씁니다.",
            border_style="box",
            back_color="#00000099",
            outline=8,
            shadow=0,
        ),
        _builtin(
            name="top",
            label="상단 자막",
            description="자막을 화면 위에 둡니다. 화면 제목은 아래로 갑니다.",
            position="top",
            margin_vertical_ratio=0.10,
        ),
        _builtin(
            name="minimal",
            label="얇은 외곽선",
            description="작은 글자에 얇은 외곽선, 그림자 없음.",
            font_size=56,
            outline=1.5,
            shadow=0,
        ),
    )
}

DEFAULT_TEMPLATE = BUILTIN_TEMPLATES["default"]


def template_names() -> list[str]:
    return list(BUILTIN_TEMPLATES)


def get_template(name: str) -> SubtitleTemplate:
    """내장 템플릿. 모르는 이름이면 후보를 들어 ValueError를 올립니다."""
    try:
        return BUILTIN_TEMPLATES[name]
    except KeyError:
        raise ValueError(
            f"모르는 자막 템플릿입니다: {name!r}. 쓸 수 있는 것: {', '.join(BUILTIN_TEMPLATES)}"
        ) from None


def load_template(path: Path) -> SubtitleTemplate:
    """JSON 파일에서 템플릿을 읽습니다. 값 검증은 `SubtitleTemplate`이 합니다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"템플릿 파일을 읽지 못했습니다: {path.name} ({type(exc).__name__})"
        ) from None
    if not isinstance(data, dict):
        raise ValueError(f"템플릿 파일은 JSON 객체여야 합니다: {path.name}")
    return SubtitleTemplate.model_validate(data)


def resolve_template(reference: str | Path | SubtitleTemplate | None) -> SubtitleTemplate:
    """내장 이름, JSON 파일 경로, 이미 만든 템플릿 중 무엇이든 템플릿으로 만듭니다.

    None은 `default`입니다. 파일은 `.json`으로 끝나거나 실제로 존재할 때만 파일로
    봅니다. 그 밖의 문자열은 내장 이름입니다.
    """
    if reference is None:
        return DEFAULT_TEMPLATE
    if isinstance(reference, SubtitleTemplate):
        return reference
    path = Path(reference)
    if isinstance(reference, Path) or path.suffix.lower() == ".json" or path.is_file():
        return load_template(path)
    return get_template(str(reference))


def styled_document(
    cues: list[Cue],
    template: SubtitleTemplate,
    *,
    width: int,
    height: int,
    duration: float,
    title: str = "",
    font_size: int | None = None,
) -> pysubs2.SSAFile:
    """이미 다듬어진 자막(출력 시각, 줄바꿈 완료)을 템플릿 모양의 ASS 문서로 만듭니다.

    줄바꿈·분할·구간 자르기는 부르는 쪽이 끝내고 넘깁니다. libass 자동 줄바꿈에
    맡기지 않기 위해 `WrapStyle=0`(줄바꿈 표기만 존중)을 둡니다. `duration`은
    출력 영상 길이(초)이고 화면 제목이 보이는 시간입니다.
    """
    subs = pysubs2.SSAFile()
    subs.info.update(PlayResX=str(width), PlayResY=str(height), WrapStyle="0")
    subs.styles["Default"] = template.style(height, font_size=font_size)
    for cue in cues:
        subs.append(
            pysubs2.SSAEvent(
                start=round(cue.start * 1000),
                end=round(cue.end * 1000),
                text=plain_ass(cue.text),
            )
        )
    if title:
        subs.styles["Title"] = template.title_style(height, font_size=font_size)
        # 제목은 영상 전체 동안 보입니다. 자막이 없어도 제목만 보일 수 있습니다.
        subs.append(
            pysubs2.SSAEvent(
                start=0, end=round(duration * 1000), text=plain_ass(title), style="Title"
            )
        )
    return subs
