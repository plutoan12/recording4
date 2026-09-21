import json
from pathlib import Path

import pytest

from pipeline.editing import EditSpec


@pytest.mark.skipif(
    not Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc").exists(),
    reason="worker font required",
)
def test_selected_audio_is_extracted_and_times_are_clip_relative(tmp_path, monkeypatch):
    from worker.word_render import write_word_captions

    calls = []
    monkeypatch.setattr("worker.word_render.subprocess.run", lambda cmd, **kw: calls.append(cmd))

    def extract(audio, script, model, language):
        assert script == "지금 시작"
        return dict(
            mode="forced_alignment",
            words=[dict(text="지금", start=0.2, end=0.6), dict(text=" 시작", start=0.8, end=1.2)],
            text=script,
        )

    monkeypatch.setattr("worker.word_render.extract", extract)
    spec = EditSpec(start=10, end=14, caption_effect="marker-follow", caption_script="지금 시작")
    write_word_captions(tmp_path / "source.mp4", tmp_path, spec, "ffmpeg")
    assert calls[0][calls[0].index("-ss") + 1] == "10.0"
    assert calls[0][calls[0].index("-t") + 1] == "4.0"
    data = json.loads((tmp_path / "words.json").read_text())
    assert data["cues"][0]["start_ms"] == 200
    assert data["alignment"]["source_start_seconds"] == 10
    assert (tmp_path / "captions.ass").exists()
