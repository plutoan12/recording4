import json

import pysubs2
import pytest

from pipeline.motion_templates import PRESETS, build, create, literal


def captions(text="안녕하세요.\n두 줄 자막입니다."):
    subs = pysubs2.SSAFile()
    event = pysubs2.SSAEvent(start=1000, end=3000)
    event.plaintext = text
    subs.append(event)
    return subs


@pytest.mark.parametrize("name", PRESETS)
def test_motion_roundtrip(name):
    out, duration = create(captions(), name)
    restored = pysubs2.SSAFile.from_string(out.to_string("ass"), format_="ass")
    assert duration == 3500
    assert any(e.is_drawing for e in restored)
    text = [e for e in restored if e.layer == 2]
    assert text[0].start == 1000 and text[0].end == 3000
    assert "안녕하세요." in text[0].plaintext
    assert r"\fad(" in text[0].text


def test_short_cue_transition():
    subs = captions()
    subs[0].end = 1040
    out, _ = create(subs, "pop")
    assert r"\fad(10,10)" in out[-1].text


def test_too_long_and_overlap():
    with pytest.raises(ValueError, match="두 줄"):
        create(captions("가" * 300), "pop")
    subs = captions()
    subs.append(pysubs2.SSAEvent(start=1500, end=2500, text="overlap"))
    with pytest.raises(ValueError, match="겹치지"):
        create(subs, "news")


def test_literal_tag_safety():
    assert literal(r"{\pos(0,0)}") == "｛＼pos(0,0)｝"


def test_pack_license_and_atomic_failure(tmp_path, monkeypatch):
    source = tmp_path / "input.srt"
    source.write_text(captions().to_string("srt"), encoding="utf-8")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "NotoSansKR.ttf").write_bytes(b"fixture-font")
    (fonts / "OFL.txt").write_text("fixture-license")
    output = tmp_path / "output"
    build(source, output, fonts, ["cinema"], render=False)
    assert (output / "fonts/OFL.txt").read_text() == "fixture-license"
    assert len(json.loads((output / "sources.json").read_text())) == 5
    with pytest.raises(ValueError, match="덮어쓰지"):
        build(source, output, fonts, ["cinema"], render=False)

    def fail(*a, **k):
        raise OSError("render test failure")

    monkeypatch.setattr("pipeline.motion_templates.subprocess.run", fail)
    with pytest.raises(OSError):
        build(source, tmp_path / "failed", fonts, ["cinema"])
    assert not (tmp_path / "failed").exists()


@pytest.mark.parametrize("motion", ["letters", "lines"])
def test_reveal_preserves_text_and_fits_short_cue(motion):
    import re

    from pipeline.motion_templates import animated_text

    text = "한글 테스트\n두 번째 줄"
    rendered = animated_text(text, motion, 90)
    event = pysubs2.SSAEvent(text=rendered)
    assert event.plaintext == text
    transitions = re.findall(r"\\t\((\d+),(\d+),", rendered)
    assert transitions
    assert all(0 <= int(start) < int(end) < 90 for start, end in transitions)
