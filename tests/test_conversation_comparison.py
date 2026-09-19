import copy
import importlib.util
import sys
from pathlib import Path

import pytest

from test_conversation_evaluation import corpus  # noqa: F401

scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location(
    "conversation_comparison", scripts / "compare_conversation_evaluation.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def scores():
    lock = dict(
        ready_for_multilingual_evaluation=True,
        cases=[
            dict(
                id=lang,
                language=lang,
                audio_sha256=str(i) * 64,
                reference_sha256="f" * 64,
                reference_characters=10,
            )
            for i, lang in enumerate(["ko", "en", "ja", "zh"])
        ],
    )
    baseline = dict(
        schema=1,
        cohort_sha256=module.fingerprint(lock),
        cases=[
            dict(
                case=r["id"],
                language=r["language"],
                sha256=r["audio_sha256"],
                reference_sha256=r["reference_sha256"],
                total_characters=10,
                word_correct=7,
                word_wrong=1,
                word_unresolved=2,
                status="succeeded",
            )
            for r in lock["cases"]
        ],
    )
    candidate = copy.deepcopy(baseline)
    candidate["cases"][0].update(word_correct=8, word_unresolved=1)
    return lock, baseline, candidate


def test_gain_is_scoped_to_same_cohort_not_deployment(scores):
    result = module.compare(*scores)
    assert result["verdict"] == "improved_on_this_corpus"
    assert result["delta"]["word_correct"] == 1
    assert not result["deploy_allowed"]
    assert set(result["languages"]) == {"ko", "en", "ja", "zh"}
    assert result["languages"]["ko"]["total_characters"] == 10


@pytest.mark.parametrize(
    "change", ["lock", "reference", "audio", "language", "denominator", "missing", "status"]
)
def test_changed_evidence_rejected(scores, change):
    lock, baseline, candidate = scores
    row = candidate["cases"][0]
    if change == "lock":
        candidate["cohort_sha256"] = "0" * 64
    elif change == "reference":
        row["reference_sha256"] = "0" * 64
    elif change == "audio":
        row["sha256"] = "f" * 64
    elif change == "language":
        row["language"] = "en"
    elif change == "denominator":
        row["total_characters"] = 11
        row["word_unresolved"] += 1
    elif change == "missing":
        candidate["cases"].pop()
    else:
        row.pop("status")
    with pytest.raises(ValueError):
        module.compare(lock, baseline, candidate)


@pytest.mark.parametrize("status", ["failed", "rejected"])
def test_failed_case_cannot_hide_behind_other_case_gain(scores, status):
    lock, baseline, candidate = scores
    for report in (baseline, candidate):
        report["cases"][1].update(status=status, word_correct=0, word_wrong=0, word_unresolved=10)
    result = module.compare(lock, baseline, candidate)
    assert result["verdict"] == "reject"
    assert len(result["failures"]) == 2
    assert result["languages"]["en"]["total_characters"] == 10


def test_wrong_increase_is_not_offset_by_correct_gain(scores):
    lock, baseline, candidate = scores
    candidate["cases"][1].update(word_wrong=2, word_unresolved=1)
    assert module.compare(lock, baseline, candidate)["verdict"] == "reject"


def test_incomplete_language_cohort_cannot_pass(scores):
    lock, baseline, candidate = scores
    lock["ready_for_multilingual_evaluation"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        module.compare(lock, baseline, candidate)


def test_cli_revalidates_files_and_preserves_previous_evidence(corpus):  # noqa: F811
    import json
    import subprocess

    from prepare_conversation_evaluation import prepare

    root, manifest = corpus
    lock = prepare(manifest, root)
    baseline = dict(
        schema=1,
        cohort_sha256=module.fingerprint(lock),
        cases=[
            dict(
                case=row["id"],
                language=row["language"],
                sha256=row["audio_sha256"],
                reference_sha256=row["reference_sha256"],
                total_characters=row["reference_characters"],
                word_correct=10,
                word_wrong=1,
                word_unresolved=row["reference_characters"] - 11,
                status="succeeded",
            )
            for row in lock["cases"]
        ],
    )
    candidate = copy.deepcopy(baseline)
    candidate["cases"][0]["word_correct"] += 1
    candidate["cases"][0]["word_unresolved"] -= 1
    for name, value in (
        ("manifest", manifest),
        ("lock", lock),
        ("baseline", baseline),
        ("candidate", candidate),
    ):
        (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    output = root / "comparison.json"
    command = [
        sys.executable,
        str(Path(module.__file__)),
        "--root",
        str(root),
        "--output",
        str(output),
    ]
    for name in ("manifest", "lock", "baseline", "candidate"):
        command += [f"--{name}", str(root / f"{name}.json")]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    before = output.read_bytes()
    audio = root / manifest["cases"][0]["audio"]
    audio.write_bytes(audio.read_bytes() + b"changed")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert output.read_bytes() == before


def test_recovered_baseline_failure_counts_as_gain(scores):
    lock, baseline, candidate = scores
    baseline["cases"][0].update(status="failed", word_correct=0, word_wrong=0, word_unresolved=10)
    candidate["cases"][0].update(word_correct=8, word_wrong=0, word_unresolved=2)
    result = module.compare(lock, baseline, candidate)
    assert result["verdict"] == "improved_on_this_corpus"
    assert result["failures"] == [{"report": "baseline", "case": "ko", "status": "failed"}]
    assert result["languages"]["ko"]["total_characters"] == 10
    assert result["delta"]["word_correct"] == 8
