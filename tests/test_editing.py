import math

import pytest
from pydantic import ValidationError

from pipeline.editing import Cue, EditSpec, clip_cues, suggest_clips
from worker.rendering import plain_ass, write_subtitles


def test_timeline_is_intersected_and_rebased():
    cues = [Cue(start=5, end=12, text="before"), Cue(start=18, end=25, text="after")]
    assert [c.model_dump(exclude_none=True) for c in clip_cues(cues, 10, 20)] == [
        {"start": 0, "end": 2, "text": "before"},
        {"start": 8, "end": 10, "text": "after"},
    ]


@pytest.mark.parametrize(
    "values",
    [{"end": 181}, {"start": math.nan}, {"focus_x": 2}, {"start": 10, "end": 5}, {"width": 1081}],
)
def test_invalid_edit_rejected(values):
    with pytest.raises(ValidationError):
        EditSpec.model_validate({"start": 0, "end": 10, **values})


def test_subtitles_cannot_inject_ass_overrides(tmp_path):
    import pysubs2

    payload = r"{\pos(0,0)}visible"
    path = tmp_path / "captions.ass"
    spec = EditSpec(start=10, end=20, title="제목", cues=[Cue(start=9, end=12, text=payload)])
    write_subtitles(path, spec)
    parsed = pysubs2.load(str(path))
    assert parsed[0].start == 0 and parsed[0].end == 2000
    assert parsed[0].text == plain_ass(payload)
    assert "\\pos" not in parsed[0].text


def test_candidates_have_sentence_boundaries_and_do_not_overlap():
    cues = [Cue(start=i * 10, end=i * 10 + 8, text=f"sentence {i}") for i in range(20)]
    candidates = suggest_clips(cues, duration=200)
    assert len(candidates) == 5
    assert all(c["end"] - c["start"] <= 45 for c in candidates)
    assert all(a["end"] <= b["start"] for a, b in zip(candidates, candidates[1:], strict=False))
