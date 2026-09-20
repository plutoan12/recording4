import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_community_evaluation import validated_turns  # noqa: E402


def test_validates_and_sorts_private_turns():
    turns = [
        SimpleNamespace(start=2, end=3, speaker="b"),
        SimpleNamespace(start=0, end=1, speaker="a"),
    ]
    assert validated_turns(turns, 3) == [
        dict(start=0.0, end=1.0, speaker="a"),
        dict(start=2.0, end=3.0, speaker="b"),
    ]


@pytest.mark.parametrize(
    "turns",
    [
        [],
        [SimpleNamespace(start=1, end=1, speaker="a")],
        [SimpleNamespace(start=0, end=4, speaker="a")],
        [SimpleNamespace(start=0, end=1, speaker="")],
    ],
)
def test_rejects_empty_or_invalid_turns(turns):
    with pytest.raises(ValueError):
        validated_turns(turns, 3)
