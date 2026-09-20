"""자막 템플릿: 값 검증, 색·정렬 변환, 내장 템플릿, 렌더 연결."""

import json

import pysubs2
import pytest
from pydantic import ValidationError

from pipeline.editing import Cue, EditSpec
from pipeline.subtitle_fonts import FONT_FAMILIES, FONT_SOURCES, GOOGLE_FONTS_CSS_FAMILIES
from pipeline.subtitle_templates import (
    BUILTIN_TEMPLATES,
    CATEGORY_LABELS,
    DEFAULT_TEMPLATE,
    SubtitleTemplate,
    alignment_for,
    format_color,
    get_template,
    load_template,
    parse_color,
    resolve_template,
    sheet_document,
    styled_document,
    template_names,
    templates_by_category,
)


def test_default_template_matches_the_style_used_before_templates_existed():
    """기존 편집본은 템플릿 이름 없이 저장돼 있으므로 이 값이 바뀌면 모양이 바뀝니다."""
    style = DEFAULT_TEMPLATE.style(1920)
    assert style.fontname == "Noto Sans CJK KR"
    assert style.fontsize == 64
    assert (style.outline, style.shadow) == (3, 1)
    assert (style.marginl, style.marginr, style.marginv) == (50, 50, int(1920 * 0.13))
    assert style.alignment == pysubs2.Alignment.BOTTOM_CENTER
    assert style.borderstyle == 1
    assert style.primarycolor == pysubs2.Color(255, 255, 255, 0)
    assert style.outlinecolor == pysubs2.Color(0, 0, 0, 0)
    assert not style.bold and not style.italic


def test_builtin_templates_have_unique_valid_names_and_labels():
    assert template_names()[0] == "default"
    assert len(set(template_names())) == len(BUILTIN_TEMPLATES)
    for name, template in BUILTIN_TEMPLATES.items():
        assert template.name == name
        assert template.label
        # 내장값 자체가 검증을 통과해야 합니다. 모델을 다시 만들어 확인합니다.
        SubtitleTemplate.model_validate(template.model_dump())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#FFFFFF", pysubs2.Color(255, 255, 255, 0)),
        ("#ffe14d", pysubs2.Color(255, 225, 77, 0)),
        ("#00000099", pysubs2.Color(0, 0, 0, 255 - 0x99)),
        ("#12345600", pysubs2.Color(0x12, 0x34, 0x56, 255)),
    ],
)
def test_colors_use_css_opacity_and_ass_alpha_is_inverted(value, expected):
    assert parse_color(value) == expected
    assert parse_color(format_color(expected)) == expected


@pytest.mark.parametrize("value", ["FFFFFF", "#FFF", "#GGGGGG", "#FFFFFFF", "rgb(1,2,3)", ""])
def test_bad_colors_are_rejected(value):
    with pytest.raises(ValueError):
        parse_color(value)
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="x", label="x", primary_color=value)


def test_alignment_follows_the_ass_numpad_layout():
    assert alignment_for("bottom") == 2
    assert alignment_for("middle") == 5
    assert alignment_for("top") == 8
    assert alignment_for("bottom", "left") == 1
    assert alignment_for("top", "right") == 9


@pytest.mark.parametrize(
    "values",
    [
        {"name": "Bad Name"},
        {"name": "-leading"},
        {"font_size": 10},
        {"font_size": 200},
        {"outline": -1},
        {"margin_vertical_ratio": 0.9},
        {"position": "left"},
        {"border_style": "shadow"},
        {"box_color": "pink"},
        {"category": "meme"},
        {"prefix": "★★★★★★★★★"},
        {"font_name": "Noto, Sans"},
        {"font_name": "Noto{\\b1}"},
        {"unknown": 1},
    ],
)
def test_invalid_template_values_are_rejected(values):
    with pytest.raises(ValidationError):
        SubtitleTemplate.model_validate({"name": "ok", "label": "확인", **values})


def test_box_template_puts_the_box_color_where_libass_reads_it():
    """libass는 BorderStyle 3의 상자를 외곽선 색으로 채웁니다. 뒷색만 넣으면 검은 상자입니다."""
    style = get_template("box").style(1920)
    assert style.borderstyle == 3
    assert style.outlinecolor == parse_color("#00000099")
    assert style.backcolor == parse_color("#00000099")
    # 상자+외곽선(BorderStyle 4)은 상자가 뒷색, 외곽선이 외곽선 색입니다.
    card = get_template("pink-cabinet").style(1920)
    assert card.borderstyle == 4
    assert card.backcolor == parse_color("#FFD1E8") and card.outlinecolor == parse_color("#F06AA8")
    # 외곽선 방식은 상자 색을 쓰지 않습니다.
    plain = SubtitleTemplate(name="p", label="p", box_color="#FF0000", back_color="#00FF00")
    assert plain.style(100).backcolor == parse_color("#00FF00")


def test_every_builtin_uses_an_installed_font_and_a_known_category():
    """글꼴 이름이 목록에 없으면 libass가 조용히 다른 글꼴로 바꿉니다. 여기서 먼저 잡습니다."""
    for template in BUILTIN_TEMPLATES.values():
        assert template.font_available, f"{template.name}: {template.font_name}"
        assert template.category in CATEGORY_LABELS
    grouped = templates_by_category()
    assert list(grouped)[0] == "basic" and grouped["basic"][0].name == "default"
    assert sum(len(v) for v in grouped.values()) == len(BUILTIN_TEMPLATES)
    assert len(BUILTIN_TEMPLATES) >= 50


def test_font_manifest_is_consistent():
    families = [source.family for source in FONT_SOURCES]
    assert len(set(families)) == len(families)
    for source in FONT_SOURCES:
        assert source.url.startswith("https://raw.githubusercontent.com/")
        assert len(source.sha256) == 64 and source.license == "OFL-1.1"
        assert source.family in FONT_FAMILIES
    assert "Noto Sans CJK KR" in FONT_FAMILIES
    # 화면 미리보기는 Google Fonts 이름을 씁니다. 파일 이름과 다른 것만 바꿉니다.
    assert "Nanum Pen Script" in GOOGLE_FONTS_CSS_FAMILIES
    assert not any(f.startswith("Galmuri") for f in GOOGLE_FONTS_CSS_FAMILIES)


def test_decorations_and_glow_are_added_outside_the_user_text():
    template = SubtitleTemplate(name="d", label="d", prefix="★", suffix="☆", glow=2.5)
    assert template.decorate("안녕") == "★ 안녕 ☆"
    assert template.override_tags() == "{\\blur2.5}"
    # 사용자 글자의 중괄호는 여전히 막히고, 우리 명령만 앞에 붙습니다.
    assert template.event_text("{\\b1}x") == "{\\blur2.5}" + "★ ｛＼b1｝x ☆"
    assert SubtitleTemplate(name="p", label="p").event_text("x") == "x"
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="p", label="p", prefix="a\nb")
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="p", label="p", glow=99)


def test_sheet_places_every_template_in_a_grid_with_its_own_style():
    templates = list(BUILTIN_TEMPLATES.values())
    document, height = sheet_document(templates, width=1080, columns=2)
    assert height % 2 == 0 and height > 150 * (len(templates) // 2)
    assert document.info["PlayResY"] == str(height)
    # 앞 층 이벤트만 셉니다(두 겹 템플릿은 -Back 층이 하나 더 있고, 별·카테고리 줄도 있습니다).
    events = [e for e in document.events if e.style.startswith("T") and "-Back" not in e.style]
    assert len(events) == len(templates)
    assert all(e.text.startswith("{\\pos(") for e in events)
    assert len({e.style for e in events}) == len(templates)
    backs = [e for e in document.events if e.style.endswith("-Back")]
    assert len(backs) == sum(t.layered for t in templates) and all(e.layer == 1 for e in backs)
    # 받은 순서와 무관하게 카테고리별로 묶여 구분 줄은 카테고리 수만큼입니다.
    categories = [e for e in document.events if e.style == "Category"]
    assert len(categories) == len(templates_by_category())
    assert sum(e.style == "Star" for e in document.events) == 70
    heart = next(e for e in events if "요래 됐습니다" in e.text)
    assert "♡" in heart.text and document.styles[heart.style].fontname == "Galmuri11 Regular"
    # 글자 크기는 칸에 맞춰 줄어들되 24 아래로는 내려가지 않습니다.
    assert all(24 <= document.styles[e.style].fontsize <= 106 for e in events)
    plain, _ = sheet_document(templates[:2], grouped=False, stars=0)
    assert not any(e.style in ("Category", "Star") for e in plain.events)
    same_text, _ = sheet_document(templates[:3], text="공통 예문", columns=3)
    assert sum("공통 예문" in e.text for e in same_text.events) == 3
    with pytest.raises(ValueError):
        sheet_document([])


def test_font_size_argument_overrides_the_template_value():
    template = get_template("shorts-bold")
    assert template.style(1920).fontsize == 72
    assert template.style(1920, font_size=40).fontsize == 40
    assert template.title_style(1920, font_size=40).fontsize == 40


def test_title_sits_opposite_the_subtitles():
    assert DEFAULT_TEMPLATE.title_style(1920).alignment == pysubs2.Alignment.TOP_CENTER
    assert get_template("top").title_style(1920).alignment == pysubs2.Alignment.BOTTOM_CENTER
    assert get_template("top").style(1920).alignment == pysubs2.Alignment.TOP_CENTER
    assert DEFAULT_TEMPLATE.title_style(1920).marginv == int(1920 * 0.08)


def test_unknown_builtin_name_lists_the_choices():
    with pytest.raises(ValueError, match="default, shorts-bold"):
        get_template("nope")


def test_json_round_trip_and_file_loading(tmp_path):
    template = get_template("yellow")
    path = tmp_path / "mine.json"
    path.write_text(template.to_json(), encoding="utf-8")
    assert load_template(path) == template
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(name="mine", primary_color="#ff0000")
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = resolve_template(path)
    assert loaded.name == "mine" and loaded.primary_color == "#FF0000"
    # 이름으로 주면 내장, .json이면 파일, None이면 기본입니다.
    assert resolve_template("yellow") == template
    assert resolve_template(str(path)) == loaded
    assert resolve_template(None) is DEFAULT_TEMPLATE
    assert resolve_template(loaded) is loaded


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"name": "x"}'])
def test_broken_template_files_fail_clearly(tmp_path, content):
    path = tmp_path / "broken.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, ValidationError)):
        load_template(path)
    with pytest.raises(ValueError):
        load_template(tmp_path / "missing.json")


def test_styled_document_keeps_text_safe_and_places_title_for_the_whole_duration():
    cues = [Cue(start=1, end=3, text=r"{\pos(0,0)}줄1" + "\n줄2")]
    document = styled_document(
        cues, get_template("top"), width=1080, height=1920, duration=10, title="제목"
    )
    assert document.info["PlayResX"] == "1080" and document.info["WrapStyle"] == "0"
    assert set(document.styles) == {"Default", "Title"}
    dialogue, title = document.events
    assert (dialogue.start, dialogue.end) == (1000, 3000)
    assert "\\pos" not in dialogue.text and dialogue.text.endswith(r"줄1\N줄2")
    assert (title.start, title.end, title.style) == (0, 10000, "Title")
    decorated = styled_document(
        cues, get_template("bubble-white"), width=1080, height=1920, duration=10, title="제목"
    )
    # bubble-white는 두 겹이라 이벤트가 넷입니다. 앞 층(layer 1)만 봅니다.
    front = [e for e in decorated.events if e.layer == 1]
    body, heading = front
    assert body.text.startswith("★ ") and body.text.endswith(" ☆")
    assert heading.text == "제목"  # 제목에는 장식을 붙이지 않습니다.
    untitled = styled_document(cues, DEFAULT_TEMPLATE, width=2, height=2, duration=1)
    assert "Title" not in untitled.styles


def test_render_uses_the_template_named_in_the_edit_spec(tmp_path):
    from worker.rendering import RenderError, write_subtitles

    spec = EditSpec(
        start=0,
        end=5,
        subtitle_template="yellow",
        cues=[Cue(start=0, end=2, text="노랑")],
    )
    path = tmp_path / "captions.ass"
    write_subtitles(path, spec)
    style = pysubs2.load(str(path)).styles["Default"]
    assert style.primarycolor == parse_color("#FFE14D") and style.bold

    # 명시한 글자 크기는 템플릿보다 우선하고, 없으면 템플릿 값입니다.
    write_subtitles(path, spec.model_copy(update={"font_size": 40}))
    assert pysubs2.load(str(path)).styles["Default"].fontsize == 40
    write_subtitles(path, spec, template="shorts-bold")
    assert pysubs2.load(str(path)).styles["Default"].fontsize == 72

    with pytest.raises(RenderError, match="모르는 자막 템플릿"):
        write_subtitles(path, spec.model_copy(update={"subtitle_template": "nope"}))


def test_edit_spec_accepts_only_template_names_and_defaults_to_default():
    assert EditSpec(start=0, end=5).subtitle_template == "default"
    assert EditSpec(start=0, end=5).font_size is None
    # 템플릿 이전 기록에는 font_size=64가 남아 있습니다. 그대로 읽혀야 합니다.
    assert EditSpec.model_validate({"start": 0, "end": 5, "font_size": 64}).font_size == 64
    with pytest.raises(ValidationError):
        EditSpec(start=0, end=5, subtitle_template="../etc")


def test_sticker_outline_renders_two_layers_and_keeps_shadow_on_the_back():
    """바깥 테두리는 ASS에 없어 두 겹으로 냅니다. 뒤 층이 굵은 바깥 색, 앞 층이 원래 선입니다."""
    template = get_template("bubble-white")
    assert template.layered and template.outline2 > 0
    document = styled_document(
        [Cue(start=0, end=1, text="유행")], template, width=1080, height=1920, duration=1, title="T"
    )
    assert [(e.layer, e.style) for e in document.events] == [
        (0, "Default-Back"),
        (1, "Default"),
        (0, "Title-Back"),
        (1, "Title"),
    ]
    back, front = document.styles["Default-Back"], document.styles["Default"]
    assert back.outline == template.outline + template.outline2
    assert back.outlinecolor == parse_color(template.outline2_color)
    assert front.outline == template.outline and front.shadow == 0
    # 글로우는 뒤 층에만 붙습니다.
    glowing = template.model_copy(update={"glow": 3})
    layers = glowing.event_text_layers("x")
    assert layers[0][1].startswith("{\\blur3}") and not layers[1][1].startswith("{")
    # 상자 방식이나 outline2=0이면 한 겹입니다.
    assert not get_template("pink-cabinet").layered
    assert len(get_template("default").event_text_layers("x")) == 1


def test_angle_and_new_fields_reach_the_style():
    tilted = get_template("playful-tilt")
    assert tilted.style(1920).angle == -3
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="a", label="a", angle=45)
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="a", label="a", outline2_color="red")


def test_sheet_fit_accounts_for_wide_latin_and_narrow_fonts():
    from pipeline.subtitle_templates import estimate_em_width

    assert estimate_em_width("TOKYO") > estimate_em_width("tokyo")
    assert estimate_em_width("한글") == 2.0
    assert estimate_em_width("한글", "Dongle") < estimate_em_width("한글", "Jua")
    document, _ = sheet_document(
        [get_template("vlog-lime"), get_template("round-white")], columns=2
    )
    sizes = {
        e.style: document.styles[e.style].fontsize
        for e in document.events
        if e.style.startswith("T") and not e.style.endswith("-Back")
    }
    # 좁은 글꼴(Dongle)은 같은 칸에서 더 크게, 넓은 라틴 대문자는 더 작게 맞춥니다.
    assert sizes["T1"] > sizes["T0"]
    assert "T0-Back" in document.styles
