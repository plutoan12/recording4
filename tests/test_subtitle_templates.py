"""자막 템플릿: 값 검증, 색·정렬 변환, 내장 템플릿, 렌더 연결."""

import json

import pysubs2
import pytest
from pydantic import ValidationError

from pipeline.editing import Cue, EditSpec
from pipeline.subtitle_templates import (
    BUILTIN_TEMPLATES,
    DEFAULT_TEMPLATE,
    SubtitleTemplate,
    alignment_for,
    format_color,
    get_template,
    load_template,
    parse_color,
    resolve_template,
    styled_document,
    template_names,
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
        {"font_name": "Noto, Sans"},
        {"font_name": "Noto{\\b1}"},
        {"unknown": 1},
    ],
)
def test_invalid_template_values_are_rejected(values):
    with pytest.raises(ValidationError):
        SubtitleTemplate.model_validate({"name": "ok", "label": "확인", **values})


def test_box_template_uses_the_box_border_style_with_translucent_background():
    style = get_template("box").style(1920)
    assert style.borderstyle == 3
    assert style.backcolor.a == 255 - 0x99


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
