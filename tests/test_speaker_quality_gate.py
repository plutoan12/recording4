import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "speaker_quality", Path(__file__).resolve().parents[1] / "scripts/check_speaker_quality.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
evaluate = module.evaluate


def row(name="clean", correct=7, wrong=1, unresolved=2):
    return dict(
        case=name,
        sha256="a" * 64,
        total_characters=10,
        word_correct=correct,
        word_wrong=wrong,
        word_unresolved=unresolved,
    )


def test_real_gain_is_only_corpus_approval():
    result = evaluate([row()], [row(correct=8, unresolved=1)])
    assert result["verdict"] == "improved_on_this_corpus"
    assert result["deploy_allowed"] is False


def test_unchanged_is_not_success():
    assert evaluate([row()], [row()])["verdict"] == "reject"


def test_wrong_increase_and_per_case_regression_cannot_hide_in_totals():
    base = [row("a"), row("b")]
    candidate = [row("a", correct=9, unresolved=0), row("b", correct=6, wrong=2, unresolved=2)]
    result = evaluate(base, candidate)
    assert result["verdict"] == "reject"
    assert len(result["reasons"]) == 2


@pytest.mark.parametrize("change", ["missing", "duplicate", "hash", "denominator", "negative"])
def test_invalid_comparison_is_blocked(change):
    candidate = [row()]
    if change == "missing":
        candidate = []
    if change == "duplicate":
        candidate *= 2
    if change == "hash":
        candidate[0]["sha256"] = "b" * 64
    if change == "denominator":
        candidate[0]["total_characters"] = 9
    if change == "negative":
        candidate[0]["word_wrong"] = -1
    with pytest.raises(ValueError):
        evaluate([row()], candidate)


def test_batch_rejects_audio_mismatch_and_invalidates_old_completion(tmp_path, monkeypatch):
    import json

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    (tmp_path / "summary.json").write_text('{"status":"review_required"}')
    with pytest.raises(ValueError, match="Audio changed"):
        run(
            [row()],
            [row()],
            tmp_path,
            [
                dict(
                    id="clean-0",
                    sha256="b" * 64,
                    hypothesis="hello",
                    generation_possibly_truncated=False,
                )
            ],
            [dict(id="clean-0", target="A")],
            tmp_path,
        )
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "running"


def test_batch_waits_for_all_target_transcripts(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    with pytest.raises(ValueError, match="Incomplete target"):
        run(
            [row()],
            [row()],
            tmp_path,
            [
                dict(
                    id="clean-0",
                    sha256="a" * 64,
                    hypothesis="hello",
                    generation_possibly_truncated=False,
                )
            ],
            [dict(id="clean-0", target="A"), dict(id="clean-1", target="B")],
            tmp_path,
        )


@pytest.mark.parametrize("flag", [None, True])
def test_batch_blocks_missing_end_metadata_or_truncated_decode(tmp_path, monkeypatch, flag):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    with pytest.raises(ValueError, match="Incomplete or unverified decode"):
        run(
            [row()],
            [row()],
            tmp_path,
            [
                dict(
                    id="clean-0",
                    sha256="a" * 64,
                    hypothesis="hello",
                    generation_possibly_truncated=flag,
                )
            ],
            [dict(id="clean-0", target="A")],
            tmp_path,
        )


def test_batch_rejects_unknown_case_instead_of_silent_empty_success(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    with pytest.raises(ValueError, match="Unknown evaluation case"):
        run([row()], [row()], tmp_path, [dict(id="missing-0")], [], tmp_path)
