from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.editing import Cue
from pipeline.workflow import WorkflowOptions
from worker.analysis import SyncOptions
from worker.sync_verification import UnverifiedSync, text_shift, verify_sync


def cues(shift=0):
    return [
        Cue(start=s + shift, end=s + 3 + shift, text=f"source sentence {i}")
        for i, s in enumerate([5, 16, 30, 45, 60])
    ]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    import worker.sync_verification as module

    source = tmp_path / "source.wav"
    source.write_bytes(b"original")
    monkeypatch.setattr(module, "refine_offset", lambda *args: None)

    def denoise(given, output):
        assert given == source and output != source
        output.write_bytes(b"analysis copy")

    monkeypatch.setattr(module, "denoise_for_sync", denoise)
    return module, source


def failed_acoustic(*args):
    raise ValueError("unverified")


def test_library_success_without_evidence_is_rejected(setup):
    _, source = setup

    def wrong(*args):
        return cues(-3.94), {"offset_seconds": -3.94}

    def aligned(*args, **kwargs):
        return cues()

    with pytest.raises(UnverifiedSync, match="충돌"):
        verify_sync(source, cues(), SyncOptions(source_language="en"), wrong, aligned)
    assert source.read_bytes() == b"original"


def test_no_source_language_cannot_align_a_translation(setup):
    _, source = setup
    with pytest.raises(UnverifiedSync, match="원문 음성 언어"):
        verify_sync(
            source,
            cues(),
            SyncOptions(),
            failed_acoustic,
            lambda *a, **kw: pytest.fail("must not guess language"),
        )


def test_verified_text_recovery_preserves_original_words_and_duration(setup):
    _, source = setup
    calls = []

    def align(path, text, **kwargs):
        calls.append(path)
        assert kwargs["language"] == "en" and kwargs["strict"]
        assert text == "\n".join(c.text for c in cues())
        return cues()

    result, report = verify_sync(
        source, cues(2.5), SyncOptions(source_language="en"), failed_acoustic, align
    )
    assert result == cues()
    assert report["verified_by"] == "source_text" and report["denoised"]
    assert report["offset_seconds"] == -2.5
    assert len(calls) == 2 and calls[0] == source and not calls[1].exists()
    assert source.read_bytes() == b"original"


def test_raw_and_denoised_conflict_is_not_averaged(setup):
    _, source = setup

    def align(path, *args, **kwargs):
        return cues(0 if path == source else 1.2)

    with pytest.raises(UnverifiedSync, match="충돌"):
        verify_sync(source, cues(), SyncOptions(source_language="en"), failed_acoustic, align)


def test_one_text_estimate_requires_original_audio_evidence(setup):
    _, source = setup

    def align(path, *args, **kwargs):
        if path == source:
            raise ValueError("missing words")
        return cues()

    with pytest.raises(UnverifiedSync, match="교차 검증"):
        verify_sync(source, cues(), SyncOptions(source_language="en"), failed_acoustic, align)


def test_boundary_verified_result_does_not_run_text_models(setup, monkeypatch):
    module, source = setup
    monkeypatch.setattr(module, "refine_offset", lambda *args: (0.1, 5))
    result, report = verify_sync(
        source,
        cues(),
        SyncOptions(),
        lambda *args: (cues(0.1), {"offset_seconds": 0.1}),
        lambda *a, **kw: pytest.fail("already verified"),
    )
    assert result == cues(0.1) and report["verified_by"] == "source_boundaries"


def test_agreeing_acoustic_and_text_preserve_coarse_shift(setup, monkeypatch):
    module, source = setup
    monkeypatch.setattr(module, "denoise_for_sync", lambda *a: pytest.fail("already agrees"))
    result, report = verify_sync(
        source,
        cues(),
        SyncOptions(source_language="en"),
        lambda *a: (cues(0.3), {"offset_seconds": 0.3}),
        lambda *a, **kw: cues(),
    )
    assert result == cues(0.3) and report["verified_by"] == "source_text"
    assert not report["denoised"]


def test_stationary_audio_cannot_bypass_guard_through_text(setup, monkeypatch):
    module, source = setup

    def no_evidence(*args):
        raise ValueError("stationary")

    monkeypatch.setattr(module, "refine_offset", no_evidence)
    with pytest.raises(UnverifiedSync, match="시간 근거"):
        verify_sync(
            source,
            cues(),
            SyncOptions(source_language="en"),
            lambda *a: (cues(), {"offset_seconds": 0}),
            lambda *a, **kw: pytest.fail("must not retry"),
        )


def test_text_evidence_needs_matching_words_and_distributed_times():
    assert text_shift(cues(1.37), cues()) == pytest.approx((-1.37, 5))
    assert text_shift(cues(), cues()[:-1]) is None
    wrong = [Cue(start=c.start, end=c.end, text="한국어 번역") for c in cues()]
    assert text_shift(cues(), wrong) is None
    drifted = [Cue(start=c.start + i, end=c.end + i, text=c.text) for i, c in enumerate(cues())]
    assert text_shift(cues(), drifted) is None


def test_word_alignment_can_preserve_caption_padding():
    padded = [Cue(start=c.start + 1.2, end=c.end - 0.8, text=c.text) for c in cues()]
    shift, count = text_shift(cues(), padded)
    assert shift == pytest.approx(0.2) and count == 5


def test_translation_uses_corrected_source_times_not_stale_translation(tmp_path, monkeypatch):
    from worker import workflow_tasks as wf

    monkeypatch.setattr(wf, "get_storage", lambda: object())
    monkeypatch.setattr(wf, "get_settings", lambda: SimpleNamespace())
    originals = cues(0.2)
    translated = [
        Cue(start=c.start + 5, end=c.end + 5, text=f"한국어 {i}") for i, c in enumerate(originals)
    ]
    options = WorkflowOptions(
        audio_mode="subtitles",
        source_language="en",
        transcript=originals,
        translated_cues=translated,
    )
    result = wf.execute_step(
        "translate:0",
        options,
        {"cues": [c.model_dump() for c in originals], "target": "ko"},
        SimpleNamespace(),
        Path(tmp_path),
        "test",
        None,
        None,
    )
    assert [c["text"] for c in result["translated"]] == [c.text for c in translated]
    assert [(c["start"], c["end"]) for c in result["translated"]] == [
        (c.start, c.end) for c in originals
    ]


@pytest.mark.parametrize("offset, support", [(0.1, 5), (2.0, 0)])
def test_text_recovery_reports_only_agreeing_boundary_support(setup, monkeypatch, offset, support):
    module, source = setup
    monkeypatch.setattr(module, "refine_offset", lambda *args: (offset, 5))
    _, report = verify_sync(
        source,
        cues(),
        SyncOptions(source_language="en"),
        failed_acoustic,
        lambda *args, **kwargs: cues(),
    )
    assert report["boundary_support"] == support
    assert report["text_support"] == 5


def test_recovery_boundary_error_has_safe_explanation(setup, monkeypatch):
    module, source = setup

    def invalid_audio(*args):
        raise ValueError("private decoder diagnostic")

    monkeypatch.setattr(module, "refine_offset", invalid_audio)
    with pytest.raises(UnverifiedSync, match="시간 근거") as error:
        verify_sync(
            source,
            cues(),
            SyncOptions(source_language="en"),
            failed_acoustic,
            lambda *args, **kwargs: cues(),
        )
    assert "private" not in str(error.value)
