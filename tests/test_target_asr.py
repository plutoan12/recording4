from pathlib import Path

import numpy as np


def test_stno_mask_separates_target_others_overlap_and_silence(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from benchmark_target_asr import stno_mask

    turns = [dict(start=0, end=2, speaker="A"), dict(start=1, end=3, speaker="B")]
    mask = stno_mask(turns, "A", 200)
    assert np.all(mask.sum(axis=0) == 1)
    assert mask[:, 25].tolist() == [0, 1, 0, 0]
    assert mask[:, 75].tolist() == [0, 0, 0, 1]
    assert mask[:, 125].tolist() == [0, 0, 1, 0]
    assert mask[:, 175].tolist() == [1, 0, 0, 0]
    other = stno_mask(turns, "B", 100, start=1)
    assert other[:, 25].tolist() == [0, 0, 0, 1]
    assert other[:, 75].tolist() == [0, 1, 0, 0]


def test_missing_target_is_not_fabricated(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from benchmark_target_asr import stno_mask

    mask = stno_mask([dict(start=0, end=1, speaker="A")], "unknown", 100)
    assert not mask[1].any() and not mask[3].any()
    assert mask[2, :50].all()


def test_resume_requires_same_reference_masks_and_decoder(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from benchmark_target_asr import run_fingerprint

    item = dict(reference="hello", target="A", turns=[])
    original = run_fingerprint(item, "rev1", True, 0.0)
    assert original == run_fingerprint(dict(item), "rev1", True, 0.0)
    for changed in [dict(item, reference="bye"), dict(item, target="B")]:
        assert original != run_fingerprint(changed, "rev1", True, 0.0)
    assert original != run_fingerprint(item, "rev1", True, 0.3)
    assert original != run_fingerprint(item, "rev2", True, 0.0)
