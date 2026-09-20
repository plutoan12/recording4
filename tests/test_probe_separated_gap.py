import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probe_separated_gap import overlapping_text  # noqa: E402


def test_only_words_intersecting_unchanged_core_are_selected():
    segment = SimpleNamespace(
        words=[
            SimpleNamespace(start=0.1, end=0.4, word="before"),
            SimpleNamespace(start=0.9, end=1.2, word="inside"),
            SimpleNamespace(start=2.0, end=2.2, word="after"),
        ]
    )
    assert overlapping_text([segment], 10, 11, 9) == "inside"
