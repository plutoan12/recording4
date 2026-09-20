import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_extended_anchor import later_solo_spans, map_labels  # noqa: E402


def turn(start, end, speaker):
    return dict(start=start, end=end, speaker=speaker)


def test_maps_renamed_labels_from_shared_time_only():
    old = [turn(0, 4, "old-a"), turn(4, 10, "old-b")]
    new = [turn(0, 4, "new-2"), turn(4, 10, "new-1"), turn(12, 14, "new-3")]
    mapping, audit = map_labels(old, new, 10)
    assert mapping == {"old-a": "new-2", "old-b": "new-1"}
    assert all(x["accepted"] for x in audit.values())


def test_rejects_mapping_that_changes_too_much_in_shared_interval():
    old = [turn(0, 10, "old-a")]
    new = [turn(0, 4, "new-a"), turn(4, 10, "new-b")]
    with pytest.raises(ValueError, match="fixed temporal support"):
        map_labels(old, new, 10)


def test_rejects_tied_temporal_identity():
    old = [turn(0, 10, "old-a")]
    new = [turn(0, 10, "new-a"), turn(0, 10, "new-b")]
    with pytest.raises(ValueError, match="Ambiguous label mapping"):
        map_labels(old, new, 10)


def test_later_anchors_never_use_evaluation_audio():
    turns = [turn(0, 5, "a"), turn(9, 12, "a"), turn(12, 14, "b")]
    assert later_solo_spans(turns, 10, 20) == {"a": [(10, 12)], "b": [(12, 14)]}
