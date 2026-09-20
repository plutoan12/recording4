import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diagnose_diarization_misses import diagnose  # noqa: E402


def turn(a, b, label):
    return dict(start=a, end=b, speaker=label)


def test_acoustic_denominators_independent_of_model_boundaries():
    audio = np.concatenate([np.full(100, 0.001), np.full(100, 0.1)])
    ref = [turn(0, 2, "a")]
    a = diagnose(ref, [turn(0, 0.7, "x")], audio, 100)["groups"]
    b = diagnose(ref, [turn(0.32, 1.49, "x")], audio, 100)["groups"]
    assert a.keys() == b.keys()
    for key in a:
        assert a[key]["reference_speaker_seconds"] == pytest.approx(
            b[key]["reference_speaker_seconds"]
        )
    assert a["all"]["missed_speaker_seconds"] == pytest.approx(1.3)
    assert b["all"]["missed_speaker_seconds"] == pytest.approx(0.83)


def test_overlap_misses_keep_speaker_time_denominator():
    result = diagnose([turn(0, 2, "a"), turn(1, 2, "b")], [turn(0, 2, "x")], np.zeros(200), 100)[
        "groups"
    ]
    assert result["all"]["reference_speaker_seconds"] == pytest.approx(3)
    assert result["all"]["missed_speaker_seconds"] == pytest.approx(1)
    assert result["overlap"]["miss_rate"] == pytest.approx(0.5)
