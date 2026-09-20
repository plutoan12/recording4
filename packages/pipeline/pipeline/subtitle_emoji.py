"""컬러 이모지: COLR 글꼴의 색 층을 libass가 그릴 수 있는 글자 겹침으로 바꿉니다.

libass는 컬러 이모지 글꼴(CBDT 비트맵, COLR 층, SVG)을 그리지 못하고 윤곽선 글리프만
그립니다. 대신 COLRv0 글꼴(Twemoji Mozilla)의 색 층 하나하나가 보통 윤곽선 글리프라는
점을 씁니다. 글꼴을 만들 때(`build_color_emoji_font`) 층 글리프마다 사용자 영역 코드를
붙이고 advance 폭을 0으로 만든 뒤, 자막 글자에서는 이모지 하나를

    {\\1c&H색1&}층1{\\1c&H색2&}층2 ... 층n 자리표

로 씁니다. 층은 폭이 0이라 같은 자리에 겹쳐 그려지고(libass는 채움을 글자 순서대로
칠합니다), 마지막 자리표 글리프(윤곽선 없음, 1em 폭)가 자리를 차지합니다. 결과는 보통
글자와 같은 경로로 그려지므로 외곽선·글로우·움직임·타자기 등이 모두 그대로 먹습니다.

만든 글꼴 옆의 JSON(`R4ColorEmoji.json`)이 코드포인트(열)를 층 목록으로 바꾸는 표입니다.
표가 없으면(컬러 이모지를 설치하지 않은 환경) 흑백 Noto Emoji로 그립니다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pipeline.subtitle_fonts import COLOR_EMOJI_FONT, COLOR_EMOJI_MAP, DEFAULT_FONTS_DIR

__all__ = [
    "ColorEmoji",
    "build_color_emoji_font",
    "color_emoji_map",
    "expand_color_emoji",
    "is_layer_group",
    "layer_group_pattern",
]

# 층 글리프와 자리표에 붙이는 사용자 영역(15번 평면). 보통 글꼴은 이 영역에 글자가 없습니다.
PUA_START = 0xF0000
PUA_END = 0xFFFFD
# 조합 이모지(국기·직업·가족·피부색)의 최대 코드포인트 수.
MAX_SEQUENCE = 10
# 자막에 넣을 때 무시하는 결합 문자. 표에 조합이 없으면 낱개로 그립니다.
_JOINERS = {0x200D, 0xFE0F, 0xFE0E}


@dataclass(frozen=True)
class ColorEmoji:
    layers: tuple[tuple[str, str], ...]  # (층 글자, #RRGGBB 또는 #RRGGBBAA)
    spacer: str  # 자리표 글자(1em 폭, 윤곽선 없음)


# ---------------------------------------------------------------- 글꼴 만들기


def build_color_emoji_font(data: bytes, family: str = COLOR_EMOJI_FONT) -> tuple[bytes, dict]:
    """COLRv0 이모지 글꼴에서 (겹침용 TTF, 코드포인트 표)를 만듭니다. fontTools가 필요합니다.

    - 층 글리프: 사용자 영역 코드를 붙이고 advance를 0으로.
    - 바탕 글리프(이모지 자체, 조합 이모지의 합자 글리프): 윤곽선을 비우고 1em 폭의 자리표로.
    - COLR·CPAL·GSUB는 표로 옮겼으므로 뺍니다. 이름은 `family`로 바꿉니다.
    """
    import io

    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables import _c_m_a_p, _g_l_y_f

    try:
        font = TTFont(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - fontTools 오류 종류가 여럿입니다.
        raise ValueError(f"글꼴 파일을 열지 못했습니다: {exc}") from None
    if "COLR" not in font or "CPAL" not in font or font["COLR"].version != 0:
        raise ValueError("COLRv0 색 층이 있는 글꼴이어야 합니다.")
    layers_of = font["COLR"].ColorLayers
    palette = font["CPAL"].palettes[0]
    cmap = font.getBestCmap()
    reverse = {name: code for code, name in cmap.items()}
    hmtx = font["hmtx"]
    glyf = font["glyf"]
    upm = font["head"].unitsPerEm

    # 조합 이모지: GSUB 합자(ccmp)를 코드포인트 열로 풉니다. 한 단계 합자만 봅니다.
    sequences: dict[tuple[int, ...], str] = {}
    if "GSUB" in font:
        for lookup in font["GSUB"].table.LookupList.Lookup:
            for subtable in lookup.SubTable:
                for first, ligatures in getattr(subtable, "ligatures", {}).items():
                    for ligature in ligatures:
                        names = [first, *ligature.Component]
                        if all(name in reverse for name in names):
                            key = tuple(reverse[name] for name in names)
                            sequences[key] = ligature.LigGlyph

    codes: dict[str, int] = {}
    next_code = PUA_START

    def assign(name: str) -> int:
        nonlocal next_code
        if name not in codes:
            if next_code > PUA_END:
                raise ValueError("사용자 영역이 모자랍니다.")
            codes[name] = next_code
            next_code += 1
        return codes[name]

    def color_of(index: int) -> str:
        color = palette[index]
        text = f"#{color.red:02X}{color.green:02X}{color.blue:02X}"
        return text if color.alpha == 255 else f"{text}{color.alpha:02X}"

    table: dict[str, dict] = {}
    bases: set[str] = set()
    layer_names: set[str] = set()

    def register(key: tuple[int, ...], base: str) -> None:
        layers = layers_of.get(base)
        if not layers:
            return
        entry = {
            "layers": [[chr(assign(layer.name)), color_of(layer.colorID)] for layer in layers],
            "spacer": chr(assign(base)),
        }
        table["-".join(f"{code:x}" for code in key)] = entry
        bases.add(base)
        layer_names.update(layer.name for layer in layers)

    for code, name in sorted(cmap.items()):
        register((code,), name)
    for key, name in sorted(sequences.items()):
        register(key, name)

    for name in layer_names:
        hmtx[name] = (0, hmtx[name][1])
    for name in bases:
        hmtx[name] = (upm, 0)
        glyf[name] = _g_l_y_f.Glyph()
    # 사용자 영역은 4바이트 cmap(format 12)에 넣습니다.
    subtable = _c_m_a_p.CmapSubtable.newSubtable(12)
    subtable.platformID, subtable.platEncID, subtable.language = 3, 10, 0
    subtable.cmap = {code: name for name, code in codes.items()}
    font["cmap"].tables = [subtable]
    for tag in ("COLR", "CPAL", "GSUB", "GDEF"):
        if tag in font:
            del font[tag]
    name_table = font["name"]
    for record in list(name_table.names):
        if record.nameID in (1, 3, 4, 6, 16):
            name_table.removeNames(nameID=record.nameID)
    name_table.setName(family, 1, 3, 1, 0x409)
    name_table.setName("Regular", 2, 3, 1, 0x409)
    name_table.setName(f"{family};Regular", 3, 3, 1, 0x409)
    name_table.setName(family, 4, 3, 1, 0x409)
    name_table.setName(family.replace(" ", "") + "-Regular", 6, 3, 1, 0x409)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue(), {"version": 1, "family": family, "emoji": table}


# ---------------------------------------------------------------- 자막에 넣기


def _map_path() -> Path | None:
    explicit = os.environ.get("R4_EMOJI_MAP", "").strip()
    if explicit:
        return Path(explicit)
    for directory in (os.environ.get("R4_FONTS_DIR", "").strip(), DEFAULT_FONTS_DIR):
        if directory and (Path(directory) / COLOR_EMOJI_MAP).is_file():
            return Path(directory) / COLOR_EMOJI_MAP
    return None


@lru_cache(maxsize=4)
def _load_map(path: Path) -> dict[str, ColorEmoji]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if raw.get("version") != 1:
        return {}
    table: dict[str, ColorEmoji] = {}
    for key, entry in raw.get("emoji", {}).items():
        table[key] = ColorEmoji(
            layers=tuple((glyph, color) for glyph, color in entry["layers"]),
            spacer=entry["spacer"],
        )
    return table


def color_emoji_map() -> dict[str, ColorEmoji]:
    """설치된 컬러 이모지 표. 없으면 빈 dict(흑백으로 그립니다)."""
    path = _map_path()
    return _load_map(path.resolve()) if path else {}


def _key(codes: tuple[int, ...]) -> str:
    return "-".join(f"{code:x}" for code in codes)


def _ass_color(color: str) -> str:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    tags = f"\\1c&H{b:02X}{g:02X}{r:02X}&"
    if len(color) == 9:
        tags += f"\\1a&H{255 - int(color[7:9], 16):02X}&"
    return tags


def expand_color_emoji(
    run: str, table: dict[str, ColorEmoji], *, restore: str
) -> tuple[str, str] | None:
    """이모지 구간을 (ASS 글자, 자리표 글자열)로 바꿉니다. 하나도 못 바꾸면 None.

    구간 안에서 표에 있는 가장 긴 조합부터 찾고, 없으면 낱개로, 그래도 없으면 그 글자는
    그대로(흑백 글꼴 대체) 둡니다. `restore`는 이모지 뒤에 되돌릴 색 명령입니다. 자리표
    글자열은 폭을 잴 때 씁니다(자리표 하나가 1em).
    """
    if not table:
        return None
    codes = [ord(char) for char in run]
    out: list[str] = []
    spacers: list[str] = []
    found = False
    index = 0
    while index < len(codes):
        match = None
        for length in range(min(MAX_SEQUENCE, len(codes) - index), 0, -1):
            candidate = tuple(codes[index : index + length])
            entry = table.get(_key(candidate))
            if entry is None and length == 1 and candidate[0] in _JOINERS:
                match = ("", 1)
                break
            if entry is not None:
                match = (entry, length)
                break
        if match is None:
            out.append(chr(codes[index]))
            index += 1
            continue
        entry, length = match
        index += length
        if entry == "":
            continue
        found = True
        out.append(
            "".join("{" + _ass_color(color) + "}" + glyph for glyph, color in entry.layers)
            + entry.spacer
        )
        spacers.append(entry.spacer)
    if not found:
        return None
    return "".join(out) + "{" + restore + "}", "".join(spacers)


_PUA = f"[{chr(PUA_START)}-{chr(PUA_END)}]"


def layer_group_pattern() -> str:
    """겹침 한 묶음(층마다 색 명령 + 층 글자, 끝에 자리표)을 잡는 정규식."""
    return rf"(?:\{{[^{{}}]*\}}{_PUA})+{_PUA}"


def is_layer_group(token: str) -> bool:
    return token.startswith("{") and token[-1] >= chr(PUA_START)
