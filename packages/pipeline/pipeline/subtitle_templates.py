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

스티커처럼 보이는 이중 외곽선(안쪽 색선 + 바깥 테두리)은 ASS에 없어 이벤트를 두
겹으로 냅니다. 뒤 층은 외곽선을 `outline + outline2`만큼 바깥 색으로, 앞 층은 원래
외곽선으로 그립니다. 그림자와 글로우는 뒤 층에만 둡니다.

속 빈 글자(`hollow`)는 채움 색을 투명으로 두고 외곽선만 그립니다. 글로우와 함께 쓰면
선만 빛나는 네온사인이 됩니다. 입체 돌출(`extrude`)은 그림자를 1px씩 밀어 여러 겹
쌓아 두께처럼 보이게 합니다. 단어별 강조(`accent_color`)는 글자 안의 `[[...]]` 표기를
그 색으로 그립니다(pipeline.subtitle_markup).

둥근 상자(`box_radius`)는 ASS 상자로는 못 그리므로 글자 폭을 재서(pipeline.subtitle_metrics)
글자 뒤 층에 벡터 둥근 사각형을 그립니다. 글자 자체는 외곽선 없는 보통 글자가 됩니다.

글로우는 ASS `\\blur` 명령입니다. 스타일에는 없고 이벤트 글자 앞에 붙는 명령이라
`styled_document`가 넣습니다. 사용자 글자는 `plain_ass`로 명령을 막지만 이 명령은
우리가 만드는 것이라 그대로 둡니다.
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from pathlib import Path
from typing import Literal

import pysubs2
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipeline.editing import Cue
from pipeline.subtitle_files import plain_ass
from pipeline.subtitle_fonts import EMOJI_FONT, FONT_FAMILIES
from pipeline.subtitle_markup import split_emoji, split_markup, strip_markup
from pipeline.subtitle_metrics import measure_text
from pipeline.subtitles import text_width

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
    # 바깥 테두리(스티커 느낌). 0이면 없습니다. 외곽선 방식에서만 그립니다.
    outline2: float = Field(default=0, ge=0, le=20)
    outline2_color: str = "#FFFFFF"
    shadow: float = Field(default=1, ge=0, le=20)
    # 살짝 기울인 글자(도). 양수가 반시계 방향입니다.
    angle: float = Field(default=0, ge=-30, le=30)
    # 속 빈 글자. 채움을 투명으로 두고 외곽선만 그립니다(네온사인).
    hollow: bool = False
    # 입체 돌출 깊이(px)와 색. 그림자를 1px씩 밀어 쌓습니다. 0이면 없습니다.
    extrude: int = Field(default=0, ge=0, le=16)
    extrude_color: str = "#222222"
    # `[[...]]`로 감싼 부분의 색. 비우면 표기만 빼고 같은 색으로 그립니다.
    accent_color: str = ""
    # 글자 주변을 번지게 하는 정도(ASS \blur). 외곽선 색이 번져 네온처럼 보입니다.
    glow: float = Field(default=0, ge=0, le=20)
    border_style: BorderStyle = "outline"
    # 상자 모서리 반지름(px). 0이면 libass의 각진 상자, 0보다 크면 글자 뒤에 둥근 사각형을
    # 그립니다. 상자 방식에서만 뜻이 있습니다. 여백은 `outline`, 테두리 두께는 `outline2`입니다.
    box_radius: int = Field(default=0, ge=0, le=60)
    position: Position = "bottom"
    horizontal: Horizontal = "center"
    margin_horizontal: int = Field(default=50, ge=0, le=500)
    # 화면 높이에 대한 비율입니다. 화면 크기가 달라도 같은 자리에 놓이게 합니다.
    margin_vertical_ratio: float = Field(default=0.13, ge=0, le=0.5)
    letter_spacing: float = Field(default=0, ge=-5, le=20)
    # 자막 앞뒤에 붙는 장식 기호(★ ☆ ♡ ✳ 등). 글꼴에 있는 글자여야 그려집니다.
    prefix: str = Field(default="", max_length=8)
    suffix: str = Field(default="", max_length=8)

    @field_validator(
        "primary_color",
        "outline_color",
        "back_color",
        "box_color",
        "outline2_color",
        "extrude_color",
    )
    @classmethod
    def _valid_color(cls, value: str) -> str:
        parse_color(value)
        return value.upper()

    @field_validator("accent_color")
    @classmethod
    def _valid_optional_color(cls, value: str) -> str:
        if value:
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
        primary = parse_color(self.primary_color)
        if self.hollow:
            primary = pysubs2.Color(primary.r, primary.g, primary.b, 255)  # 완전 투명
        if self.rounded_box:
            # 상자는 따로 그리므로 글자는 외곽선·그림자 없는 보통 글자입니다.
            return pysubs2.SSAStyle(
                fontname=self.font_name,
                fontsize=font_size or self.font_size,
                bold=self.bold,
                italic=self.italic,
                primarycolor=primary,
                outline=0,
                shadow=0,
                borderstyle=1,
                alignment=alignment_for(self.position, self.horizontal),
                marginl=self.margin_horizontal,
                marginr=self.margin_horizontal,
                marginv=self.margin_vertical(height),
                spacing=self.letter_spacing,
                angle=self.angle,
            )
        return pysubs2.SSAStyle(
            fontname=self.font_name,
            fontsize=font_size or self.font_size,
            bold=self.bold,
            italic=self.italic,
            primarycolor=primary,
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
            angle=self.angle,
        )

    @property
    def rounded_box(self) -> bool:
        return self.border_style != "outline" and self.box_radius > 0

    @property
    def layered(self) -> bool:
        """두 겹 이상으로 그려야 하는지.

        바깥 테두리가 있거나, 속 빈 글자에 글로우를 줄 때(뒤 층만 번지고 앞 선은 또렷),
        입체 돌출이 있을 때입니다. 외곽선 방식에서만입니다.
        """
        if self.border_style != "outline":
            return False
        return self.outline2 > 0 or (self.hollow and self.glow > 0) or self.extrude > 0

    @property
    def has_back_layer(self) -> bool:
        return self.border_style == "outline" and (
            self.outline2 > 0 or (self.hollow and self.glow > 0)
        )

    def back_style(self, style: pysubs2.SSAStyle) -> pysubs2.SSAStyle:
        """앞 층 스타일에서 뒤 층(바깥 테두리 또는 번지는 선) 스타일을 만듭니다."""
        back = style.copy()
        if self.outline2 > 0:
            back.outlinecolor = parse_color(self.outline2_color)
            back.outline = style.outline + self.outline2
        return back

    def extrude_style(self, style: pysubs2.SSAStyle) -> pysubs2.SSAStyle:
        """입체 돌출 층. 글자와 외곽선을 돌출 색으로 칠해 뒤로 밀어 쌓습니다."""
        color = parse_color(self.extrude_color)
        depth = style.copy()
        depth.primarycolor = color
        depth.outlinecolor = color
        depth.shadow = 0
        return depth

    def front_style(self, style: pysubs2.SSAStyle) -> pysubs2.SSAStyle:
        """두 겹일 때 앞 층. 그림자는 뒤 층이 그리므로 뺍니다."""
        front = style.copy()
        front.shadow = 0
        return front

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

    def _ass_color_tag(self, color: str) -> str:
        c = parse_color(color)
        return f"\\{'3' if self.hollow else '1'}c&H{c.b:02X}{c.g:02X}{c.r:02X}&"

    def body_text(self, text: str, *, accent: bool = True) -> str:
        """사용자 글자를 안전하게 만들고 장식과 `[[...]]` 강조 색을 붙인 이벤트 글자.

        강조는 앞 층에만 넣습니다(`accent=False`면 표기만 뺍니다). 속 빈 글자는 채움이
        투명이라 외곽선 색(\\3c)을 바꿉니다. 색을 되돌리는 명령을 뒤에 붙여 다음 조각이
        원래 색으로 돌아가게 합니다.
        """
        decorated = self.decorate(text)
        if not accent or not self.accent_color:
            return self._with_emoji_font(strip_markup(decorated))
        base = self.outline_color if self.hollow else self.primary_color
        pieces = []
        for piece, highlighted in split_markup(decorated):
            if highlighted:
                pieces.append(
                    "{"
                    + self._ass_color_tag(self.accent_color)
                    + "}"
                    + self._with_emoji_font(piece)
                    + "{"
                    + self._ass_color_tag(base)
                    + "}"
                )
            else:
                pieces.append(self._with_emoji_font(piece))
        return "".join(pieces)

    def _with_emoji_font(self, text: str) -> str:
        """이모지 구간에 흑백 이모지 글꼴을 붙입니다. libass는 컬러 이모지를 못 그립니다.

        글꼴 대체에 맡기면 어떤 글꼴이 걸릴지 알 수 없어(픽셀 글꼴의 이모지가 나오기도
        합니다) 구간마다 명시합니다. 글꼴 이름은 검증돼 있어 명령에 넣어도 안전합니다.
        """
        pieces = []
        for piece, emoji in split_emoji(text):
            if emoji:
                pieces.append(
                    f"{{\\fn{EMOJI_FONT}}}" + plain_ass(piece) + f"{{\\fn{self.font_name}}}"
                )
            else:
                pieces.append(plain_ass(piece))
        return "".join(pieces)

    def event_text_layers(self, text: str) -> list[tuple[int, str, str]]:
        """(layer, 이벤트 글자, 스타일 접미사) 목록. 뒤 층이 먼저 옵니다.

        접미사는 "" (앞 층), "-Back" (바깥 테두리·번짐), "-Extrude" (입체 돌출)입니다.
        글로우는 뒤 층에만 붙여 앞 층 글자는 또렷하게 둡니다.
        """
        front = self.body_text(text)
        if not self.layered:
            return [(0, self.override_tags() + front, "")]
        plain = self.body_text(text, accent=False)
        layers: list[tuple[int, str, str]] = []
        layer = 0
        for depth in range(self.extrude, 0, -1):
            tags = f"{{\\shad0\\xshad{depth}\\yshad{depth}}}"
            layers.append((layer, tags + plain, "-Extrude"))
            layer += 1
        if self.has_back_layer:
            layers.append((layer, self.override_tags() + plain, "-Back"))
            layer += 1
        layers.append((layer, front, ""))
        return layers

    def decorate(self, text: str) -> str:
        """장식을 붙입니다. 여러 줄이면 첫 줄 앞과 마지막 줄 뒤에만 붙입니다."""
        if self.prefix:
            text = f"{self.prefix} {text}"
        if self.suffix:
            text = f"{text} {self.suffix}"
        return text

    def event_text(self, text: str) -> str:
        """한 겹일 때의 이벤트 글자(명령 + 본문)."""
        return self.override_tags() + self.body_text(text)

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
            box_radius=8,
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
            outline2=4,
            outline2_color="#FFFFFF",
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
            outline=5,
            outline2=4,
            outline2_color="#FFFFFF",
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
            outline=5,
            outline2=2.5,
            outline2_color="#3FA9E8",
            shadow=0,
            suffix="♡",
        ),
        _builtin(
            name="bubble-pink",
            label="말풍선 핑크",
            description="핑크 통통 글자에 흰 외곽선.",
            sample="[[딸기]]말차라떼",
            category="cute",
            font_name="Bagel Fat One",
            font_size=78,
            primary_color="#8FD48A",
            outline_color="#FFFFFF",
            outline=5,
            outline2=2.5,
            outline2_color="#E84393",
            shadow=0,
            accent_color="#FF9BD2",
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
            font_name="Cafe24 Ssurround",
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
            name="neon-hollow-pink",
            label="속 빈 네온 핑크",
            description="글자 속을 비우고 핑크 선만 빛나게. 네온사인 간판 느낌.",
            sample="제발... 제발!!!!!",
            category="neon",
            font_name="Gaegu",
            font_size=88,
            bold=True,
            outline_color="#FF5FE0",
            outline=3,
            shadow=0,
            glow=8,
            hollow=True,
        ),
        _builtin(
            name="neon-hollow-round",
            label="속 빈 네온 둥글",
            description="써라운드 글자 속을 비우고 연핑크 선이 번지게.",
            sample="둥글둥글 귀엽다",
            category="neon",
            font_name="Cafe24 Ssurround",
            font_size=88,
            outline_color="#FFB3F0",
            outline=4,
            shadow=0,
            glow=6,
            hollow=True,
            suffix="♡",
        ),
        _builtin(
            name="neon-hollow-lime",
            label="속 빈 네온 라임",
            description="잘난체 속 빈 글자에 연두 선이 빛나게. 강조에.",
            sample="파워 충전 완료",
            category="neon",
            font_name="Jalnan",
            font_size=84,
            outline_color="#B8FF5A",
            outline=3,
            shadow=0,
            glow=7,
            hollow=True,
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
            font_name="Jalnan",
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
            font_name="Cafe24 Ssurround",
            font_size=52,
            primary_color="#3A2A3A",
            border_style="box-outline",
            box_radius=14,
            outline2=3,
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
            box_radius=12,
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
            box_radius=12,
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
            box_radius=12,
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
            box_radius=16,
            outline2=3,
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
            font_name="Gmarket Sans",
            font_size=56,
            primary_color="#111111",
            border_style="box-outline",
            box_radius=10,
            outline2=3,
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
            box_radius=10,
            box_color="#262626",
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
            font_name="Cafe24 Ssurround",
            font_size=48,
            primary_color="#1A1A1A",
            border_style="box",
            box_radius=18,
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
            primary_color="#FFB74D",
            outline_color="#5D2E00",
            outline=3,
            outline2=3,
            outline2_color="#FFF3E0",
            shadow=0,
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
        # ---- 추가: 새 글꼴로 만든 것 ------------------------------------------
        _builtin(
            name="clean-white",
            label="깔끔한 흰색",
            description="선플라워 굵은 글자에 얇은 검은 외곽선. 담백한 기본 자막.",
            sample="오늘의 브이로그 시작!",
            category="basic",
            font_name="Sunflower",
            font_size=64,
            bold=True,
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="title-sticker",
            label="스티커 제목",
            description="가속 굵은 제목에 검은 선과 흰 테두리. 썸네일용 스티커 느낌.",
            sample="썸네일용으로 진짜 딱임!!",
            category="vlog",
            font_name="Gasoek One",
            font_size=84,
            outline_color="#111111",
            outline=4,
            outline2=5,
            outline2_color="#FFFFFF",
            shadow=0,
        ),
        _builtin(
            name="pink-sticker",
            label="핑크 스티커",
            description="핑크 굵은 글자에 흰 선과 진핑크 테두리.",
            sample="올영 세일템 추천",
            category="vlog",
            font_name="Gasoek One",
            font_size=84,
            primary_color="#FF6FB5",
            outline_color="#FFFFFF",
            outline=4,
            outline2=3,
            outline2_color="#C2185B",
            shadow=0,
            suffix="✦",
        ),
        _builtin(
            name="solid-shadow",
            label="입체 그림자",
            description="노란 굵은 글자 뒤에 진갈색 그림자를 길게. 입체 스티커.",
            sample="이건 꼭 사야만 함.. 💗",
            category="vlog",
            font_name="Gasoek One",
            font_size=84,
            primary_color="#FFD54F",
            outline_color="#3E2723",
            back_color="#3E2723",
            outline=3,
            shadow=7,
            suffix="♡",
        ),
        _builtin(
            name="playful-tilt",
            label="장난스러운 기울임",
            description="기랑해랑 글꼴을 살짝 기울여 노란 글자로. 장난스러운 강조.",
            sample="이게 무슨 일이야...",
            category="cute",
            font_name="Kirang Haerang",
            font_size=88,
            primary_color="#FFF176",
            outline_color="#000000",
            outline=3,
            shadow=0,
            angle=-3,
        ),
        _builtin(
            name="lilac-sticker",
            label="라일락 스티커",
            description="연성 글꼴에 연보라 글자, 흰 선과 보라 테두리.",
            sample="너무 귀엽자나...",
            category="cute",
            font_name="Yeon Sung",
            font_size=84,
            primary_color="#E1BEE7",
            outline_color="#FFFFFF",
            outline=5,
            outline2=2.5,
            outline2_color="#8E24AA",
            shadow=0,
            suffix="♡",
        ),
        _builtin(
            name="cute-lemon",
            label="큐트 레몬",
            description="가늘고 귀여운 글꼴에 연노랑 글자.",
            sample="개 느좋 ☆",
            category="cute",
            font_name="Cute Font",
            font_size=104,
            primary_color="#FFF59D",
            outline_color="#5D4037",
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="tilt-sticker",
            label="기울인 스티커",
            description="통통한 흰 글자에 핑크 선, 흰 테두리를 살짝 기울여서.",
            sample="우왕 뽑았다!!!!!",
            category="cute",
            font_name="Bagel Fat One",
            font_size=80,
            outline_color="#FF4081",
            outline=5,
            outline2=4,
            outline2_color="#FFFFFF",
            shadow=0,
            angle=4,
        ),
        _builtin(
            name="cyber-cyan",
            label="사이버 시안",
            description="오르빗 글꼴에 시안 빛 번짐. 게임·테크 느낌.",
            sample="파워 충전 완료",
            category="neon",
            font_name="Orbit",
            font_size=72,
            primary_color="#B2FFFF",
            outline_color="#00BCD4",
            outline=3,
            shadow=0,
            glow=5,
        ),
        _builtin(
            name="news-bar",
            label="뉴스 하단 바",
            description="검정 고딕 흰 글자를 빨간 띠에. 속보·안내 느낌.",
            sample="속보) 다 품절이라고요...?",
            category="box",
            font_name="Gothic A1",
            font_size=48,
            bold=True,
            border_style="box",
            box_color="#C62828",
            outline=10,
            shadow=0,
            margin_vertical_ratio=0.08,
        ),
        _builtin(
            name="brush-shadow",
            label="붓 손글씨 핑크 그림자",
            description="나눔붓 흰 글씨 뒤에 핑크 그림자.",
            sample="여행은 오랜만이라서 떨리네요",
            category="handwriting",
            font_name="Nanum Brush Script",
            font_size=104,
            outline_color="#000000",
            back_color="#FF4081",
            outline=2,
            shadow=4,
        ),
        _builtin(
            name="diary",
            label="일기장 손글씨",
            description="서툰이야기 글꼴 흰 글씨에 얇은 선. 일기 쓰듯.",
            sample="아무도 안 물어봤던 오늘의 TMI",
            category="handwriting",
            font_name="Poor Story",
            font_size=88,
            outline=2,
            shadow=0,
            prefix="✧",
        ),
        _builtin(
            name="brush-red",
            label="붓글씨 빨강",
            description="독도 붓글씨에 빨간 글자와 그림자. 강한 한마디.",
            sample="불타는 고구마;;;;",
            category="handwriting",
            font_name="Dokdo",
            font_size=100,
            primary_color="#FF5252",
            outline_color="#000000",
            outline=2,
            shadow=3,
        ),
        _builtin(
            name="retro-blue-3d",
            label="레트로 블루 입체",
            description="잘난체 하늘색 글자에 흰 선, 남색으로 두껍게 돌출. 레트로 크롬 느낌.",
            sample="완전 레트로 느낌이잖아",
            category="retro",
            font_name="Jalnan",
            font_size=84,
            primary_color="#9BD2FF",
            outline_color="#FFFFFF",
            outline=3,
            shadow=0,
            extrude=8,
            extrude_color="#1B2A6B",
        ),
        _builtin(
            name="pop-yellow-3d",
            label="팝 노랑 입체",
            description="가속 노란 글자에 검은 선, 진갈색 돌출과 별 장식. 팝 스티커.",
            sample="[[#1]] Base 파운데이션",
            category="vlog",
            font_name="Gasoek One",
            font_size=84,
            primary_color="#FFE14D",
            outline_color="#222222",
            outline=3,
            shadow=0,
            extrude=7,
            extrude_color="#5D3A1A",
            accent_color="#7FC8FF",
        ),
        _builtin(
            name="songmyung-cream",
            label="송명 레트로",
            description="송명 세리프에 크림색 글자, 자간 살짝. 옛날 잡지 느낌.",
            sample="완전 레트로 느낌이잖아",
            category="retro",
            font_name="Song Myung",
            font_size=72,
            primary_color="#FFF3E0",
            outline_color="#4E342E",
            outline=2,
            shadow=0,
            letter_spacing=2,
            prefix="✦",
            suffix="✦",
        ),
        _builtin(
            name="elegant-serif",
            label="우아한 세리프",
            description="디필레이아 세리프 흰 글자에 넓은 자간.",
            sample="제 친구 뻔뀐이에요",
            category="retro",
            font_name="Diphylleia",
            font_size=60,
            outline=1,
            shadow=0,
            letter_spacing=4,
            suffix="♡",
        ),
        _builtin(
            name="grandiflora-pink",
            label="그랜디플로라 핑크",
            description="꽃 같은 세리프에 연핑크 글자, 자주 외곽선.",
            sample="고급스러운 느낌",
            category="retro",
            font_name="Grandiflora One",
            font_size=68,
            primary_color="#FCE4EC",
            outline_color="#880E4F",
            outline=2,
            shadow=0,
            suffix="✦",
        ),
        # ---- 추가: 굵고 둥근 썸네일 글씨(잘난체·카페24·지마켓·Pretendard·Wanted) ------
        _builtin(
            name="jalnan-sticker",
            label="잘난체 스티커",
            description="잘난체 흰 글자에 검은 선과 흰 테두리. 썸네일의 정석.",
            sample="썸네일용으로 진짜 딱임!!",
            category="vlog",
            font_name="Jalnan",
            font_size=84,
            outline_color="#111111",
            outline=4,
            outline2=5,
            outline2_color="#FFFFFF",
            shadow=0,
        ),
        _builtin(
            name="jalnan-yellow",
            label="잘난체 노랑",
            description="잘난체 노란 글자에 검은 외곽선. 예능 강조.",
            sample="이거 진짜 맛있다",
            category="vlog",
            font_name="Jalnan",
            font_size=84,
            primary_color="#FFE14D",
            outline_color="#111111",
            outline=4,
            shadow=0,
        ),
        _builtin(
            name="jalnan-pink-sticker",
            label="잘난체 핑크 스티커",
            description="잘난체 핑크 글자에 흰 선과 진핑크 테두리.",
            sample="우왕 뽑았다!!!!!",
            category="cute",
            font_name="Jalnan",
            font_size=84,
            primary_color="#FF6FB5",
            outline_color="#FFFFFF",
            outline=4,
            outline2=2.5,
            outline2_color="#E0117A",
            shadow=0,
        ),
        _builtin(
            name="ssurround-lime",
            label="써라운드 라임",
            description="카페24 써라운드 연두 글자에 진녹 외곽선.",
            sample="셀프 메이크업 완성!",
            category="vlog",
            font_name="Cafe24 Ssurround",
            font_size=84,
            primary_color="#C6FF6B",
            outline_color="#2E5A00",
            outline=3,
            shadow=0,
        ),
        _builtin(
            name="ssurround-sky-sticker",
            label="써라운드 하늘 스티커",
            description="카페24 써라운드 하늘 글자에 흰 선과 파란 테두리.",
            sample="너무 귀여워...",
            category="cute",
            font_name="Cafe24 Ssurround",
            font_size=84,
            primary_color="#9BDBFF",
            outline_color="#FFFFFF",
            outline=5,
            outline2=2.5,
            outline2_color="#2F8FD6",
            shadow=0,
            suffix="♡",
        ),
        _builtin(
            name="ssurround-peach",
            label="써라운드 피치",
            description="카페24 써라운드 살구색 글자에 흰 선과 주황 테두리.",
            sample="[[딸기]]말차라떼 🍓🍵",
            category="cute",
            font_name="Cafe24 Ssurround",
            font_size=84,
            primary_color="#B5E88A",
            outline_color="#FFFFFF",
            outline=5,
            outline2=2.5,
            outline2_color="#E86A2F",
            shadow=0,
            accent_color="#FF9BB0",
        ),
        _builtin(
            name="simplehae-lilac",
            label="심플해 라일락",
            description="카페24 심플해 연보라 글자에 자주 외곽선.",
            sample="헤헿 아닌가보다",
            category="cute",
            font_name="Cafe24 Simplehae",
            font_size=84,
            primary_color="#E8D1FF",
            outline_color="#6A1B9A",
            outline=2,
            shadow=0,
            suffix="☆",
        ),
        _builtin(
            name="gmarket-yellow",
            label="지마켓 노랑",
            description="지마켓 산스 굵은 노란 글자에 검은 외곽선. 깔끔한 예능 자막.",
            sample="이거 진짜 맛있다",
            category="basic",
            font_name="Gmarket Sans",
            font_size=64,
            primary_color="#FFE14D",
            outline_color="#111111",
            outline=3,
            shadow=0,
        ),
        _builtin(
            name="pretendard-clean",
            label="프리텐다드 깔끔",
            description="프리텐다드 블랙 흰 글자에 얇은 외곽선. 정보 전달용.",
            sample="오늘의 브이로그 시작!",
            category="basic",
            font_name="Pretendard",
            font_size=60,
            outline=2,
            shadow=0,
        ),
        _builtin(
            name="wanted-mint-card",
            label="원티드 민트 카드",
            description="원티드 산스 진녹 글자를 연민트 카드에.",
            sample="올영 세일템 추천",
            category="box",
            font_name="Wanted Sans",
            font_size=52,
            primary_color="#1B5E20",
            border_style="box-outline",
            box_radius=14,
            outline2=3,
            box_color="#E0FFF0",
            outline_color="#66BB6A",
            outline=3,
            shadow=0,
            prefix="✳",
            suffix="✳",
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
    style = template.style(height, font_size=font_size)
    add_styles(subs, "Default", template, style)
    for cue in cues:
        lift = 0
        if template.rounded_box:
            anchor_x, anchor_y = _anchor_for(style, template, width, height)
            subs.append(
                pysubs2.SSAEvent(
                    start=round(cue.start * 1000),
                    end=round(cue.end * 1000),
                    layer=0,
                    style="Default-Box",
                    text=rounded_box_text(
                        template,
                        cue.text,
                        style.fontsize,
                        anchor_x=anchor_x,
                        anchor_y=anchor_y,
                        vertical=template.position,
                        horizontal=template.horizontal,
                    ),
                )
            )
            lift = 1
        for layer, text, suffix in template.event_text_layers(cue.text):
            subs.append(
                pysubs2.SSAEvent(
                    start=round(cue.start * 1000),
                    end=round(cue.end * 1000),
                    layer=layer + lift,
                    style=f"Default{suffix}",
                    text=text,
                )
            )
    if title:
        add_styles(subs, "Title", template, template.title_style(height, font_size=font_size))
        # 제목은 영상 전체 동안 보입니다. 자막이 없어도 제목만 보일 수 있습니다.
        # 장식·강조는 대사에만 붙입니다. 제목은 편집기에서 직접 적는 글자입니다.
        plain_title = template.model_copy(update={"prefix": "", "suffix": "", "accent_color": ""})
        lift = 0
        if template.rounded_box:
            title_style = subs.styles["Title"]
            opposite: Position = "bottom" if template.position == "top" else "top"
            anchor_x = (title_style.marginl + width - title_style.marginr) / 2
            anchor_y = float(
                height - title_style.marginv if opposite == "bottom" else title_style.marginv
            )
            subs.append(
                pysubs2.SSAEvent(
                    start=0,
                    end=round(duration * 1000),
                    layer=0,
                    style="Title-Box",
                    text=rounded_box_text(
                        plain_title,
                        title,
                        title_style.fontsize,
                        anchor_x=anchor_x,
                        anchor_y=anchor_y,
                        vertical=opposite,
                        horizontal="center",
                    ),
                )
            )
            lift = 1
        for layer, text, suffix in plain_title.event_text_layers(title):
            subs.append(
                pysubs2.SSAEvent(
                    start=0,
                    end=round(duration * 1000),
                    layer=layer + lift,
                    style=f"Title{suffix}",
                    text=text,
                )
            )
    return subs


def _ass_hex(color: str) -> str:
    c = parse_color(color)
    return f"&H{c.b:02X}{c.g:02X}{c.r:02X}&"


def _ass_alpha(color: str) -> str:
    return f"&H{parse_color(color).a:02X}&"


def rounded_rect_path(width: float, height: float, radius: float) -> str:
    """ASS 벡터 그리기 명령으로 된 둥근 사각형(왼쪽 위가 0,0). 모서리는 베지어 곡선입니다."""
    r = max(0.0, min(radius, width / 2, height / 2))
    k = 0.5523 * r  # 원호를 3차 베지어로 근사하는 상수
    w, h = width, height

    def f(v: float) -> str:
        return f"{v:.1f}".rstrip("0").rstrip(".")

    return (
        f"m {f(r)} 0 l {f(w - r)} 0 "
        f"b {f(w - r + k)} 0 {f(w)} {f(r - k)} {f(w)} {f(r)} "
        f"l {f(w)} {f(h - r)} "
        f"b {f(w)} {f(h - r + k)} {f(w - r + k)} {f(h)} {f(w - r)} {f(h)} "
        f"l {f(r)} {f(h)} "
        f"b {f(r - k)} {f(h)} 0 {f(h - r + k)} 0 {f(h - r)} "
        f"l 0 {f(r)} "
        f"b 0 {f(r - k)} {f(r - k)} 0 {f(r)} 0"
    )


def rounded_box_text(
    template: SubtitleTemplate,
    text: str,
    font_size: int,
    *,
    anchor_x: float,
    anchor_y: float,
    vertical: Position,
    horizontal: Horizontal,
) -> str:
    """글자 뒤에 놓는 둥근 상자 이벤트의 글자(명령 + 벡터 경로).

    `anchor`는 글자가 정렬되는 점(libass가 글자 상자를 맞추는 점)입니다. 글자 폭·높이를
    재서 그 둘레에 `outline`만큼 여백을 두고, `outline2`가 있으면 테두리를 두릅니다.
    """
    lines = strip_markup(template.decorate(text)).split("\n") or [""]
    sizes = [
        measure_text(
            line,
            template.font_name,
            font_size,
            letter_spacing=template.letter_spacing,
            bold=template.bold,
        )
        for line in lines
    ]
    text_width = max(size.width for size in sizes)
    text_height = sum(size.line_height for size in sizes)
    pad = template.outline
    width, height = text_width + 2 * pad, text_height + 2 * pad
    left = {
        "left": anchor_x - pad,
        "center": anchor_x - width / 2,
        "right": anchor_x - width + pad,
    }[horizontal]
    top = {
        "top": anchor_y - pad,
        "middle": anchor_y - height / 2,
        "bottom": anchor_y - height + pad,
    }[vertical]
    border = template.outline2 if template.border_style == "box-outline" else 0
    tags = (
        f"\\pos({left:.0f},{top:.0f})\\an7\\p1\\shad0"
        f"\\1c{_ass_hex(template.box_color)}\\1a{_ass_alpha(template.box_color)}"
        f"\\3c{_ass_hex(template.outline_color)}\\bord{border:g}"
    )
    if template.angle:
        tags += f"\\frz{template.angle:g}"
    return "{" + tags + "}" + rounded_rect_path(width, height, template.box_radius)


def _anchor_for(style: pysubs2.SSAStyle, template: SubtitleTemplate, width: int, height: int):
    """스타일의 정렬·여백에서 libass가 글자를 맞추는 점을 구합니다."""
    x = {
        "left": float(style.marginl),
        "center": (style.marginl + width - style.marginr) / 2,
        "right": float(width - style.marginr),
    }[template.horizontal]
    y = {
        "top": float(style.marginv),
        "middle": height / 2,
        "bottom": float(height - style.marginv),
    }[template.position]
    return x, y


def add_styles(
    subs: pysubs2.SSAFile, name: str, template: SubtitleTemplate, style: pysubs2.SSAStyle
) -> None:
    """스타일을 등록합니다. 여러 겹이면 `<name>-Back`, `<name>-Extrude`도 함께 넣습니다."""
    if template.rounded_box:
        # 상자 그리기용 스타일. 색·크기는 이벤트 명령이 정하므로 정렬만 둡니다.
        box = pysubs2.SSAStyle(outline=0, shadow=0, alignment=pysubs2.Alignment.TOP_LEFT)
        box.marginl = box.marginr = box.marginv = 0
        subs.styles[f"{name}-Box"] = box
    if not template.layered:
        subs.styles[name] = style
        return
    if template.extrude > 0:
        subs.styles[f"{name}-Extrude"] = template.extrude_style(style)
    if template.has_back_layer:
        subs.styles[f"{name}-Back"] = template.back_style(style)
    subs.styles[name] = template.front_style(style)


# ---------------------------------------------------------------- 미리보기 시트

SHEET_WIDTH = 1080
SHEET_COLUMNS = 2
SHEET_ROW_HEIGHT = 170
SHEET_PADDING = 40
SHEET_HEADER = 120
SHEET_CATEGORY_HEIGHT = 80
SHEET_BACKGROUND_STARS = 70


# 글꼴마다 글자 폭이 다릅니다. 손글씨·가는 글꼴은 좁아서 같은 크기라도 작아 보이므로
# 시트에서 더 크게 맞춥니다. 값은 한글 한 자의 폭을 em으로 어림한 것입니다.
FONT_WIDTH_FACTORS: dict[str, float] = {
    "Dongle": 0.6,
    "Cute Font": 0.6,
    "Nanum Pen": 0.82,
    "Nanum Brush Script": 0.85,
    "Poor Story": 0.85,
    "Hi Melody": 0.85,
    "Gaegu": 0.85,
    "Gamja Flower": 0.8,
    "East Sea Dokdo": 0.8,
    "Dokdo": 0.85,
    "Kirang Haerang": 0.9,
    "Single Day": 0.9,
    "Diphylleia": 0.95,
    "Black Han Sans": 1.05,
    "Gasoek One": 1.05,
    "Jalnan": 1.05,
    "Cafe24 Ssurround": 1.0,
    "Cafe24 Simplehae": 0.95,
    "Gmarket Sans": 1.05,
    "Pretendard": 1.0,
    "Wanted Sans": 1.0,
}


def estimate_em_width(text: str, font_name: str = "") -> float:
    """글자 폭을 em으로 어림합니다.

    한글·기호 1em, 라틴 대문자·숫자 0.7em, 소문자 0.55em, 공백 0.35em에 글꼴 폭 계수를
    곱합니다. 실제 렌더 폭은 재지 않습니다. 시트에서 칸을 넘치지 않게 하는 용도입니다.
    """
    total = 0.0
    for char in text:
        if char == " ":
            total += 0.35
        elif text_width(char) >= 1.0 or unicodedata.east_asian_width(char) == "A":
            total += 1.0
        elif char.isupper() or char.isdigit():
            total += 0.7
        else:
            total += 0.55
    return total * FONT_WIDTH_FACTORS.get(font_name, 1.0)


def _fit_font_size(
    template: SubtitleTemplate, shown: str, cell_width: float, row_height: int
) -> int:
    """칸에 들어가는 글자 크기. 자간과 외곽선 두께도 뺍니다."""
    border = 2 * (template.outline + template.outline2) + 24
    # 어림이므로 6%를 여유로 둡니다. 넘치면 옆 칸을 침범해 시트가 못 쓰게 됩니다.
    usable = max(cell_width - border, 40) * 0.94
    spacing = template.letter_spacing * max(len(shown) - 1, 0)
    estimate = (usable - spacing) / max(estimate_em_width(shown, template.font_name), 1.0)
    fit = int(min(template.font_size, estimate, row_height * 0.62))
    return max(24, fit)


def sheet_document(
    templates: list[SubtitleTemplate],
    *,
    width: int = SHEET_WIDTH,
    columns: int = SHEET_COLUMNS,
    row_height: int = SHEET_ROW_HEIGHT,
    text: str | None = None,
    title: str = "자막 템플릿",
    grouped: bool = True,
    stars: int = SHEET_BACKGROUND_STARS,
    layout: Literal["grid", "flow"] = "grid",
) -> tuple[pysubs2.SSAFile, int]:
    """템플릿마다 예문 한 줄을 격자에 놓은 ASS 문서와 필요한 화면 높이를 돌려줍니다.

    한 프레임으로 렌더하면 인스타그램 소개 이미지 같은 한 장짜리 시트가 됩니다.
    `layout="grid"`는 같은 크기 칸에 하나씩, `"flow"`는 글자 폭을 재서 한 줄에 들어가는
    만큼 채워 넣습니다(참고 이미지처럼 빽빽하고 글자가 큽니다).
    템플릿마다 스타일을 만들고(두 겹이면 둘) `\\pos`로 칸 가운데에 둡니다. 글자
    크기는 칸에 맞춰 줄입니다. `grouped`면 카테고리가 바뀔 때 구분 줄을 넣고,
    `stars`만큼 흐린 별을 배경에 흩어 놓습니다(같은 자리에 늘 같게 나오도록 고정 씨앗).
    """
    if not templates:
        raise ValueError("시트에 넣을 템플릿이 없습니다.")
    if columns < 1 or width < 200:
        raise ValueError("열 수는 1 이상, 너비는 200 이상이어야 합니다.")
    cell_width = (width - 2 * SHEET_PADDING) / columns
    if grouped:
        # 카테고리 순서로 묶습니다(같은 카테고리 안에서는 받은 순서 유지).
        order = list(CATEGORY_LABELS)
        templates = sorted(templates, key=lambda t: order.index(t.category))

    subs = pysubs2.SSAFile()
    subs.info.update(PlayResX=str(width), WrapStyle="2")
    subs.styles["Header"] = pysubs2.SSAStyle(
        fontname="Noto Sans CJK KR",
        fontsize=44,
        bold=True,
        primarycolor=pysubs2.Color(255, 255, 255, 0),
        outline=0,
        shadow=0,
        alignment=pysubs2.Alignment.MIDDLE_CENTER,
    )
    subs.styles["Category"] = pysubs2.SSAStyle(
        fontname="Noto Sans CJK KR",
        fontsize=30,
        bold=True,
        primarycolor=pysubs2.Color(255, 141, 199, 0),
        outlinecolor=pysubs2.Color(60, 20, 45, 0),
        outline=0,
        shadow=0,
        spacing=2,
        alignment=pysubs2.Alignment.MIDDLE_CENTER,
    )
    subs.styles["Star"] = pysubs2.SSAStyle(
        fontname="Noto Sans CJK KR",
        fontsize=34,
        primarycolor=pysubs2.Color(70, 58, 66, 0),
        outline=0,
        shadow=0,
        alignment=pysubs2.Alignment.MIDDLE_CENTER,
    )
    events: list[pysubs2.SSAEvent] = []
    events.append(
        pysubs2.SSAEvent(
            start=0,
            end=1000,
            layer=1,
            style="Header",
            text=f"{{\\pos({width / 2:.0f},{SHEET_HEADER / 2:.0f})}}"
            + plain_ass(f"{title} · {len(templates)}종"),
        )
    )
    y = SHEET_HEADER
    column = 0
    current_category: str | None = None
    placements: list[tuple[int, SubtitleTemplate, str, int, float, float]] = []
    flow_row: list[tuple[int, SubtitleTemplate, str, int, float, float]] = []
    flow_width = 0.0
    flow_height = 0.0
    usable = width - 2 * SHEET_PADDING
    gap = 36

    def flush_flow() -> None:
        """모아 둔 한 줄을 가운데 정렬로 확정합니다."""
        nonlocal y, flow_row, flow_width, flow_height
        if not flow_row:
            return
        x = SHEET_PADDING + (usable - flow_width) / 2
        for index, template, sample, fit, item_w, _ in flow_row:
            placements.append((index, template, sample, fit, x + item_w / 2, y + flow_height / 2))
            x += item_w + gap
        y += flow_height
        flow_row, flow_width, flow_height = [], 0.0, 0.0

    for index, template in enumerate(templates):
        if grouped and template.category != current_category:
            if layout == "flow":
                flush_flow()
            elif column:
                y += row_height
                column = 0
            current_category = template.category
            label = CATEGORY_LABELS[template.category]
            events.append(
                pysubs2.SSAEvent(
                    start=0,
                    end=1000,
                    layer=1,
                    style="Category",
                    text=f"{{\\pos({width / 2:.0f},{y + SHEET_CATEGORY_HEIGHT / 2:.0f})}}"
                    + plain_ass(f"— {label} —"),
                )
            )
            y += SHEET_CATEGORY_HEIGHT
        sample = text or template.sample or template.label
        shown = strip_markup(template.decorate(sample))
        if layout == "flow":
            # 글자 폭을 재서 한 줄에 들어가는 만큼 채웁니다. 크기는 템플릿 값에 가깝게 둡니다.
            fit = min(template.font_size, 48)
            extra = 2 * (template.outline + template.outline2) + 2 * template.extrude + 16
            size = measure_text(
                shown, template.font_name, fit, letter_spacing=template.letter_spacing
            )
            item_w = size.width + extra
            if item_w > usable:
                fit = max(24, int(fit * usable / item_w))
                size = measure_text(
                    shown, template.font_name, fit, letter_spacing=template.letter_spacing
                )
                item_w = size.width + extra
            item_h = size.line_height + 2 * (template.outline + template.outline2) + 28
            if flow_row and flow_width + gap + item_w > usable:
                flush_flow()
            flow_width += (gap if flow_row else 0) + item_w
            flow_height = max(flow_height, item_h)
            flow_row.append((index, template, sample, fit, item_w, item_h))
            continue
        fit = _fit_font_size(template, shown, cell_width, row_height)
        x = SHEET_PADDING + cell_width * (column + 0.5)
        cy = y + row_height / 2
        placements.append((index, template, sample, fit, x, cy))
        column += 1
        if column == columns:
            column = 0
            y += row_height
    if layout == "flow":
        flush_flow()
    elif column:
        y += row_height

    for index, template, sample, fit, x, cy in placements:
        style = template.style(SHEET_ROW_HEIGHT, font_size=fit)
        style.alignment = pysubs2.Alignment.MIDDLE_CENTER
        style.marginl = style.marginr = style.marginv = 0
        name = f"T{index}"
        add_styles(subs, name, template, style)
        lift = 1
        if template.rounded_box:
            events.append(
                pysubs2.SSAEvent(
                    start=0,
                    end=1000,
                    layer=1,
                    style=f"{name}-Box",
                    text=rounded_box_text(
                        template,
                        sample,
                        fit,
                        anchor_x=x,
                        anchor_y=cy,
                        vertical="middle",
                        horizontal="center",
                    ),
                )
            )
            lift = 2
        for layer, body, suffix in template.event_text_layers(sample):
            events.append(
                pysubs2.SSAEvent(
                    start=0,
                    end=1000,
                    layer=layer + lift,
                    style=f"{name}{suffix}",
                    text=f"{{\\pos({x:.0f},{cy:.0f})}}" + body,
                )
            )
    height = int(round(y)) + SHEET_PADDING
    height += height % 2
    subs.info["PlayResY"] = str(height)

    # 배경 별. 글자 뒤(layer 0)에 두고 씨앗을 고정해 렌더마다 같은 자리에 나옵니다.
    rng = random.Random(4)
    for _ in range(max(0, stars)):
        sx, sy = rng.uniform(10, width - 10), rng.uniform(SHEET_HEADER, height - 10)
        glyph = rng.choice("★★☆✦")
        size = rng.randint(22, 40)
        subs.append(
            pysubs2.SSAEvent(
                start=0,
                end=1000,
                layer=0,
                style="Star",
                text=f"{{\\pos({sx:.0f},{sy:.0f})\\fs{size}}}{glyph}",
            )
        )
    for event in events:
        subs.append(event)
    return subs, height
