import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_dialogue_pilot import ami_turns, clip_turns, jcre3_turns  # noqa: E402


def test_provider_milliseconds_and_overlapping_speakers_preserved():
    turns = jcre3_turns(
        dict(
            utterances=[
                dict(start=119000, end=121000, speaker="A"),
                dict(start=119500, end=120000, speaker="B"),
            ]
        )
    )
    assert turns == [dict(start=119, end=120, speaker="A"), dict(start=119.5, end=120, speaker="B")]
    assert all("text" not in t for t in turns)


def test_ami_mismatched_parallel_arrays_rejected():
    with pytest.raises(ValueError):
        ami_turns(
            dict(
                rows=[
                    dict(row=dict(timestamps_start=[0, 1], timestamps_end=[1], speakers=["A", "B"]))
                ]
            )
        )


@pytest.mark.parametrize(
    "row",
    [
        dict(start=-1, end=2, speaker="A"),
        dict(start=True, end=2, speaker="A"),
        dict(start=1, end=1, speaker="A"),
        dict(start=1, end=2, speaker=""),
    ],
)
def test_bad_reference_is_not_silently_repaired(row):
    with pytest.raises(ValueError):
        clip_turns([row])
