"""클립 편집본 자막 파일(SRT·VTT) 생성. 파일 형식과 영상과의 일치를 확인합니다."""

import pysubs2
import pytest

from pipeline.editing import Cue, EditSpec
from pipeline.subtitle_files import FORMATS, MEDIA_TYPES, subtitle_file
from pipeline.subtitles import SubtitleRules


def spec(**overrides) -> EditSpec:
    base = {
        "start": 10,
        "end": 25,
        "cues": [
            Cue(start=5, end=13, text="구간보다 먼저 시작한 자막"),
            Cue(start=14, end=18, text="가운데 자막"),
            Cue(start=30, end=40, text="구간 밖 자막"),
        ],
    }
    return EditSpec.model_validate({**base, **overrides})


def test_formats_are_srt_and_vtt_only():
    assert FORMATS == ("srt", "vtt")
    assert set(MEDIA_TYPES) == {"srt", "vtt"}


def test_srt_times_are_clip_relative_and_outside_cues_are_dropped():
    text = subtitle_file(spec(), "srt")
    assert text.startswith("1\n00:00:00,000 --> 00:00:03,000\n")
    assert "00:00:04,000 --> 00:00:08,000" in text
    assert "구간 밖 자막" not in text


def test_vtt_has_header_and_dot_separator():
    text = subtitle_file(spec(), "vtt")
    assert text.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:03.000" in text


def test_screen_title_is_not_exported():
    """제목은 화면 구성이라 자막 파일에 넣지 않습니다. 넣으면 첫 자막과 겹칩니다."""
    assert "제목입니다" not in subtitle_file(spec(title="제목입니다"), "vtt")


def test_export_matches_the_subtitles_burned_into_the_video(tmp_path):
    """같은 규칙을 거치므로 영상 자막과 시각·줄바꿈이 같아야 합니다."""
    from worker.rendering import write_subtitles

    rules = SubtitleRules(max_chars_per_line=6, max_lines=1)
    edit = spec(title="제목")
    path = tmp_path / "captions.ass"
    write_subtitles(path, edit, rules)
    burned = [e for e in pysubs2.load(str(path)) if e.style != "Title"]
    exported = pysubs2.SSAFile.from_string(subtitle_file(edit, "srt", rules))
    assert len(exported) == len(burned) > 2
    for a, b in zip(exported, burned, strict=True):
        assert (a.start, a.end) == (b.start, b.end)
        assert a.text.replace("\n", r"\N") == b.text


def test_subtitle_text_survives_ass_override_syntax():
    """pysubs2는 이벤트 글자를 ASS 표기로 읽습니다. 막지 않으면 글자가 사라집니다."""
    payload = r"{\pos(0,0)}보이는 글자"
    text = subtitle_file(spec(cues=[Cue(start=12, end=16, text=payload)]), "srt")
    assert "보이는 글자" in text
    assert "\\pos" not in text and "{" not in text


def test_clip_without_cues_is_empty():
    assert subtitle_file(spec(cues=[]), "srt") == ""


def test_unsupported_format_is_rejected():
    with pytest.raises(ValueError):
        subtitle_file(spec(), "ass")
