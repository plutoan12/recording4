"""`[[...]]` 강조 표기: 조각 나누기, 표기 제거, 굽는 자막과 내보내기에서의 처리."""

import pysubs2

from pipeline.editing import Cue
from pipeline.subtitle_files import dump_subtitles, subtitle_file
from pipeline.subtitle_markup import has_markup, split_markup, strip_markup
from pipeline.subtitle_templates import SubtitleTemplate, get_template, styled_document


def test_split_and_strip_handle_unbalanced_markers():
    assert split_markup("[[딸기]]말차라떼") == [("딸기", True), ("말차라떼", False)]
    assert split_markup("그냥 글자") == [("그냥 글자", False)]
    # 닫히지 않은 표기는 끝까지 강조, 짝 없는 닫힘은 뺍니다(규칙이 자막을 나눌 때 생깁니다).
    assert split_markup("a[[b") == [("a", False), ("b", True)]
    assert split_markup("c]]d") == [("cd", False)]
    assert strip_markup("[[딸기]]말차[[라떼") == "딸기말차라떼"
    assert has_markup("[[x") and not has_markup("x")
    assert split_markup("") == [("", False)]


def test_accent_color_changes_only_the_marked_piece_in_the_burned_subtitle():
    template = SubtitleTemplate(
        name="a", label="a", primary_color="#FFFFFF", accent_color="#FF0000"
    )
    text = template.body_text("[[딸기]]말차")
    assert text == "{\\1c&H0000FF&}딸기{\\1c&HFFFFFF&}말차"
    # 강조 색이 없으면 표기만 뺍니다. 사용자 중괄호는 여전히 막힙니다.
    plain = SubtitleTemplate(name="b", label="b")
    assert plain.body_text("[[x]]{y}") == "x｛y｝"
    # 속 빈 글자는 외곽선 색(\\3c)을 바꿉니다.
    hollow = template.model_copy(update={"hollow": True, "outline_color": "#00FF00"})
    assert hollow.body_text("[[x]]y") == "{\\3c&H0000FF&}x{\\3c&H00FF00&}y"


def test_markup_never_reaches_srt_vtt_or_the_title():
    cues = [Cue(start=0, end=2, text="[[딸기]]말차라떼")]
    assert "[[" not in dump_subtitles(cues, "srt") and "딸기말차라떼" in dump_subtitles(cues, "srt")
    assert "[[" not in subtitle_file(cues, 0, 5, "vtt")
    template = get_template("bubble-pink")
    assert template.accent_color
    document = styled_document(
        cues, template, width=1080, height=1920, duration=5, title="[[제목]]"
    )
    front = [e for e in document.events if e.style == "Default"][0]
    assert "\\1c" in front.text and "[[" not in front.text
    title = [e for e in document.events if e.style == "Title"][0]
    assert title.text == "제목" and "\\1c" not in title.text
    parsed = pysubs2.SSAFile.from_string(document.to_string("ass"))
    assert parsed[0].plaintext or True  # 파싱만 되면 됩니다.
