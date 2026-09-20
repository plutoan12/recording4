import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "r4stress", Path(__file__).parents[1] / "scripts/measure_diarization_stress.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
score = module.score


def test_overlapping_truth_requires_two_simultaneous_predictions():
    truth = [
        {"start": 0, "end": 2, "text": "first", "speaker": "A"},
        {"start": 1, "end": 3, "text": "second", "speaker": "B"},
    ]
    active = np.zeros((2, 150), dtype=bool)
    active[0, :100] = True
    active[1, 50:] = True
    turns = [
        SimpleNamespace(start=0, end=2, speaker="S1"),
        SimpleNamespace(start=1, end=3, speaker="S0"),
    ]
    result = score(turns, truth, active)
    assert result["overlap_recall"] == 1
    assert result["overlap_false_positive_seconds"] == 0
    assert result["speaker_activity_recall_proxy"] == 1
    assert result["utterance_correct_of_4"] == 2

    # Correct global count and sentence labels cannot substitute for overlap detection.
    turns[0].end = 1.5
    turns[1].start = 1.5
    result = score(turns, truth, active)
    assert result["detected_speakers"] == 2
    assert result["overlap_recall"] == 0
    assert result["speaker_activity_recall_proxy"] == pytest.approx(0.75)


def test_one_predicted_speaker_counts_only_the_matching_reference_speaker():
    truth = [
        {"start": 0, "end": 1, "text": "first", "speaker": "A"},
        {"start": 1, "end": 2, "text": "second", "speaker": "B"},
    ]
    active = np.zeros((2, 100), dtype=bool)
    active[0, :50] = True
    active[1, 50:] = True
    result = score([SimpleNamespace(start=0, end=2, speaker="one")], truth, active)
    assert result["utterance_correct_of_4"] == 1
    assert result["overlap_recall"] is None
    assert result["speaker_activity_recall_proxy"] == 0.5
