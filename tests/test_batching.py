"""장면 단위 묶음(LLM-Subtrans SubtitleBatcher 이식)."""

from __future__ import annotations

import pytest

from pipeline.batching import batch_starts, scene_batches


def cues(*spans):
    return [{"start": s, "end": e, "text": "x" * n} for s, e, n in spans]


def test_a_long_silence_starts_a_new_scene():
    rows = cues((0, 1, 1), (2, 3, 1), (40, 41, 1), (42, 43, 1))
    assert [len(b) for b in scene_batches(rows)] == [2, 2]
    assert batch_starts(rows) == [0, 2]


def test_an_oversized_scene_splits_at_its_longest_gap():
    rows = cues((0, 1, 1), (1.1, 2, 1), (5, 6, 1), (6.1, 7, 1), (7.1, 8, 1))
    assert [len(b) for b in scene_batches(rows, max_lines=3)] == [2, 3]


def test_min_lines_keeps_splits_away_from_the_edges():
    rows = cues((0, 1, 1), (9, 10, 1), (10.1, 11, 1), (11.1, 12, 1))
    # 가장 긴 틈은 1번 앞이지만 min_lines=2라 그 자리에서는 못 가릅니다.
    assert [len(b) for b in scene_batches(rows, max_lines=3, min_lines=2)] == [2, 2]


def test_character_cap_splits_even_without_gaps():
    rows = cues((0, 1, 60), (1, 2, 60), (2, 3, 60))
    assert [len(b) for b in scene_batches(rows, max_chars=100)] == [1, 1, 1]


def test_order_is_preserved_and_nothing_is_dropped():
    rows = cues(*[(i, i + 0.5, 3) for i in range(250)])
    batches = scene_batches(rows)
    assert [c for b in batches for c in b] == rows
    assert all(len(b) <= 100 for b in batches)


def test_bad_limits_are_rejected():
    with pytest.raises(ValueError):
        scene_batches([], min_lines=5, max_lines=2)
