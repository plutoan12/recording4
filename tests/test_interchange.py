"""실제 파서/직렬화기를 사용한 자막 교환 회귀 검사. 외부 앱/DB는 사용하지 않습니다."""

import json

import pysubs2
import pytest

from pipeline.interchange import (
    DEFAULT_TEMPLATE,
    ae_script,
    apply_template,
    load_template,
    main,
    make_bundle,
    read_subtitles,
    serialize,
)


def sample():
    subs = pysubs2.SSAFile()
    subs.append(pysubs2.SSAEvent(start=1230, end=3450, text=r"안녕\N세계"))
    return subs


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass", "ssa", "ttml", "json"])
def test_real_roundtrip(tmp_path, fmt):
    text, _ = serialize(sample(), fmt)
    file = tmp_path / ("captions." + fmt)
    file.write_text(text, encoding="utf-8")
    result, _ = read_subtitles(file)
    assert (result[0].start, result[0].end, result[0].plaintext) == (1230, 3450, "안녕\n세계")


def test_ass_preserves_styles_and_overrides(tmp_path):
    subs = sample()
    subs.styles["Default"].fontname = "Example Font"
    subs[0].text = r"{\pos(50,60)\b1}한글"
    file = tmp_path / "style.ass"
    file.write_text(serialize(subs, "ass")[0], encoding="utf-8")
    result, _ = read_subtitles(file)
    assert result.styles["Default"].fontname == "Example Font"
    assert result[0].text == subs[0].text


def test_plain_output_and_loss_notice():
    subs = sample()
    subs[0].text = r"{\pos(50,60)\b1}한글"
    subs.styles["Default"].italic = True
    text, warnings = serialize(subs, "srt")
    assert "한글" in text and "pos" not in text and "<i>" not in text
    assert warnings
    assert subs.styles["Default"].italic  # 입력 불변


def test_cp949_requires_explicit_choice(tmp_path):
    file = tmp_path / "old.srt"
    file.write_bytes(serialize(sample(), "srt")[0].encode("cp949"))
    with pytest.raises(ValueError, match="encoding cp949"):
        read_subtitles(file)
    assert read_subtitles(file, "cp949")[0][0].plaintext == "안녕\n세계"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
def test_bom(tmp_path, encoding):
    file = tmp_path / "bom.srt"
    file.write_bytes(serialize(sample(), "srt")[0].encode(encoding))
    assert read_subtitles(file)[0][0].start == 1230


def test_bad_duration_rejected(tmp_path):
    file = tmp_path / "bad.srt"
    file.write_text("1\n00:00:03,000 --> 00:00:01,000\nwrong\n", encoding="utf-8")
    with pytest.raises(ValueError, match="시간"):
        read_subtitles(file)


def test_overlap_preserved_reported(tmp_path):
    subs = sample()
    subs.append(pysubs2.SSAEvent(start=2000, end=4000, text="겹침"))
    file = tmp_path / "overlap.srt"
    file.write_text(subs.to_string("srt"), encoding="utf-8")
    result, notes = read_subtitles(file)
    assert result[1].start == 2000
    assert any("겹칩니다" in note for note in notes)


@pytest.mark.parametrize(
    "data",
    [
        {"size": -1},
        {"size": True},
        {"color": "red"},
        {"alignment": 10},
        {"width": 0},
        {"extra": 1},
        {"version": 2},
        {"margin_v": 600},
        [],
    ],
)
def test_invalid_template(tmp_path, data):
    file = tmp_path / "template.json"
    file.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_template(file)


def test_template_replaces_style_without_mutation():
    subs = sample()
    subs[0].text = r"{\b1}자막"
    result = apply_template(subs, DEFAULT_TEMPLATE)
    assert result[0].text == "자막"
    assert result.styles["Default"].fontsize == 52
    assert result.info["PlayResX"] == "1920"
    assert subs[0].text == r"{\b1}자막"


def test_four_editor_bundle(tmp_path):
    out = tmp_path / "bundle"
    make_bundle(sample(), out, "all", DEFAULT_TEMPLATE, [])
    for target in ("premiere", "capcut", "davinci"):
        assert read_subtitles(out / target / "captions.srt")[0][0].start == 1230
    assert (out / "after-effects/captions.jsx").is_file()
    report = json.loads((out / "report.json").read_text())
    assert any("미지원" in note for note in report["warnings"])
    with pytest.raises(ValueError, match="이미"):
        make_bundle(sample(), out, "all", DEFAULT_TEMPLATE, [])


def test_jsx_escapes_source_text():
    subs = sample()
    subs[0].plaintext = '"; alert(1); //\n한글\u2028'
    script = ae_script(subs, DEFAULT_TEMPLATE)
    payload = script.split("var data = ", 1)[1].split(";\n", 1)[0]
    assert json.loads(payload)["cues"][0]["text"] == subs[0].plaintext
    assert "\u2028" not in payload


def test_cli_no_overwrite(tmp_path):
    file = tmp_path / "input.srt"
    original = sample().to_string("srt")
    file.write_text(original)
    with pytest.raises(SystemExit) as caught:
        main([str(file), str(file)])
    assert caught.value.code == 2
    assert file.read_text() == original


def test_smi_input(tmp_path):
    file = tmp_path / "input.smi"
    file.write_text(
        "<SAMI><BODY><SYNC Start=1000><P>안녕하세요" "<SYNC Start=2500><P>&nbsp;</BODY></SAMI>",
        encoding="utf-8",
    )
    result, notes = read_subtitles(file)
    assert result[0].plaintext == "안녕하세요"
    assert (result[0].start, result[0].end) == (1000, 2500)
    assert notes


def test_smi_missing_end_rejected(tmp_path):
    file = tmp_path / "unfinished.smi"
    file.write_text("<SAMI><BODY><SYNC Start=1000><P>끝</BODY></SAMI>", encoding="utf-8")
    with pytest.raises(ValueError, match="종료 시각"):
        read_subtitles(file)


def test_ass_zero_duration_comment_preserved(tmp_path):
    subs = sample()
    subs.append(pysubs2.SSAEvent(start=0, end=0, text="메모", type="Comment"))
    file = tmp_path / "comments.ass"
    file.write_text(subs.to_string("ass"), encoding="utf-8")
    result, _ = read_subtitles(file)
    assert result[1].is_comment
