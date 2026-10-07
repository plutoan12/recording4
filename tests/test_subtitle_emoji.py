"""컬러 이모지: COLR 층 겹침 글꼴 만들기와 자막 글자 바꾸기."""

import json
import os
from pathlib import Path

import pytest

from pipeline import subtitle_emoji
from pipeline.subtitle_emoji import (
    ColorEmoji,
    build_color_emoji_font,
    color_emoji_map,
    expand_color_emoji,
    is_layer_group,
)
from pipeline.subtitle_motion import tokens

L1, L2, L3, SPACER, FLAG_L, FLAG_S = (chr(0xF0000 + i) for i in range(6))
TABLE = {
    "1f353": ColorEmoji(
        layers=((L1, "#BE1931"), (L2, "#77B255"), (L3, "#F4ABBA80")), spacer=SPACER
    ),
    "1f1f0-1f1f7": ColorEmoji(layers=((FLAG_L, "#0033AA"),), spacer=FLAG_S),
}


def test_expand_replaces_known_emoji_with_stacked_layers_and_a_spacer():
    out = expand_color_emoji("🍓", TABLE, restore="\\fnJua\\1c&HFFFFFF&")
    assert out is not None
    ass, spacers = out
    assert ass == (
        "{\\1c&H3119BE&}"
        + L1
        + "{\\1c&H55B277&}"
        + L2
        # 반투명 층은 채움 투명도도 씁니다(불투명도 0x80 → ASS 알파 0x7F).
        + "{\\1c&HBAABF4&\\1a&H7F&}"
        + L3
        + SPACER
        + "{\\fnJua\\1c&HFFFFFF&}"
    )
    assert spacers == SPACER


def test_expand_prefers_sequences_skips_joiners_and_keeps_unknown_characters():
    # 국기(두 코드포인트)는 조합으로, 변이 선택자(FE0F)는 건너뛰고, 모르는 이모지는 그대로.
    ass, spacers = expand_color_emoji("🇰🇷️🍓🎃", TABLE, restore="")
    assert ass.startswith("{\\1c&HAA3300&}" + FLAG_L + FLAG_S + "{\\1c&H3119BE&}")
    assert ass.endswith(SPACER + "🎃{}")
    assert spacers == FLAG_S + SPACER
    # 하나도 못 바꾸면 None(흑백 글꼴로 갑니다). 표가 없어도 None.
    assert expand_color_emoji("🎃", TABLE, restore="") is None
    assert expand_color_emoji("🍓", {}, restore="") is None


def test_tokens_treat_a_layer_group_as_one_character():
    ass, _ = expand_color_emoji("🍓", TABLE, restore="\\fnJua")
    items = tokens("가 " + ass + "나")
    assert items[0] == "가" and items[1] == " "
    assert is_layer_group(items[2]) and items[2].endswith(SPACER)
    assert items[3] == "{\\fnJua}" and items[4] == "나"


def test_map_is_loaded_from_the_fonts_dir_or_env_and_missing_map_means_monochrome(
    tmp_path, monkeypatch
):
    subtitle_emoji._load_map.cache_clear()
    monkeypatch.delenv("R4_EMOJI_MAP", raising=False)
    monkeypatch.setenv("R4_FONTS_DIR", str(tmp_path))
    assert color_emoji_map() == {}
    path = tmp_path / "R4ColorEmoji.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "family": "R4 Color Emoji",
                "emoji": {"1f353": {"layers": [[L1, "#FF0000"]], "spacer": SPACER}},
            }
        ),
        encoding="utf-8",
    )
    assert color_emoji_map()["1f353"].spacer == SPACER
    # 다른 버전이나 깨진 파일은 빈 표입니다.
    other = tmp_path / "other.json"
    other.write_text('{"version": 2}', encoding="utf-8")
    monkeypatch.setenv("R4_EMOJI_MAP", str(other))
    assert color_emoji_map() == {}
    other.write_text("not json", encoding="utf-8")
    subtitle_emoji._load_map.cache_clear()
    assert color_emoji_map() == {}


def _source_font() -> Path | None:
    for candidate in (
        os.environ.get("R4_TWEMOJI_SOURCE", ""),
        str(Path(os.environ.get("R4_FONTS_DIR", "")) / ".." / "emoji" / "Twemoji.Mozilla.ttf"),
    ):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def test_build_makes_zero_width_layers_and_a_table_from_a_real_colr_font():
    source = _source_font()
    if source is None:
        pytest.skip("Twemoji Mozilla source font not available (R4_TWEMOJI_SOURCE)")
    import io

    from fontTools.ttLib import TTFont

    ttf, table = build_color_emoji_font(source.read_bytes())
    font = TTFont(io.BytesIO(ttf))
    assert "COLR" not in font and "CPAL" not in font
    names = {n.nameID: str(n) for n in font["name"].names if n.platformID == 3}
    assert names[1] == "R4 Color Emoji"
    entry = table["emoji"]["1f353"]
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    for glyph, color in entry["layers"]:
        assert hmtx[cmap[ord(glyph)]][0] == 0 and color.startswith("#")
    spacer = cmap[ord(entry["spacer"])]
    assert hmtx[spacer][0] == font["head"].unitsPerEm
    assert font["glyf"][spacer].numberOfContours in (0, None)
    assert "1f1f0-1f1f7" in table["emoji"]  # 국기 조합
    with pytest.raises(ValueError):
        build_color_emoji_font(b"not a font")
