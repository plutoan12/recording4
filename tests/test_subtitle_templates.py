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
    # 반지름이 0인 각진 상자만 libass 상자를 씁니다(둥근 상자는 따로 그립니다).
    square = get_template("box").model_copy(update={"box_radius": 0})
    style = square.style(1920)
    assert style.borderstyle == 3
    assert style.outlinecolor == parse_color("#00000099")
    assert style.backcolor == parse_color("#00000099")
    # 상자+외곽선(BorderStyle 4)은 상자가 뒷색, 외곽선이 외곽선 색입니다.
    card = get_template("pink-cabinet").model_copy(update={"box_radius": 0}).style(1920)
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
        # 커밋 고정 raw 파일이거나, 컬러 이모지처럼 태그 고정 릴리스 파일입니다.
        assert source.url.startswith(("https://raw.githubusercontent.com/", "https://github.com/"))
        assert "/releases/download/v" in source.url or "raw.githubusercontent" in source.url
        assert len(source.sha256) == 64 and source.license
        # Google Fonts에서 받는 것은 모두 OFL입니다. 회사 글꼴은 자체 라이선스입니다.
        assert source.license == "OFL-1.1" or not source.google
        # 컬러 이모지 글꼴은 템플릿이 직접 고르는 글꼴이 아닙니다.
        assert (source.family in FONT_FAMILIES) != source.color_emoji
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
    events = [e for e in document.events if e.style.startswith("T") and "-" not in e.style]
    # 그라데이션 템플릿은 앞 층이 띠 수만큼 있습니다.
    from pipeline.subtitle_templates import GRADIENT_STEPS

    expected = sum(GRADIENT_STEPS if t.gradient else 1 for t in templates)
    assert len(events) == expected
    assert all(e.text.startswith("{\\pos(") for e in events)
    assert len({e.style for e in events}) == len(templates)
    backs = [e for e in document.events if e.style.endswith("-Back")]
    assert len(backs) == sum(t.has_back_layer for t in templates)
    extrudes = [e for e in document.events if e.style.endswith("-Extrude")]
    assert len(extrudes) == sum(t.extrude for t in templates)
    # 앞 층은 같은 칸의 뒤 층들보다 위에 그려집니다.
    for event in events:
        siblings = [e for e in document.events if e.style.startswith(event.style + "-")]
        assert all(e.layer < event.layer for e in siblings)
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


def test_hollow_neon_keeps_a_crisp_front_line_and_a_glowing_back_line():
    template = get_template("neon-hollow-pink")
    assert template.hollow and template.glow > 0 and template.layered
    document = styled_document(
        [Cue(start=0, end=1, text="제발")], template, width=1080, height=1920, duration=1
    )
    back, front = document.styles["Default-Back"], document.styles["Default"]
    # 채움은 완전 투명, 선만 남습니다. 뒤 층만 번집니다.
    assert front.primarycolor.a == 255 and back.primarycolor.a == 255
    layers = template.event_text_layers("제발")
    assert layers[0][1].startswith("{\\blur") and layers[0][2] == "-Back"
    assert not layers[1][1].startswith("{") and layers[1][2] == ""


def test_extrude_stacks_shadow_layers_behind_the_text():
    template = get_template("retro-blue-3d")
    layers = template.event_text_layers("레트로")
    depths = [layer for layer in layers if layer[2] == "-Extrude"]
    assert len(depths) == template.extrude == 8
    assert depths[0][1].startswith("{\\shad0\\xshad8\\yshad8}")
    assert depths[-1][1].startswith("{\\shad0\\xshad1\\yshad1}")
    assert layers[-1][2] == "" and layers[-1][0] == len(layers) - 1
    document = styled_document(
        [Cue(start=0, end=1, text="x")], template, width=1080, height=1920, duration=1
    )
    extrude = document.styles["Default-Extrude"]
    assert extrude.primarycolor == parse_color("#1B2A6B") == extrude.outlinecolor
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="e", label="e", extrude=40)
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="e", label="e", accent_color="red")


def test_rounded_box_is_drawn_behind_the_text_and_sized_from_the_measured_text(monkeypatch):
    from pipeline.subtitle_templates import rounded_rect_path

    template = get_template("pink-cabinet")
    assert template.rounded_box and template.box_radius > 0
    # 글자 자체는 외곽선 없는 보통 글자가 되고 상자는 따로 그립니다.
    style = template.style(1920)
    assert style.borderstyle == 1 and style.outline == 0
    document = styled_document(
        [Cue(start=0, end=2, text="민주의 핑크 캐비닛")],
        template,
        width=1080,
        height=1920,
        duration=2,
        title="제목",
    )
    kinds = [(e.layer, e.style) for e in document.events]
    assert kinds == [(0, "Default-Box"), (1, "Default"), (0, "Title-Box"), (1, "Title")]
    box = document.events[0].text
    assert box.startswith("{\\pos(") and "\\p1" in box and "\\bord3" in box and " b " in box
    assert "\\1c&HE8D1FF&" in box  # 상자 색 #FFD1E8 → BGR
    # 상자는 글자와 같은 정렬(아래 가운데)로 글자의 정렬 점에서 여백만큼 아래에 놓입니다.
    x, y = map(int, box[6 : box.index(")")].split(","))
    assert (x, y) == (540, 1920 - style.marginv + template.outline) and "\\an2" in box
    path = rounded_rect_path(100, 40, 10)
    assert path.startswith("m 10 0 l 90 0 b ") and path.count(" b ") == 4
    # 반지름이 너무 크면 짧은 변의 절반으로 줄입니다.
    assert rounded_rect_path(100, 40, 100).startswith("m 20 0 l 80 0")
    # 각진 상자(반지름 0)는 예전처럼 libass 상자를 씁니다.
    square = get_template("news-bar")
    assert not square.rounded_box and square.style(1920).borderstyle == 3


def test_text_measurement_falls_back_to_estimates_without_font_files(monkeypatch, tmp_path):
    from pipeline import subtitle_metrics

    monkeypatch.setenv("R4_FONTS_DIR", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)
    subtitle_metrics.font_file_for.cache_clear()
    size = subtitle_metrics.measure_text("한글 ab", "Nope Font", 50, letter_spacing=2)
    assert not size.measured and size.line_height == 60
    assert size.width == pytest.approx((2 + 0.35 + 0.55 * 2) * 50 + 2 * (len("한글 ab") - 1))
    subtitle_metrics.font_file_for.cache_clear()


def test_flow_layout_packs_rows_by_measured_width_and_keeps_integer_height():
    templates = [t for ts in templates_by_category().values() for t in ts]
    document, height = sheet_document(templates, width=1080, layout="flow")
    assert isinstance(height, int) and height % 2 == 0
    assert document.info["PlayResY"] == str(height)
    fronts = [e for e in document.events if e.style.startswith("T") and "-" not in e.style]
    assert len({e.style for e in fronts}) == len(templates)
    # 같은 줄(같은 y)에 놓인 항목은 서로 겹치지 않고 화면 안에 있습니다. 그라데이션은
    # 같은 자리에 띠가 여럿이므로 스타일마다 첫 이벤트만 봅니다.
    rows: dict[str, list[float]] = {}
    first_of: dict[str, object] = {}
    for event in fronts:
        first_of.setdefault(event.style, event)
    for event in first_of.values():
        x, y = event.text[6 : event.text.index(")")].split(",")
        rows.setdefault(y, []).append(float(x))
        assert 0 < float(x) < 1080
    assert any(len(xs) >= 2 for xs in rows.values())
    for xs in rows.values():
        assert xs == sorted(xs) and len(set(xs)) == len(xs)
    # 흐름 배치는 격자보다 짧습니다(빽빽하게 채우므로).
    _, grid_height = sheet_document(templates, width=1080, layout="grid")
    assert height < grid_height


def test_animated_template_puts_the_same_motion_on_every_layer_but_not_the_title():
    from pipeline.subtitle_motion import ANIMATION_LABELS

    assert "motion" in CATEGORY_LABELS and CATEGORY_LABELS["motion"] == "움직임"
    sticker = get_template("bounce-sticker")
    assert sticker.animation == "bounce" and sticker.animation_label == ANIMATION_LABELS["bounce"]
    document = styled_document(
        [Cue(start=1, end=3, text="오늘의 브이로그")],
        sticker,
        width=1080,
        height=1920,
        duration=5,
        title="제목",
    )
    back, front, title_back, title_front = document.events
    assert (back.style, front.style) == ("Default-Back", "Default")
    lead = back.text[: back.text.index("}") + 1]
    assert lead.startswith("{\\q2\\move(540,") and "\\fscy84" in lead
    assert front.text.startswith(lead)
    # 제목은 영상 내내 보이므로 움직이지 않습니다.
    assert "\\move" not in title_back.text and "\\t(" not in title_front.text
    # 정지 화면(시트)에는 움직임이 붙지 않습니다.
    assert all("\\t(" not in text for _, text, _ in sticker.event_text_layers("가"))


def test_rounded_box_moves_and_scales_with_its_text():
    card = get_template("drop-card")
    assert card.rounded_box and card.animation == "slide-down"
    document = styled_document(
        [Cue(start=0, end=2, text="민주의 핑크 캐비닛")], card, width=1080, height=1920, duration=2
    )
    box, text = document.events
    assert box.style == "Default-Box" and "\\pos(" not in box.text
    # 상자는 글자와 같은 정렬(아래 가운데)로 놓이고 같은 거리만큼 움직입니다.
    assert "\\an2" in box.text and "\\move(540," in box.text and "\\move(540," in text.text
    moved = get_template("pink-cabinet")
    still = (
        styled_document(
            [Cue(start=0, end=2, text="가")], moved, width=1080, height=1920, duration=2
        )
        .events[0]
        .text
    )
    assert still.startswith("{\\pos(540,") and "\\an2" in still


def test_with_animation_validates_and_karaoke_drops_accent_markup():
    yellow = get_template("yellow")
    popped = yellow.with_animation("pop", 500)
    assert (popped.animation, popped.animation_ms, popped.motion_ms) == ("pop", 500, 500)
    assert yellow.with_animation("fade").motion_ms == 250
    with pytest.raises(ValueError, match="모르는 움직임"):
        yellow.with_animation("spin")
    with pytest.raises(ValidationError):
        SubtitleTemplate.model_validate({**yellow.model_dump(), "animation_ms": 10})
    bubble = get_template("bubble-pink").with_animation("karaoke")
    layers = bubble.event_text_layers("[[딸기]]말차라떼 최고", duration_ms=2000, anchor=(540, 1600))
    front = layers[-1][1]
    # 노래방은 단어 색을 스스로 바꾸므로 강조 표기는 빠지고 강조 색으로 단어를 칠합니다.
    assert "[[" not in front and front.count("\\r") == 2 and "\\1c&HD29BFF&" in front
    # 강조 색이 없는 템플릿은 기본 노랑을 씁니다.
    plain = get_template("default").with_animation("karaoke")
    assert "\\1c&H4DE1FF&" in plain.event_text_layers("가 나", duration_ms=1000)[0][1]


def test_reel_document_shows_templates_one_after_another():
    from pipeline.subtitle_templates import reel_document

    chosen = [get_template("pop-jalnan"), get_template("karaoke-card")]
    document, seconds = reel_document(chosen, width=720, height=720, seconds_each=2, gap=0.5)
    assert seconds == 5
    captions = [e for e in document.events if e.style == "Caption"]
    assert [(e.start, e.end) for e in captions] == [(0, 2000), (2500, 4500)]
    assert "pop-jalnan" in captions[0].text and "팝" in captions[0].text
    assert {e.style for e in document.events} >= {"T0", "T1-Box", "T1"}
    assert any("\\fscx40" in e.text for e in document.events)
    with pytest.raises(ValueError):
        reel_document([], width=720, height=720)
    with pytest.raises(ValueError):
        reel_document(chosen, width=720, height=720, seconds_each=0)


def test_render_applies_the_animation_named_in_the_edit_spec(tmp_path):
    from worker.rendering import RenderError, write_subtitles

    spec = EditSpec(
        start=0,
        end=5,
        subtitle_template="yellow",
        subtitle_animation="fade",
        cues=[Cue(start=0, end=2, text="노랑")],
    )
    path = tmp_path / "captions.ass"
    write_subtitles(path, spec)
    assert "\\fad(250,250)" in path.read_text(encoding="utf-8")
    # `none`은 템플릿의 움직임을 뺍니다.
    write_subtitles(path, spec.model_copy(update={"subtitle_template": "pop-jalnan"}))
    assert "\\fad(" in path.read_text(encoding="utf-8")
    write_subtitles(
        path,
        spec.model_copy(update={"subtitle_template": "pop-jalnan", "subtitle_animation": "none"}),
    )
    assert "\\t(" not in path.read_text(encoding="utf-8")
    with pytest.raises(RenderError, match="모르는 움직임"):
        write_subtitles(path, spec.model_copy(update={"subtitle_animation": "spin"}))
    with pytest.raises(ValidationError):
        EditSpec(start=0, end=5, subtitle_animation="Spin!")


def test_gradient_splits_the_front_layer_into_pinned_clip_strips():
    from pipeline.subtitle_templates import GRADIENT_STEPS, TextBlock

    gold = get_template("infomercial-gold")
    assert gold.gradient and gold.category == "gradient"
    block = TextBlock(left=300, top=1500, width=480, height=120)
    strips = gold.gradient_strips(block, 1080, 1920)
    assert len(strips) == GRADIENT_STEPS
    # 첫 띠는 화면 위 끝부터, 끝 띠는 화면 아래 끝까지 덮어 외곽선이 잘리지 않습니다.
    assert strips[0].startswith("\\clip(0,0,1080,1505)\\1c&HA8F6FF&")
    assert strips[-1].startswith("\\clip(0,1615,1080,1920)\\1c&H1F9AFF&")
    layers = gold.event_text_layers("지금 전화", anchor=(540, 1670), block=block)
    front = [body for _, body, suffix in layers if suffix == ""]
    assert len(front) == GRADIENT_STEPS and all(
        body.startswith("{\\pos(540,1670)\\clip(") for body in front
    )
    assert len([1 for _, _, suffix in layers if suffix == "-Extrude"]) == gold.extrude
    # 상자 뒤에 놓는 시트 경로처럼 anchor가 없으면 pos 없이, block이 없으면 단색 한 겹입니다.
    assert gold.event_text_layers("가", block=block)[-1][1].startswith("{\\clip(")
    assert len([1 for _, _, suffix in gold.event_text_layers("가") if suffix == ""]) == 1
    # 가로 그라데이션은 세로 띠, 이동하는 움직임은 clip도 함께 움직입니다.
    across = get_template("gold-across")
    assert across.gradient_strips(block, 1080, 1920)[1].startswith("\\clip(320,0,340,1920)")
    sliding = gold.with_animation("slide-up")
    moving = sliding.gradient_strips(block, 1080, 1920)[1]
    assert moving.startswith("\\clip(0,1575,1080,1580)\\t(0,320,\\clip(0,1505,1080,1510))")
    document = styled_document(
        [Cue(start=0, end=2, text="지금 전화")], sliding, width=1080, height=1920, duration=2
    )
    assert all("\\pos(" not in e.text and "\\move(" in e.text for e in document.events)
    # 속 빈 글자는 선 색이 흐릅니다.
    hollow = get_template("aurora-hollow")
    assert hollow.gradient_strips(block, 1080, 1920)[0].endswith("\\3c&HFFE85F&")
    with pytest.raises(ValidationError):
        SubtitleTemplate(name="g", label="g", gradient_color="red")


def test_measure_line_uses_the_emoji_font_for_emoji_runs(monkeypatch):
    from pipeline import subtitle_templates

    template = get_template("yellow")
    monkeypatch.setattr(subtitle_templates, "color_emoji_map", lambda: {})
    calls = []

    def fake_measure(text, family, size, letter_spacing=0, bold=False):
        calls.append((text, family))
        return subtitle_templates.TextSize(
            width=10 * len(text), line_height=size * 1.2, measured=True
        )

    monkeypatch.setattr(subtitle_templates, "measure_text", fake_measure)
    size = template.measure_line("딸기 🍓", 64)
    assert size.width == 40 and size.line_height == pytest.approx(76.8)
    assert ("딸기 ", "Noto Sans CJK KR") in calls and ("🍓", "Noto Emoji") in calls
    block = template.text_block(
        "가\n나다", 64, anchor=(540, 1670), vertical="bottom", horizontal="center"
    )
    assert (block.left, block.top, block.width, block.height) == (
        530,
        1670 - 2 * 76.8,
        20,
        2 * 76.8,
    )


def test_cue_word_times_reach_the_karaoke_tags():
    from pipeline.editing import Word

    template = get_template("karaoke-yellow").model_copy(update={"prefix": "★"})
    words = [Word(start=10.2, end=10.6, text="말하는"), Word(start=10.9, end=11.4, text="단어")]
    cue = Cue(start=10, end=12, text="말하는 단어", words=words)
    document = styled_document([cue], template, width=1080, height=1920, duration=12)
    text = document.events[0].text
    # 장식 ★은 첫 단어의 시각을 나눠 갖고, 단어는 원본 시각에서 자막 시작을 뺀 ms에 켜집니다.
    assert "\\t(200,201,\\1c&H4DE1FF&)" in text and "\\t(900,901,\\1c&H4DE1FF&)" in text
    # 단어 시각이 없으면 예전처럼 고르게 나눕니다.
    plain = styled_document(
        [Cue(start=10, end=12, text="말하는 단어")], template, width=1080, height=1920, duration=12
    )
    assert "\\t(667,668,\\1c&H4DE1FF&)" in plain.events[0].text
