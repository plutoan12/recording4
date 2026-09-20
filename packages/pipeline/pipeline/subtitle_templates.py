"""자막 템플릿: 영상에 굽는 자막의 모양(글꼴·색·외곽선·상자·글로우·장식·위치)을 이름 붙여 둡니다.

순수 계산만 둡니다. 템플릿은 JSON으로 읽고 쓰는 값 객체이고, 렌더가 쓰는
pysubs2 스타일로 바꾸는 일만 합니다. 어떤 자막을 언제 보일지(줄바꿈·분할·
구간 자르기)는 `pipeline.subtitles`와 `pipeline.editing`이 정합니다. 여기서는
그렇게 정해진 자막을 어떤 모양으로 그릴지만 정합니다.

내장 템플릿 `default`는 템플릿이 생기기 전 렌더가 쓰던 값과 같습니다. 기존
편집본은 템플릿 이름 없이 저장돼 있으므로 이 값으로 그대로 렌더됩니다.

색은 CSS처럼 `#RRGGBB` 또는 `#RRGGBBAA`(AA는 불투명도, FF가 불투명)로 적습니다.
ASS는 알파를 반대로(0이 불투명) 두므로 여기서 바꿔 줍니다.

상자 색은 libass 동작에 맞춥니다. BorderStyle 3(상자)은 **외곽선 색**으로 상자를
채우고, BorderStyle 4(상자+외곽선)는 뒷색으로 상자를 채우고 외곽선을 따로
그립니다. 그래서 `box_color`를 두고 방식에 따라 알맞은 자리에 넣습니다.

글로우는 ASS `\\blur` 명령입니다. 스타일에는 없고 이벤트 글자 앞에 붙는 명령이라
`styled_document`가 넣습니다. 사용자 글자는 `plain_ass`로 명령을 막지만 이 명령은
우리가 만드는 것이라 그대로 둡니다.
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
from pipeline.subtitle_fonts import FONT_FAMILIES

TEMPLATE_NAME = r"^[a-z0-9][a-z0-9-]{0,39}$"
"""템플릿 이름 규칙. 편집본 설정과 URL에 그대로 들어가므로 소문자·숫자·하이픈만 둡니다."""

Position = Literal["bottom", "middle", "top"]
Horizontal = Literal["left", "center", "right"]
BorderStyle = Literal["outline", "box", "box-outline"]
Category = Literal["basic", "vlog", "cute", "neon", "pixel", "box", "handwriting", "retro"]

CATEGORY_LABELS: dict[str, str] = {
    "basic": "기본",
    "vlog": "브이로그 제목",
    "cute": "귀여운 외곽선",
    "neon": "네온·글로우",
    "pixel": "픽셀",
    "box": "상자·카드",
    "handwriting": "손글씨",
    "retro": "레트로·세리프",
}

_COLOR = re.compile(r"^#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?$")
# ASS 스타일 줄은 쉼표로 나뉘고 중괄호·역슬래시는 명령으로 읽힙니다. 글꼴 이름에
# 그런 글자가 들어가면 파일이 깨지거나 명령이 주입되므로 받지 않습니다.
_FONT_NAME = re.compile(r"^[^,{}\\\r\n\t]+$")
# 장식은 글자 몇 개입니다. 줄바꿈은 자막 줄 수 규칙을 깨므로 받지 않습니다.
_DECORATION = re.compile(r"^[^\r\n\t]*$")


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
_BORDER = {"outline": 1, "box": 3, "box-outline": 4}


def alignment_for(position: Position, horizontal: Horizontal = "center") -> pysubs2.Alignment:
    return pysubs2.Alignment(_ROW[position] + _COLUMN[horizontal])


class SubtitleTemplate(BaseModel):
    """자막 모양 한 벌. 값은 모두 검증되며 JSON으로 저장·복원할 수 있습니다."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    name: str = Field(pattern=TEMPLATE_NAME)
    label: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    category: Category = "basic"
    # 미리보기에 쓰는 예문. 비우면 label을 씁니다.
    sample: str = Field(default="", max_length=40)
    font_name: str = Field(default="Noto Sans CJK KR", min_length=1, max_length=80)
    font_size: int = Field(default=64, ge=20, le=120)
    bold: bool = False
    italic: bool = False
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    # 외곽선 방식의 그림자 색입니다.
    back_color: str = "#000000"
    # 상자 방식(box, box-outline)의 상자 색입니다.
    box_color: str = "#000000"
    outline: float = Field(default=3, ge=0, le=20)
    shadow: float = Field(default=1, ge=0, le=20)
    # 글자 주변을 번지게 하는 정도(ASS \blur). 외곽선 색이 번져 네온처럼 보입니다.
    glow: float = Field(default=0, ge=0, le=20)
    border_style: BorderStyle = "outline"
    position: Position = "bottom"
    horizontal: Horizontal = "center"
    margin_horizontal: int = Field(default=50, ge=0, le=500)
    # 화면 높이에 대한 비율입니다. 화면 크기가 달라도 같은 자리에 놓이게 합니다.
    margin_vertical_ratio: float = Field(default=0.13, ge=0, le=0.5)
    letter_spacing: float = Field(default=0, ge=-5, le=20)
    # 자막 앞뒤에 붙는 장식 기호(★ ☆ ♡ ✳ 등). 글꼴에 있는 글자여야 그려집니다.
    prefix: str = Field(default="", max_length=8)
    suffix: str = Field(default="", max_length=8)

    @field_validator("primary_color", "outline_color", "back_color", "box_color")
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

    @field_validator("prefix", "suffix")
    @classmethod
    def _valid_decoration(cls, value: str) -> str:
        if not _DECORATION.match(value):
            raise ValueError("장식에 줄바꿈이나 탭을 쓸 수 없습니다.")
        return value.strip()

    @property
    def font_available(self) -> bool:
        """워커 이미지에 설치하는 글꼴인지. 아니면 libass가 다른 글꼴로 대체합니다."""
        return self.font_name in FONT_FAMILIES

    def margin_vertical(self, height: int) -> int:
        return int(height * self.margin_vertical_ratio)

    def style(self, height: int, *, font_size: int | None = None) -> pysubs2.SSAStyle:
        """렌더가 쓰는 pysubs2 스타일. `font_size`를 주면 템플릿 값보다 우선합니다."""
        outline_color = parse_color(self.outline_color)
        back_color = parse_color(self.back_color)
        if self.border_style == "box":
            # libass는 BorderStyle 3의 상자를 외곽선 색으로 채웁니다.
            outline_color = parse_color(self.box_color)
            back_color = parse_color(self.box_color)
        elif self.border_style == "box-outline":
            back_color = parse_color(self.box_color)
        return pysubs2.SSAStyle(
            fontname=self.font_name,
            fontsize=font_size or self.font_size,
            bold=self.bold,
            italic=self.italic,
            primarycolor=parse_color(self.primary_color),
            outlinecolor=outline_color,
            backcolor=back_color,
            outline=self.outline,
            shadow=self.shadow,
            borderstyle=_BORDER[self.border_style],
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

    def override_tags(self) -> str:
        """이벤트 글자 앞에 붙는 ASS 명령. 지금은 글로우뿐입니다."""
        return f"{{\\blur{self.glow:g}}}" if self.glow else ""

    def decorate(self, text: str) -> str:
        """장식을 붙입니다. 여러 줄이면 첫 줄 앞과 마지막 줄 뒤에만 붙입니다."""
        if self.prefix:
            text = f"{self.prefix} {text}"
        if self.suffix:
            text = f"{text} {self.suffix}"
        return text

    def event_text(self, text: str) -> str:
        """사용자 글자를 안전하게 만들고 장식·명령을 붙인 이벤트 글자."""
        return self.override_tags() + plain_ass(self.decorate(text))

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2) + "\n"


def _builtin(**values) -> SubtitleTemplate:  # noqa: ANN003
    return SubtitleTemplate.model_validate(values)


# 내장 템플릿. 순서가 화면과 시트에 그대로 나옵니다.
#
# 글꼴은 pipeline.subtitle_fonts 목록에 있는 것만 씁니다. 글자 크기는 1080x1920
# 숏폼 기준이고, 두 줄 이상이면 규칙(pipeline.subtitles)이 먼저 나눕니다.
BUILTIN_TEMPLATES: dict[str, SubtitleTemplate] = {
    t.name: t
    for t in (
        # ---- 기본 -------------------------------------------------------
        # 템플릿이 생기기 전 렌더 값 그대로입니다. 바꾸면 기존 편집본의 모양이 바뀝니다.
        _builtin(
            name="default",
            label="기본",
            description="흰 글자에 검은 외곽선. 템플릿 도입 전과 같은 모양입니다.",
            sample="기본 자막입니다",
        ),
        _builtin(
            name="shorts-bold",
            label="숏폼 강조",
            description="굵고 큰 글자에 두꺼운 외곽선. 작은 화면에서 잘 읽힙니다.",
            sample="작은 화면에서도 잘 보여요",
            font_size=72,
            bold=True,
            outline=4,
            shadow=0,
        ),
        _builtin(
            name="yellow",
            label="예능 노랑",
            description="노란 굵은 글자에 검은 외곽선.",
            sample="이거 진짜 맛있다",
            bold=True,
            primary_color="#FFE14D",
            outline=4,
            shadow=0,
        ),
        _builtin(
            name="box",
            label="반투명 상자",
            description="검은 반투명 상자 위에 흰 글자. 배경이 밝거나 복잡할 때 씁니다.",
            sample="배경이 복잡해도 잘 읽혀요",
            category="box",
            border_style="box",
            box_color="#00000099",
            outline=8,
            shadow=0,
        ),
        _builtin(
            name="top",
            label="상단 자막",
            description="자막을 화면 위에 둡니다. 화면 제목은 아래로 갑니다.",
            sample="위쪽에 놓이는 자막",
            position="top",
            margin_vertical_ratio=0.10,
        ),
        _builtin(
            name="minimal",
            label="얇은 외곽선",
            description="작은 글자에 얇은 외곽선, 그림자 없음.",
            sample="담백하게 작은 글자",
            font_size=56,
            outline=1.5,
            shadow=0,
        ),
        # ---- 브이로그 제목 ------------------------------------------------
        _builtin(
            name="vlog-lime",
            label="브이로그 라임",
            description="형광 연두 굵은 제목 글씨. TOKYO VLOG 같은 큰 제목에.",
            sample="TOKYO VLOG",
            category="vlog",
            font_name="Black Han Sans",
            font_size=96,
            primary_color="#9DFF3C",
            outline_color="#0B3D00",
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="vlog-pink",
            label="브이로그 핑크",
            description="진한 핑크 제목 글씨. 한글도 영어도 예쁩니다.",
            sample="TOKYO VLOG",
            category="vlog",
            font_name="Black Han Sans",
            font_size=92,
            primary_color="#FF4FA3",
            outline_color="#3D0A25",
            outline=2,
            shadow=0,
            prefix="✳",
            suffix="✳",
        ),
        _builtin(
            name="fire-red",
            label="불타는 빨강",
            description="빨간 굵은 글자가 살짝 번집니다. 강조에.",
            sample="불타는 고구마;;;;",
            category="vlog",
            font_name="Black Han Sans",
            font_size=84,
            primary_color="#FF3B2E",
            outline_color="#5A0000",
            outline=3,
            shadow=0,
            glow=2,
        ),
        _builtin(
            name="spring-glow",
            label="봄 느낌 글로우",
            description="흰 손글씨에 연둣빛 번짐. 따뜻한 봄 느낌.",
            sample="따뜻한 봄 느낌 살려서~",
            category="vlog",
            font_name="Gaegu",
            font_size=80,
            bold=True,
            primary_color="#FFFFFF",
            outline_color="#B8FF7A",
            outline=5,
            shadow=0,
            glow=6,
        ),
        # ---- 귀여운 외곽선 ------------------------------------------------
        _builtin(
            name="bubble-white",
            label="말풍선 흰색",
            description="통통한 흰 글자에 두꺼운 검은 외곽선. 별 장식.",
            sample="유행을 찾아서",
            category="cute",
            font_name="Bagel Fat One",
            font_size=78,
            outline=7,
            shadow=0,
            prefix="★",
            suffix="☆",
        ),
        _builtin(
            name="bubble-sky",
            label="말풍선 하늘",
            description="하늘색 통통 글자에 흰 외곽선. 하트 장식.",
            sample="너무 귀여워...",
            category="cute",
            font_name="Bagel Fat One",
            font_size=78,
            primary_color="#8ED8FF",
            outline_color="#FFFFFF",
            outline=6,
            shadow=0,
            glow=1.5,
            suffix="♡",
        ),
        _builtin(
            name="bubble-pink",
            label="말풍선 핑크",
            description="핑크 통통 글자에 흰 외곽선.",
            sample="딸기말차라떼",
            category="cute",
            font_name="Bagel Fat One",
            font_size=78,
            primary_color="#FF9BD2",
            outline_color="#FFFFFF",
            outline=6,
            shadow=0,
        ),
        _builtin(
            name="round-white",
            label="둥글둥글 흰색",
            description="동글동글한 글자에 핑크 외곽선이 살짝 번집니다.",
            sample="둥글둥글 귀엽다",
            category="cute",
            font_name="Dongle",
            font_size=110,
            bold=True,
            outline_color="#FF7AB6",
            outline=5,
            shadow=0,
            glow=3,
            suffix="♡",
        ),
        _builtin(
            name="mint-pastel",
            label="민트 파스텔",
            description="연한 민트 글자에 흰 외곽선.",
            sample="셀프 메이크업 완성!",
            category="cute",
            font_name="Jua",
            font_size=76,
            primary_color="#C8FFE6",
            outline_color="#FFFFFF",
            outline=4,
            shadow=0,
            glow=1,
        ),
        # ---- 네온·글로우 --------------------------------------------------
        _builtin(
            name="neon-pink",
            label="네온 핑크",
            description="연핑크 글자에 진핑크 빛 번짐. 네온사인 느낌.",
            sample="제발... 제발!!!!!",
            category="neon",
            font_name="Gaegu",
            font_size=84,
            bold=True,
            primary_color="#FFE6FA",
            outline_color="#FF3FD8",
            outline=4,
            shadow=0,
            glow=7,
        ),
        _builtin(
            name="neon-blue",
            label="네온 블루",
            description="파란 빛 번짐. 완전 레트로 느낌.",
            sample="완전 레트로 느낌이잖아",
            category="neon",
            font_name="Gugi",
            font_size=76,
            primary_color="#DDEEFF",
            outline_color="#2F6BFF",
            outline=4,
            shadow=0,
            glow=6,
        ),
        _builtin(
            name="neon-purple",
            label="네온 퍼플",
            description="보라 빛 번짐에 별 장식.",
            sample="쿨하게 패스",
            category="neon",
            font_name="Jua",
            font_size=78,
            primary_color="#F4E6FF",
            outline_color="#9B4DFF",
            outline=4,
            shadow=0,
            glow=7,
            suffix="☆",
        ),
        _builtin(
            name="lavender-glow",
            label="라벤더 글로우",
            description="연보라 손글씨에 은은한 번짐.",
            sample="고급스러운 느낌",
            category="neon",
            font_name="Single Day",
            font_size=84,
            primary_color="#E6D6FF",
            outline_color="#B08CFF",
            outline=3,
            shadow=0,
            glow=5,
            suffix="✦",
        ),
        # ---- 픽셀 -------------------------------------------------------
        _builtin(
            name="pixel-heart",
            label="픽셀 하트",
            description="도트 글꼴에 핑크 글자, 하트 장식.",
            sample="요래 됐습니다",
            category="pixel",
            font_name="Galmuri11 Regular",
            font_size=64,
            primary_color="#FFB7D5",
            outline_color="#4A1F35",
            outline=2,
            shadow=0,
            prefix="♡",
            suffix="♡",
        ),
        _builtin(
            name="pixel-mint",
            label="픽셀 민트",
            description="도트 글꼴에 민트 글자.",
            sample="오늘의 TMI!",
            category="pixel",
            font_name="Galmuri11 Regular",
            font_size=64,
            primary_color="#B7FFE8",
            outline_color="#0B3D33",
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="pixel-box",
            label="픽셀 상자",
            description="도트 글꼴을 연노랑 상자에.",
            sample="짧은 자막용!",
            category="pixel",
            font_name="Galmuri9 Regular",
            font_size=48,
            primary_color="#2A2A2A",
            border_style="box",
            box_color="#FFF3A6",
            outline=10,
            shadow=0,
        ),
        # ---- 상자·카드 ----------------------------------------------------
        _builtin(
            name="pink-cabinet",
            label="핑크 캐비닛",
            description="연핑크 상자에 진핑크 테두리. 소제목에.",
            sample="민주의 핑크 캐비닛",
            category="box",
            font_name="Jua",
            font_size=52,
            primary_color="#3A2A3A",
            border_style="box-outline",
            box_color="#FFD1E8",
            outline_color="#F06AA8",
            outline=3,
            shadow=0,
            prefix="✳",
            suffix="✳",
        ),
        _builtin(
            name="note-yellow",
            label="짧은 자막 노랑",
            description="연노랑 상자에 작은 검은 글자. 짧은 한마디에.",
            sample="짧은 자막용!",
            category="box",
            font_name="Jua",
            font_size=44,
            primary_color="#2A2A2A",
            border_style="box",
            box_color="#FFF3A6",
            outline=10,
            shadow=0,
        ),
        _builtin(
            name="note-pink",
            label="짧은 자막 핑크",
            description="연핑크 상자에 작은 검은 글자.",
            sample="짧은 자막용!",
            category="box",
            font_name="Jua",
            font_size=44,
            primary_color="#2A2A2A",
            border_style="box",
            box_color="#FFD6EA",
            outline=10,
            shadow=0,
        ),
        _builtin(
            name="note-blue",
            label="짧은 자막 하늘",
            description="하늘색 상자에 작은 검은 글자.",
            sample="짧은 자막용!",
            category="box",
            font_name="Jua",
            font_size=44,
            primary_color="#2A2A2A",
            border_style="box",
            box_color="#CFEBFF",
            outline=10,
            shadow=0,
        ),
        _builtin(
            name="tmi-blue",
            label="TMI 파랑",
            description="연파랑 상자에 파란 손글씨, 하늘 테두리.",
            sample="아무도 안 물어봤던 오늘의 TMI!",
            category="box",
            font_name="Gaegu",
            font_size=52,
            bold=True,
            primary_color="#1B4DFF",
            border_style="box-outline",
            box_color="#E6F3FF",
            outline_color="#6EB6FF",
            outline=3,
            shadow=0,
        ),
        _builtin(
            name="white-card",
            label="흰 카드",
            description="흰 카드에 검은 글자. 제품 이름·정보 표시에.",
            sample="WAKEMAKE 소프트 블러링",
            category="box",
            font_name="Do Hyeon",
            font_size=56,
            primary_color="#111111",
            border_style="box-outline",
            box_color="#FFFFFF",
            outline_color="#111111",
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="black-tag",
            label="검은 태그",
            description="검은 상자에 작은 흰 글자. 안내 문구에.",
            sample="광고X, 내돈내산템만!",
            category="box",
            font_name="Do Hyeon",
            font_size=42,
            border_style="box",
            box_color="#111111",
            outline=8,
            shadow=0,
            letter_spacing=1,
        ),
        _builtin(
            name="cyan-strip",
            label="하늘 띠",
            description="하늘색 띠에 검은 글자와 별 장식.",
            sample="이거 진짜 귀엽다",
            category="box",
            font_name="Jua",
            font_size=48,
            primary_color="#1A1A1A",
            border_style="box",
            box_color="#9BE7FF",
            outline=8,
            shadow=0,
            prefix="✳",
            suffix="✳",
        ),
        # ---- 손글씨 -------------------------------------------------------
        _builtin(
            name="pen-white",
            label="펜 손글씨",
            description="흰 펜 글씨에 얇은 검은 외곽선, 반짝이 장식.",
            sample="헤헿 아닌가보다",
            category="handwriting",
            font_name="Nanum Pen",
            font_size=96,
            outline=2,
            shadow=0,
            prefix="✧",
            suffix="✧",
        ),
        _builtin(
            name="melody-pink",
            label="멜로디 핑크",
            description="동그란 손글씨에 연핑크 글자.",
            sample="나만 없어 인형 ㅠㅠㅠ",
            category="handwriting",
            font_name="Hi Melody",
            font_size=88,
            primary_color="#FFC2E2",
            outline_color="#4A1F35",
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="gamja-yellow",
            label="감자꽃 노랑",
            description="삐뚤빼뚤 손글씨에 연노랑 글자.",
            sample="여행은 오랜만이라서 떨리네요...",
            category="handwriting",
            font_name="Gamja Flower",
            font_size=84,
            primary_color="#FFF7B0",
            outline_color="#5A4A00",
            outline=3,
            shadow=0,
        ),
        _builtin(
            name="brush-white",
            label="붓글씨",
            description="붓 느낌 흰 글씨에 그림자.",
            sample="이게 무슨 일이야...",
            category="handwriting",
            font_name="East Sea Dokdo",
            font_size=92,
            outline=2,
            shadow=2,
        ),
        # ---- 레트로·세리프 --------------------------------------------------
        _builtin(
            name="movie-serif",
            label="영화 자막",
            description="바탕체 흰 글자, 자간 살짝. 영화 같은 자막.",
            sample="제 친구 뻔뀐이에요",
            category="retro",
            font_name="Gowun Batang",
            font_size=52,
            outline=1,
            shadow=0,
            letter_spacing=2,
            suffix="♪",
        ),
        _builtin(
            name="luxury-serif",
            label="고급 세리프",
            description="바탕체에 얇은 외곽선과 반짝이. 고급스러운 느낌.",
            sample="고급스러운 느낌",
            category="retro",
            font_name="Gowun Batang",
            font_size=64,
            outline=1,
            shadow=1,
            letter_spacing=3,
            suffix="✦",
        ),
        _builtin(
            name="retro-orange",
            label="레트로 주황",
            description="레트로 글꼴에 주황 글자, 갈색 외곽선과 그림자.",
            sample="당일치기 후쿠오카",
            category="retro",
            font_name="Moirai One",
            font_size=84,
            primary_color="#FFD966",
            outline_color="#7A3E00",
            outline=4,
            shadow=3,
            prefix="★",
            suffix="★",
        ),
        _builtin(
            name="retro-blue-pixel",
            label="레트로 블루 픽셀",
            description="도트 글꼴에 파란 글자, 흰 외곽선.",
            sample="원위외 뷰티템 ASMR",
            category="retro",
            font_name="Galmuri11 Regular",
            font_size=64,
            primary_color="#3D7BFF",
            outline_color="#FFFFFF",
            outline=2,
            shadow=0,
            prefix="♪",
            suffix="♪",
        ),
    )
}

DEFAULT_TEMPLATE = BUILTIN_TEMPLATES["default"]


def template_names() -> list[str]:
    return list(BUILTIN_TEMPLATES)


def templates_by_category() -> dict[str, list[SubtitleTemplate]]:
    """카테고리 순서대로 묶은 내장 템플릿. 화면과 시트가 같은 순서를 씁니다."""
    grouped: dict[str, list[SubtitleTemplate]] = {key: [] for key in CATEGORY_LABELS}
    for template in BUILTIN_TEMPLATES.values():
        grouped[template.category].append(template)
    return {key: items for key, items in grouped.items() if items}


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
                text=template.event_text(cue.text),
            )
        )
    if title:
        subs.styles["Title"] = template.title_style(height, font_size=font_size)
        # 제목은 영상 전체 동안 보입니다. 자막이 없어도 제목만 보일 수 있습니다.
        # 장식은 대사에만 붙입니다. 제목은 편집기에서 직접 적는 글자입니다.
        subs.append(
            pysubs2.SSAEvent(
                start=0,
                end=round(duration * 1000),
                text=template.override_tags() + plain_ass(title),
                style="Title",
            )
        )
    return subs


# ---------------------------------------------------------------- 미리보기 시트

SHEET_WIDTH = 1080
SHEET_COLUMNS = 2
SHEET_ROW_HEIGHT = 150
SHEET_PADDING = 40
SHEET_HEADER = 110


def sheet_document(
    templates: list[SubtitleTemplate],
    *,
    width: int = SHEET_WIDTH,
    columns: int = SHEET_COLUMNS,
    row_height: int = SHEET_ROW_HEIGHT,
    text: str | None = None,
    title: str = "자막 템플릿",
) -> tuple[pysubs2.SSAFile, int]:
    """템플릿마다 예문 한 줄을 격자에 놓은 ASS 문서와 필요한 화면 높이를 돌려줍니다.

    한 프레임으로 렌더하면 인스타그램 소개 이미지 같은 한 장짜리 시트가 됩니다.
    템플릿마다 스타일을 하나씩 만들고 `\\pos`로 칸 가운데에 둡니다. 글자 크기는
    칸에 맞춰 줄입니다(긴 예문이 옆 칸을 침범하지 않게).
    """
    if not templates:
        raise ValueError("시트에 넣을 템플릿이 없습니다.")
    if columns < 1 or width < 200:
        raise ValueError("열 수는 1 이상, 너비는 200 이상이어야 합니다.")
    rows = -(-len(templates) // columns)
    height = SHEET_HEADER + rows * row_height + SHEET_PADDING
    height += height % 2
    cell_width = (width - 2 * SHEET_PADDING) / columns

    subs = pysubs2.SSAFile()
    subs.info.update(PlayResX=str(width), PlayResY=str(height), WrapStyle="2")
    subs.styles["Header"] = pysubs2.SSAStyle(
        fontname="Noto Sans CJK KR",
        fontsize=40,
        bold=True,
        primarycolor=pysubs2.Color(255, 255, 255, 0),
        outlinecolor=pysubs2.Color(0, 0, 0, 0),
        outline=0,
        shadow=0,
        alignment=pysubs2.Alignment.MIDDLE_CENTER,
    )
    subs.append(
        pysubs2.SSAEvent(
            start=0,
            end=1000,
            style="Header",
            text=f"{{\\pos({width / 2:.0f},{SHEET_HEADER / 2:.0f})}}"
            + plain_ass(f"{title} · {len(templates)}종"),
        )
    )
    for index, template in enumerate(templates):
        sample = text or template.sample or template.label
        shown = template.decorate(sample)
        # 칸 너비에 맞춰 글자 크기를 줄입니다. 한글 1자 ≈ 글자 크기 1배 폭으로 어림합니다.
        widest = max(len(shown), 1)
        fit = int(min(template.font_size, (cell_width - 2 * template.outline - 40) / widest * 1.4))
        fit = max(20, min(fit, int(row_height * 0.55)))
        style = template.style(height, font_size=fit)
        style.alignment = pysubs2.Alignment.MIDDLE_CENTER
        style.marginl = style.marginr = style.marginv = 0
        style_name = f"T{index}"
        subs.styles[style_name] = style
        column, row = index % columns, index // columns
        x = SHEET_PADDING + cell_width * (column + 0.5)
        y = SHEET_HEADER + row_height * (row + 0.5)
        subs.append(
            pysubs2.SSAEvent(
                start=0,
                end=1000,
                style=style_name,
                text=f"{{\\pos({x:.0f},{y:.0f})}}" + template.override_tags() + plain_ass(shown),
            )
        )
    return subs, height
