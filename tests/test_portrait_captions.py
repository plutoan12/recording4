import copy
import json
from pathlib import Path

import pytest
from PIL import ImageFont

from pipeline.portrait_captions import STYLES, build, create, layout, validate

FONT = Path(".runtime/external-fonts/NotoSansKR.ttf")


@pytest.fixture
def data():
    return {
        "version": 1,
        "timing_source": "manual",
        "cues": [
            {
                "start_ms": 100,
                "end_ms": 2000,
                "text": "한글 테스트",
                "words": [
                    {"text": "한글", "start_ms": 200, "end_ms": 500},
                    {"text": "테스트", "start_ms": 800, "end_ms": 1200},
                ],
            }
        ],
    }


@pytest.mark.parametrize("mutation", ["overlap", "outside", "text", "precision", "bool"])
def test_invalid_timing(data, mutation):
    cue = data["cues"][0]
    if mutation == "overlap":
        cue["words"][1]["start_ms"] = 400
    elif mutation == "outside":
        cue["words"][1]["end_ms"] = 2500
    elif mutation == "text":
        cue["text"] = "수정된 대사"
    elif mutation == "precision":
        cue["words"][0]["start_ms"] = 201
    else:
        cue["start_ms"] = True
    with pytest.raises(ValueError):
        validate(data)


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR font fixture required")
@pytest.mark.parametrize("style", STYLES)
def test_active_word_resets_and_layout_stays_fixed(data, style):
    result, plain = create(data, FONT, style)
    assert result.info["PlayResY"] == "1920"
    assert plain[0].plaintext == "한글 테스트"
    active = [e for e in result if e.start == 200 and e.layer == 1]
    gap = [e for e in result if e.start == 500 and e.layer == 1]
    assert len(active) == len(gap) == 2
    assert active[0].text != gap[0].text
    assert active[1].text == gap[1].text
    assert all(e.start < e.end for e in result)
    assert all(r"\c&HFFFFFF&" in e.text for e in gap)


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR font fixture required")
def test_korean_word_layout_and_overflow():
    words = [{"text": t} for t in "한글과 English 2026년 함께 표시해요".split()]
    size, positions = layout(words, FONT)
    assert len(positions) == len(words)
    for x, _, width in positions.values():
        assert 100 <= x - width / 2 < x + width / 2 <= 980
    assert ImageFont.truetype(str(FONT), size).getlength("한글과") > 0
    with pytest.raises(ValueError, match="두 줄"):
        layout([{"text": "가" * 100}], FONT)


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR font fixture required")
def test_pack_and_failed_render_are_atomic(data, tmp_path, monkeypatch):
    source = tmp_path / "words.json"
    source.write_text(json.dumps(data))
    output = tmp_path / "pack"
    build(source, output, FONT.parent, render=False)
    assert json.loads((output / "words.json").read_text()) == data
    assert (output / "fonts/OFL.txt").exists()
    with pytest.raises(ValueError, match="덮어쓰지"):
        build(source, output, FONT.parent, render=False)

    def fail(*args, **kwargs):
        raise OSError("test")

    monkeypatch.setattr("pipeline.portrait_captions.subprocess.run", fail)
    with pytest.raises(OSError):
        build(source, tmp_path / "failed", FONT.parent)
    assert not (tmp_path / "failed").exists()


def test_validate_does_not_mutate(data):
    original = copy.deepcopy(data)
    validate(data)
    assert data == original


@pytest.mark.parametrize(
    "field,value",
    [("translation", ""), ("translation", 123), ("speaker", "가\n나"), ("speaker", None)],
)
def test_optional_fields_reject_invalid_values(data, field, value):
    data["cues"][0][field] = value
    with pytest.raises(ValueError):
        validate(data)


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR font fixture required")
def test_bilingual_and_speaker_layers_are_separate(data, tmp_path):
    data["cues"][0].update(translation="A Korean subtitle test.", speaker="진행자")
    result, plain = create(data, FONT)
    labels = [e for e in result if e.layer == 2]
    assert {e.plaintext for e in labels} == {"진행자", "A Korean subtitle test."}
    assert all(e.start == 100 and e.end == 2000 for e in labels)
    assert plain[0].plaintext == "한글 테스트"
    source = tmp_path / "words.json"
    source.write_text(json.dumps(data))
    build(source, tmp_path / "pack", FONT.parent, render=False)
    import pysubs2

    translated = pysubs2.load(str(tmp_path / "pack/translated.srt"))
    bilingual = pysubs2.load(str(tmp_path / "pack/bilingual.srt"))
    assert translated[0].plaintext == "A Korean subtitle test."
    assert bilingual[0].plaintext == "한글 테스트\nA Korean subtitle test."
    assert translated[0].start == plain[0].start


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR font fixture required")
def test_long_translation_is_rejected_before_output(data, tmp_path):
    data["cues"][0]["translation"] = "Long sentence " * 100
    source = tmp_path / "words.json"
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="보조 자막"):
        build(source, tmp_path / "failed", FONT.parent, render=False)
    assert not (tmp_path / "failed").exists()


def test_missing_translation_does_not_fabricate_content(data):
    from pipeline.portrait_captions import plain_tracks

    tracks = plain_tracks(data)
    assert not tracks["translated"]
    assert tracks["bilingual"][0].plaintext == "한글 테스트"


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR font fixture required")
def test_speaker_color_is_stable_when_speaker_returns(data):
    first = data["cues"][0]
    first["speaker"] = "진행자"
    for offset, speaker in [(2000, "게스트"), (4000, "진행자")]:
        cue = copy.deepcopy(first)
        cue["speaker"] = speaker
        for key in ("start_ms", "end_ms"):
            cue[key] += offset
        for word in cue["words"]:
            for key in ("start_ms", "end_ms"):
                word[key] += offset
        data["cues"].append(cue)
    result, _ = create(data, FONT)
    labels = [e.text for e in result if e.layer == 2]
    assert labels[0] == labels[2]
    assert labels[0] != labels[1]
