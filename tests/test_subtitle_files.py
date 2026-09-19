"""클립 편집본 자막 파일(SRT·VTT) 생성. 파일 형식과 영상과의 일치를 확인합니다."""

import pysubs2
import pytest

from pipeline.editing import Cue, EditSpec
from pipeline.subtitle_files import (
    FORMATS,
    MEDIA_TYPES,
    clip_subtitle_file,
    parse_subtitles,
    subtitle_file,
)
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
    text = clip_subtitle_file(spec(), "srt")
    assert text.startswith("1\n00:00:00,000 --> 00:00:03,000\n")
    assert "00:00:04,000 --> 00:00:08,000" in text
    assert "구간 밖 자막" not in text


def test_vtt_has_header_and_dot_separator():
    text = clip_subtitle_file(spec(), "vtt")
    assert text.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:03.000" in text


def test_screen_title_is_not_exported():
    """제목은 화면 구성이라 자막 파일에 넣지 않습니다. 넣으면 첫 자막과 겹칩니다."""
    assert "제목입니다" not in clip_subtitle_file(spec(title="제목입니다"), "vtt")


def test_export_matches_the_subtitles_burned_into_the_video(tmp_path):
    """같은 규칙을 거치므로 영상 자막과 시각·줄바꿈이 같아야 합니다."""
    from worker.rendering import write_subtitles

    rules = SubtitleRules(max_chars_per_line=6, max_lines=1)
    edit = spec(title="제목")
    path = tmp_path / "captions.ass"
    write_subtitles(path, edit, rules)
    burned = [e for e in pysubs2.load(str(path)) if e.style != "Title"]
    exported = pysubs2.SSAFile.from_string(clip_subtitle_file(edit, "srt", rules))
    assert len(exported) == len(burned) > 2
    for a, b in zip(exported, burned, strict=True):
        assert (a.start, a.end) == (b.start, b.end)
        assert a.text.replace("\n", r"\N") == b.text


def test_subtitle_text_survives_ass_override_syntax():
    """pysubs2는 이벤트 글자를 ASS 표기로 읽습니다. 막지 않으면 글자가 사라집니다."""
    payload = r"{\pos(0,0)}보이는 글자"
    text = clip_subtitle_file(spec(cues=[Cue(start=12, end=16, text=payload)]), "srt")
    assert "보이는 글자" in text
    assert "\\pos" not in text and "{" not in text


def test_clip_without_cues_is_empty():
    assert clip_subtitle_file(spec(cues=[]), "srt") == ""


def test_unsupported_format_is_rejected():
    with pytest.raises(ValueError):
        clip_subtitle_file(spec(), "ass")


def test_job_window_starts_at_zero_and_keeps_dubbing_aligned_times():
    """번역·더빙 작업은 출력 영상 전체(0초~길이)를 창으로 씁니다."""
    cues = [Cue(start=0.5, end=3, text="첫 문장"), Cue(start=4, end=7, text="둘째 문장")]
    text = subtitle_file(cues, 0, 30, "srt")
    assert "00:00:00,500 --> 00:00:03,000" in text
    assert "00:00:04,000 --> 00:00:07,000" in text


def test_job_window_drops_cues_past_the_output_length():
    cues = [Cue(start=1, end=3, text="안에 있는 자막"), Cue(start=31, end=33, text="길이 밖 자막")]
    text = subtitle_file(cues, 0, 30, "vtt")
    assert "안에 있는 자막" in text
    assert "길이 밖 자막" not in text


SAMPLE_SRT = """1
00:00:01,000 --> 00:00:03,500
첫 줄
둘째 줄

2
00:00:04,000 --> 00:00:06,000
<i>기울임</i> 글자
"""


def test_import_reads_srt_and_joins_the_file_wrapping():
    """파일의 줄바꿈은 그 도구가 그 화면에 맞춰 끊은 것이라 공백으로 합칩니다."""
    cues, notes = parse_subtitles(SAMPLE_SRT)
    assert [c.model_dump() for c in cues] == [
        {"start": 1.0, "end": 3.5, "text": "첫 줄 둘째 줄"},
        {"start": 4.0, "end": 6.0, "text": "기울임 글자"},
    ]
    assert notes == []


def test_import_reads_webvtt_and_strips_speaker_tags():
    text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v 진행자>안녕하세요\n"
    cues, _ = parse_subtitles(text)
    assert [c.model_dump() for c in cues] == [{"start": 1.0, "end": 2.0, "text": "안녕하세요"}]


def test_import_says_what_it_skipped_instead_of_dropping_it_silently():
    text = (
        SAMPLE_SRT
        + """
3
00:00:07,000 --> 00:00:07,000
길이 0

4
00:00:08,000 --> 00:00:09,000

"""
    )
    cues, notes = parse_subtitles(text)
    assert len(cues) == 2
    assert any("3번" in note and "시간" in note for note in notes)
    assert any("4번" in note and "글자가 없어" in note for note in notes)


def test_import_sorts_by_time():
    text = "1\n00:00:05,000 --> 00:00:06,000\n뒤\n\n2\n00:00:01,000 --> 00:00:02,000\n앞\n"
    cues, _ = parse_subtitles(text)
    assert [c.text for c in cues] == ["앞", "뒤"]


def test_import_rejects_a_file_it_cannot_read():
    with pytest.raises(ValueError):
        parse_subtitles("이건 자막 파일이 아닙니다")


def test_import_rejects_a_file_with_nothing_usable():
    with pytest.raises(ValueError, match="읽을 수 있는 자막이 없습니다"):
        parse_subtitles("1\n00:00:01,000 --> 00:00:02,000\n\n")


def test_import_round_trips_what_we_export():
    """우리가 내보낸 파일을 다시 들이면 같은 시각·글자가 나와야 합니다."""
    cues = [Cue(start=0, end=2, text="첫 문장"), Cue(start=3, end=5, text="둘째 문장")]
    exported = subtitle_file(cues, 0, 10, "srt")
    again, notes = parse_subtitles(exported)
    assert [c.model_dump() for c in again] == [c.model_dump() for c in cues]
    assert notes == []
