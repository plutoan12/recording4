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


def test_batch_connects_independent_evidence_without_changing_assignments(tmp_path, monkeypatch):
    import json

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    reviews = [
        dict(
            text="a sufficiently long phrase",
            overlaps=[dict(start=0, end=1)],
            needs_review=True,
            words=[
                dict(
                    text="a sufficiently long phrase",
                    start=0,
                    end=1,
                    speaker="A",
                    timing_valid=True,
                    needs_review=True,
                )
            ],
        )
    ]
    (tmp_path / "clean-words.json").write_text(json.dumps(reviews), encoding="utf-8")
    summary = run(
        [row()],
        [row(correct=8, unresolved=1)],
        tmp_path,
        [
            dict(
                id="clean-0",
                sha256="a" * 64,
                hypothesis=reviews[0]["text"],
                generation_possibly_truncated=False,
            )
        ],
        [dict(id="clean-0", target="B")],
        tmp_path / "output",
        [
            dict(
                case="clean",
                source_sha256="a" * 64,
                cue_index=0,
                word_index=0,
                target="B",
                text=reviews[0]["text"],
                start=0,
                end=1,
                voice=dict(
                    method="speaker_embedding",
                    model_revision="voice-v1",
                    match=0.8,
                    margin=0.2,
                ),
                visual=dict(
                    method="human_visual_review",
                    reviewer_id="reviewer-1",
                    reviewed_at="2026-09-20T13:00:00+09:00",
                    active_speaker_score=1,
                ),
            )
        ],
    )
    assert summary["schema"] == 2
    assert summary["independent_evidence_status"] == "evaluated"
    assert summary["cases"][0]["independently_qualified_words"] == 1
    assert summary["changed_assignments"] == 0
    review = json.loads((tmp_path / "output" / "clean-review.json").read_text())
    assert review[0]["words"][0]["speaker"] == "A"
    assert review[0]["words"][0]["target_asr_review"]["qualified_for_reassignment"] is True


def test_batch_marks_independent_evidence_as_absent(tmp_path, monkeypatch):
    import json

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    reviews = [dict(text="short", overlaps=[], needs_review=False, words=[])]
    (tmp_path / "clean-words.json").write_text(json.dumps(reviews), encoding="utf-8")
    summary = run(
        [row()],
        [row()],
        tmp_path,
        [
            dict(
                id="clean-0",
                sha256="a" * 64,
                hypothesis="short",
                generation_possibly_truncated=False,
            )
        ],
        [dict(id="clean-0", target="A")],
        tmp_path / "output",
    )
    assert summary["independent_evidence_status"] == "absent"
    assert summary["cases"][0]["independently_qualified_words"] is None


def test_batch_rejects_independent_evidence_for_changed_audio(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    with pytest.raises(ValueError, match="audio changed"):
        run(
            [row()],
            [row()],
            tmp_path,
            [
                dict(
                    id="clean-0",
                    sha256="a" * 64,
                    hypothesis="text",
                    generation_possibly_truncated=False,
                )
            ],
            [dict(id="clean-0", target="A")],
            tmp_path,
            [dict(case="clean", source_sha256="b" * 64)],
        )


def test_batch_rejects_independent_evidence_without_target_asr_case(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    with pytest.raises(ValueError, match="no target-ASR case"):
        run(
            [row()],
            [row()],
            tmp_path,
            [],
            [],
            tmp_path,
            [dict(case="clean")],
        )


@pytest.mark.parametrize("evidence", [{}, False, "rows"])
def test_batch_rejects_non_list_independent_evidence(tmp_path, monkeypatch, evidence):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from automate_speaker_review import run

    with pytest.raises(ValueError, match="must be a list"):
        run([row()], [row()], tmp_path, [], [], tmp_path, evidence)


def test_cli_rejects_json_null_independent_evidence_as_invalid(tmp_path):
    import json
    import subprocess
    import sys

    names = ["baseline", "candidate", "predictions", "manifest"]
    for name in names:
        (tmp_path / f"{name}.json").write_text("[]", encoding="utf-8")
    (tmp_path / "evidence.json").write_text("null", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts/automate_speaker_review.py"),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--candidate",
            str(tmp_path / "candidate.json"),
            "--reviews-dir",
            str(tmp_path),
            "--predictions",
            str(tmp_path / "predictions.json"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--output",
            str(tmp_path / "output"),
            "--independent-evidence",
            str(tmp_path / "evidence.json"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env={"PYTHONPATH": "services/worker:services/api:packages/pipeline"},
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "invalid"
    assert (
        json.loads((tmp_path / "output" / "summary.json").read_text(encoding="utf-8"))["status"]
        == "invalid"
    )


def cli(tmp_path, baseline, candidate):
    import subprocess
    import sys

    (tmp_path / "baseline.json").write_text(baseline, encoding="utf-8")
    (tmp_path / "candidate.json").write_text(candidate, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--candidate",
            str(tmp_path / "candidate.json"),
            "--output",
            str(tmp_path / "result.json"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_cli_utf8_idempotence_and_conflicting_output_preservation(tmp_path):
    import json

    baseline = json.dumps([row("한국어・日本語・中文")], ensure_ascii=False)
    candidate = json.dumps(
        [row("한국어・日本語・中文", correct=8, unresolved=1)], ensure_ascii=False
    )
    assert cli(tmp_path, baseline, candidate).returncode == 0
    original = (tmp_path / "result.json").read_bytes()
    assert "한국어" in original.decode("utf-8")
    assert cli(tmp_path, baseline, candidate).returncode == 0
    conflict = cli(tmp_path, baseline, baseline)
    assert conflict.returncode == 1
    assert json.loads(conflict.stdout)["reasons"] == ["output_conflict_or_unavailable"]
    assert (tmp_path / "result.json").read_bytes() == original


@pytest.mark.parametrize("candidate", ['[{"case":"private","case":"other"}]', "[NaN]", "[]"])
def test_cli_invalid_input_has_fixed_safe_error(tmp_path, candidate):
    import json

    result = cli(tmp_path, json.dumps([row()]), candidate)
    assert result.returncode == 1
    assert json.loads(result.stdout)["reasons"] == ["invalid_input"]
    assert "private" not in result.stdout and "Traceback" not in result.stderr


def test_cli_missing_file_is_invalid_without_traceback(tmp_path):
    import json
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--baseline",
            str(tmp_path / "private-missing"),
            "--candidate",
            str(tmp_path / "other"),
            "--output",
            str(tmp_path / "result.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["verdict"] == "invalid"
    assert "private-missing" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_cli_equal_deltas_from_changed_inputs_do_not_reuse_old_evidence(tmp_path):
    import json

    assert (
        cli(tmp_path, json.dumps([row()]), json.dumps([row(correct=8, unresolved=1)])).returncode
        == 0
    )
    original = (tmp_path / "result.json").read_bytes()
    # Same +1 delta but a different baseline and candidate must create a new artifact.
    result = cli(
        tmp_path,
        json.dumps([row(correct=6, unresolved=3)]),
        json.dumps([row(correct=7, unresolved=2)]),
    )
    assert result.returncode == 1
    assert (tmp_path / "result.json").read_bytes() == original
