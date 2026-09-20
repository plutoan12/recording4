"""글자 폭·줄 높이 재기. 둥근 상자를 글자 뒤에 그릴 때 크기를 정하는 데 씁니다.

libass는 글자를 그리고 나서야 크기를 알기 때문에 ASS 문서를 만드는 시점에는 폭을 직접
계산해야 합니다. 설치된 글꼴 파일을 fontTools로 열어 글자마다 advance 폭을 더하면
libass가 그리는 폭과 거의 같습니다(커닝은 무시합니다. 한글 글꼴은 대개 커닝이 없습니다).

글꼴 파일은 `R4_FONTS_DIR`(로컬)이나 fontconfig(`fc-match`, 워커 이미지)로 찾습니다.
fontTools나 글꼴 파일이 없으면 글꼴별 폭 계수로 어림한 값을 돌려주고 `measured=False`로
알립니다. 그러면 상자가 글자와 조금 어긋날 수 있습니다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

FONT_SUFFIXES = (".ttf", ".otf")


@dataclass(frozen=True, slots=True)
class TextSize:
    width: float
    line_height: float
    measured: bool  # False면 어림값입니다.


def _fonts_dir() -> Path | None:
    value = os.environ.get("R4_FONTS_DIR", "").strip()
    return Path(value) if value else None


def _families_of(path: Path) -> set[str]:
    """파일 안의 family 이름들. fontTools가 없으면 빈 집합입니다."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return set()
    try:
        font = TTFont(str(path), lazy=True)
        names = {r.toUnicode().strip() for r in font["name"].names if r.nameID in (1, 16)}
        font.close()
        return names
    except Exception:  # noqa: BLE001 - 깨진 파일은 후보에서 뺍니다.
        return set()


@lru_cache(maxsize=64)
def font_file_for(family: str) -> Path | None:
    """이 family 이름의 글꼴 파일. 로컬 디렉터리를 먼저, 다음에 fontconfig를 봅니다."""
    directory = _fonts_dir()
    if directory and directory.is_dir():
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() in FONT_SUFFIXES and family in _families_of(path):
                return path
    binary = shutil.which("fc-match")
    if not binary:
        return None
    # 하이픈이 든 이름을 크기로 오해하지 않도록 `:family=` 꼴로 묻습니다.
    completed = subprocess.run(
        [binary, "--format", "%{file}|%{family}", f":family={family}"],
        capture_output=True,
        text=True,
    )
    if completed.returncode or "|" not in completed.stdout:
        return None
    file, families = completed.stdout.split("|", 1)
    # fc-match는 없는 이름에도 기본 글꼴을 돌려줍니다. 이름이 정말 맞을 때만 씁니다.
    if family not in [name.strip() for name in families.split(",")]:
        return None
    return Path(file)


@lru_cache(maxsize=32)
def _metrics(path: Path) -> tuple[dict[int, int], int, float] | None:
    """(문자 → advance, unitsPerEm, 줄 높이 비율). 열지 못하면 None."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        font = TTFont(str(path), lazy=True)
        cmap = font.getBestCmap() or {}
        hmtx = font["hmtx"]
        upm = font["head"].unitsPerEm
        hhea = font["hhea"]
        line = (hhea.ascent - hhea.descent) / upm
        advances = {code: hmtx[name][0] for code, name in cmap.items()}
        font.close()
        return advances, upm, line
    except Exception:  # noqa: BLE001
        return None


def measure_text(
    text: str, family: str, size: float, *, letter_spacing: float = 0, bold: bool = False
) -> TextSize:
    """한 줄 글자의 폭과 줄 높이(px). 글꼴이 없으면 어림합니다."""
    from pipeline.subtitle_templates import estimate_em_width

    path = font_file_for(family)
    metrics = _metrics(path) if path else None
    if metrics is None:
        return TextSize(
            width=estimate_em_width(text, family) * size + letter_spacing * max(len(text) - 1, 0),
            line_height=size * 1.2,
            measured=False,
        )
    advances, upm, line = metrics
    fallback = int(upm * 0.9)
    units = sum(advances.get(ord(char), fallback) for char in text)
    width = units / upm * size + letter_spacing * max(len(text) - 1, 0)
    if bold:
        # libass의 합성 굵기는 글자를 조금 넓힙니다. 글꼴 자체가 굵으면 차이가 없습니다.
        width *= 1.02
    return TextSize(width=width, line_height=line * size, measured=True)
