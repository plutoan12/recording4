from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.editing import Cue
from pipeline.subtitle_files import dump_subtitles
from worker.analysis import SyncOptions
from worker.analysis import _sync_acoustic as sync_subtitles
from worker.sync_evidence import boundary_consensus, refine_offset


def cues(offset=0.0):
    return [Cue(start=s + offset, end=s + 3 + offset, text=str(s)) for s in (4, 15, 29)]


@pytest.mark.parametrize("offset", [-0.73, 0.0, 1.37, 4.12])
def test_boundary_evidence_is_shift_equivariant(offset):
    spans = [(4.05, 7.05), (15.01, 18.01), (28.97, 31.97)]
    result = boundary_consensus(spans, cues(offset), 0.6 - offset)
    assert result is not None
    shift, support = result
    assert shift == pytest.approx(0.01 - offset)
    assert support == 3


def test_no_evidence_from_silence_or_one_anchor():
    assert boundary_consensus([], cues(), 0) is None
    assert boundary_consensus([(4, 7)], cues(), 0) is None


def test_overlapping_captions_cannot_multiply_votes():
    repeated = [Cue(start=4, end=7, text=str(i)) for i in range(5)]
    assert boundary_consensus([(4, 7)], repeated, 0) is None


def test_conflicting_clusters_are_not_confidence():
    original = [Cue(start=s, end=s + 3, text=str(s)) for s in (4, 15, 29, 41, 53, 68)]
    spans = [
        (c.start + d, c.end + d) for c, d in zip(original, [-0.3] * 3 + [0.7] * 3, strict=False)
    ]
    assert boundary_consensus(spans, original, 0) is None


def test_anchors_must_cover_the_recording():
    original = cues() + [Cue(start=200, end=203, text="later scene")]
    assert boundary_consensus([(4, 7), (15, 18), (29, 32)], original, 0) is None


def test_energy_cannot_search_for_an_arbitrary_shift():
    assert boundary_consensus([(4, 7), (15, 18), (29, 32)], cues(), 1.2) is None
    assert boundary_consensus([(4, 7), (15, 18), (29, 32)], cues(), 5) is None


def test_many_anchors_do_not_require_a_pairwise_matrix():
    original = [Cue(start=i * 5 + 2, end=i * 5 + 4, text=str(i)) for i in range(5000)]
    spans = [(c.start + 0.1, c.end + 0.1) for c in original]
    shift, count = boundary_consensus(spans, original, 0.4)
    assert count == 5000 and shift == pytest.approx(0.1)


def test_optional_decode_failure_supplies_no_evidence(monkeypatch):
    import worker.sync_evidence as evidence

    def fail(source):
        raise OSError("unreadable input")

    monkeypatch.setattr(evidence, "audio_boundaries", fail)
    assert refine_offset(Path("unreadable.wav"), cues(), 0) is None


def test_stationary_noise_is_not_timing_evidence():
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from worker.sync_evidence import envelope_spans

    power = np.random.default_rng(918).uniform(0.8, 1.2, size=3500)
    with pytest.raises(ValueError, match="일정한 잡음"):
        envelope_spans(power)
    assert envelope_spans(np.zeros(3500)) == []


def test_sparse_speech_can_supply_temporal_evidence():
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from worker.sync_evidence import envelope_spans

    power = np.full(10000, 0.0001)
    power[500:800] = 1
    spans = envelope_spans(power)
    assert spans == [(5, 8)]


@pytest.mark.parametrize("profile", ["quiet", "long_cues"])
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("initial_shift", [-9, 10])
def test_recovery_requires_independent_evidence(
    tmp_path, monkeypatch, profile, confirmed, initial_shift
):
    pytest.importorskip("ffsubsync")
    import worker.analysis as analysis
    import worker.sync_evidence as evidence

    attempts = []
    normalizations = []

    def normalize(source, target, *, recovery=False):
        normalizations.append(recovery)
        target.write_bytes(b"temporary analysis audio")

    def run(args):
        attempts.append(args)
        if Path(args.reference).name != "recovery.wav":
            # Even a library 'success' that puts captions before zero is invalid.
            return {"sync_was_successful": True, "offset_seconds": initial_shift}
        Path(args.srtout).write_text(dump_subtitles(cues()))
        return {"sync_was_successful": True, "offset_seconds": -0.4}

    monkeypatch.setattr(analysis, "_normalize_sync_audio", normalize)
    monkeypatch.setattr(analysis, "_run_sync", run)
    monkeypatch.setattr(evidence, "refine_offset", lambda *args: (0.02, 3) if confirmed else None)
    if not confirmed:
        with pytest.raises(ValueError, match="보정 근거가 부족"):
            sync_subtitles(tmp_path / "source.wav", cues(), SyncOptions(profile=profile))
    else:
        result, report = sync_subtitles(
            tmp_path / "source.wav", cues(), SyncOptions(profile=profile)
        )
        assert result == cues(0.02)
        assert report["recovery_used"] and report["boundary_support"] == 3
    assert normalizations.count(True) == 1
    assert len(attempts) == 2


def test_standard_does_not_use_boundary_refinement(tmp_path, monkeypatch):
    pytest.importorskip("ffsubsync")
    import worker.analysis as analysis
    import worker.sync_evidence as evidence

    def run(args):
        Path(args.srtout).write_text(dump_subtitles(cues()))
        return {"sync_was_successful": True, "offset_seconds": 0.6}

    monkeypatch.setattr(analysis, "_run_sync", run)
    monkeypatch.setattr(evidence, "refine_offset", lambda *args: pytest.fail("standard unchanged"))
    result, report = sync_subtitles(tmp_path / "source.wav", cues())
    assert result == cues(0.6)
    assert not report["recovery_used"] and report["boundary_support"] == 0
