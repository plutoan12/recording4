import copy
from pathlib import Path

import pytest

from pipeline.audio_captions import map_words, pack_words

FONT = Path(".runtime/external-fonts/NotoSansKR.ttf")


def raw():
    return {
        "text": "지금 시작해요",
        "words": [
            {"text": "지금", "start": 0.2, "end": 0.6},
            {"text": " 시작", "start": 0.8, "end": 1.2},
            {"text": "해요", "start": 1.2, "end": 1.7},
        ],
    }


def test_merge_model_subwords_preserves_actual_times():
    data = raw()
    original = copy.deepcopy(data)
    assert map_words(data) == [
        {"text": "지금", "start_ms": 200, "end_ms": 600},
        {"text": "시작해요", "start_ms": 800, "end_ms": 1700},
    ]
    assert original == data


@pytest.mark.parametrize("case", ["mismatch", "cross_boundary", "zero", "overlap", "nan"])
def test_bad_alignment_fails_instead_of_inventing_times(case):
    data = raw()
    if case == "mismatch":
        data["text"] = "없는 단어"
    elif case == "cross_boundary":
        data["text"] = "지 금시작해요"
    elif case == "zero":
        data["words"][0]["end"] = 0.2
    elif case == "overlap":
        data["words"][1]["start"] = 0.5
    else:
        data["words"][0]["start"] = float("nan")
    with pytest.raises(ValueError):
        map_words(data)


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR required")
def test_grouping_preserves_every_word_and_time():
    words = [
        {"text": "한글입니다", "start_ms": i * 500, "end_ms": i * 500 + 400} for i in range(18)
    ]
    words[-1]["start_ms"] += 1000
    words[-1]["end_ms"] += 1000
    data = pack_words(words, FONT)
    assert [w for c in data["cues"] for w in c["words"]] == words
    assert len(data["cues"]) >= 4
    assert data["timing_source"] == "aligned"
    assert data["cues"][-1]["words"] == [words[-1]]


@pytest.mark.skipif(not FONT.exists(), reason="Noto Sans KR required")
def test_audio_render_maps_sound_and_preserves_long_tail(tmp_path, monkeypatch):
    import json
    import wave

    from pipeline.portrait_captions import build

    source = tmp_path / "words.json"
    source.write_text(json.dumps(pack_words(map_words(raw()), FONT)))
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 16000 * 4)
    calls = []
    monkeypatch.setattr(
        "pipeline.portrait_captions.subprocess.run", lambda cmd, **kw: calls.append(cmd)
    )
    build(source, tmp_path / "output", FONT.parent, audio=audio)
    cmd = calls[0]
    assert "1:a:0" in cmd
    assert str(audio.resolve()) in cmd
    assert cmd[cmd.index("-t") + 1] == "4.0"


def test_reversed_internal_tokens_are_rejected():
    data = raw()
    data["words"][2]["start"] = 0.7
    with pytest.raises(ValueError, match="내부 토큰"):
        map_words(data)
