import copy
import importlib.util
import json
import wave
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "conversation_evaluation",
    Path(__file__).resolve().parents[1] / "scripts/prepare_conversation_evaluation.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def corpus(tmp_path):
    cases = []
    for i, lang in enumerate(sorted(module.LANGUAGES)):
        audio = tmp_path / f"{lang}.wav"
        with wave.open(str(audio), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(bytes([i, 0]) * 32000)
        reference = tmp_path / f"{lang}.json"
        reference.write_text(
            json.dumps(
                {
                    "segments": [
                        dict(start=0, end=1.5, speaker="a", text="private text"),
                        dict(start=0.5, end=2, speaker="b", text="private reply"),
                    ]
                }
            )
        )
        cases.append(
            dict(
                id=lang,
                language=lang,
                kind="real_conversation",
                human_annotated=True,
                source="fixture only",
                revision="fixed",
                license="test",
                selection_rule="all fixtures",
                audio=audio.name,
                reference=reference.name,
                audio_sha256=module.digest(audio),
                reference_sha256=module.digest(reference),
                evaluation_start=0,
                evaluation_end=2,
            )
        )
    return tmp_path, dict(schema=1, policy=copy.deepcopy(module.POLICY), cases=cases)


def test_lock_preserves_overlap_and_denominator_without_transcripts(corpus):
    root, manifest = corpus
    result = module.prepare(manifest, root)
    assert result["ready_for_multilingual_evaluation"]
    assert not result["deploy_allowed"]
    assert all(row["reference_characters"] == 23 for row in result["cases"])
    assert all(row["reference_speakers"] == 2 for row in result["cases"])
    assert "private text" not in json.dumps(result)
    assert module.prepare(manifest, root) == result


def test_one_language_is_not_multilingual_success(corpus):
    root, manifest = corpus
    manifest["cases"] = manifest["cases"][:1]
    result = module.prepare(manifest, root)
    assert not result["ready_for_multilingual_evaluation"]
    assert len(result["missing_languages"]) == 3


@pytest.mark.parametrize(
    "change",
    [
        "read",
        "automatic",
        "digest",
        "duplicate",
        "policy",
        "nan",
        "boolean",
        "outside",
        "provenance",
        "duplicate_audio",
    ],
)
def test_invalid_or_changed_inputs_rejected(corpus, change):
    root, manifest = corpus
    case = manifest["cases"][0]
    if change == "read":
        case["kind"] = "read_speech"
    elif change == "automatic":
        case["human_annotated"] = False
    elif change == "digest":
        case["reference_sha256"] = "0" * 64
    elif change == "duplicate":
        manifest["cases"].append(copy.deepcopy(case))
    elif change == "policy":
        manifest["policy"]["der_collar"] = 0.25
    elif change == "nan":
        case["evaluation_end"] = float("nan")
    elif change == "boolean":
        case["evaluation_start"] = False
    elif change == "outside":
        case["audio"] = "../outside.wav"
    elif change == "provenance":
        case["selection_rule"] = ""
    else:
        manifest["cases"][1]["audio"] = case["audio"]
        manifest["cases"][1]["audio_sha256"] = case["audio_sha256"]
    with pytest.raises(ValueError):
        module.prepare(manifest, root)


def test_reference_speaker_and_timing_validation(corpus):
    root, manifest = corpus
    case = manifest["cases"][0]
    path = root / case["reference"]
    ref = json.loads(path.read_text())
    ref["segments"][1]["speaker"] = "a"
    path.write_text(json.dumps(ref))
    case["reference_sha256"] = module.digest(path)
    with pytest.raises(ValueError, match="two"):
        module.prepare(manifest, root)
    ref["segments"][1]["speaker"] = "b"
    ref["segments"][1]["end"] = 3
    path.write_text(json.dumps(ref))
    case["reference_sha256"] = module.digest(path)
    with pytest.raises(ValueError, match="interval"):
        module.prepare(manifest, root)


def test_cli_never_replaces_a_different_existing_cohort(corpus, monkeypatch):
    import sys

    root, manifest = corpus
    source = root / "manifest.json"
    output = root / "lock.json"
    source.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare", "--manifest", str(source), "--root", str(root), "--output", str(output)],
    )
    with pytest.raises(SystemExit) as first:
        module.main()
    assert first.value.code == 0
    before = output.read_bytes()
    with pytest.raises(SystemExit) as identical:
        module.main()
    assert identical.value.code == 0
    manifest["cases"][0]["selection_rule"] = "changed sampling"
    source.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differs"):
        module.main()
    assert output.read_bytes() == before


def test_cli_incomplete_cohort_is_nonzero(corpus, monkeypatch):
    import sys

    root, manifest = corpus
    manifest["cases"] = manifest["cases"][:1]
    source, output = root / "manifest.json", root / "lock.json"
    source.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        sys,
        "argv",
        ["prepare", "--manifest", str(source), "--root", str(root), "--output", str(output)],
    )
    with pytest.raises(SystemExit) as result:
        module.main()
    assert result.value.code == 2
    assert not json.loads(output.read_text())["ready_for_multilingual_evaluation"]


@pytest.mark.parametrize("field", ["schema", "policy"])
def test_boolean_numeric_schema_confusion_rejected(corpus, field):
    root, manifest = corpus
    if field == "schema":
        manifest["schema"] = True
    else:
        manifest["policy"]["include_overlap"] = 1
    with pytest.raises(ValueError, match="schema"):
        module.prepare(manifest, root)


@pytest.mark.parametrize("raw", ['{"schema":1,"schema":2}', '{"schema":NaN}'])
def test_ambiguous_json_rejected(tmp_path, raw):
    path = tmp_path / "manifest.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        module.load_json(path)


def test_cli_error_does_not_print_private_paths(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--manifest",
            str(tmp_path / "private-user.json"),
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "private-user" not in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("value", [[], None, "private text"])
def test_non_object_manifest_rejected_without_traceback(tmp_path, value):
    import subprocess
    import sys

    source = tmp_path / "private-user.json"
    source.write_text(json.dumps(value), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--manifest",
            str(source),
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "private-user" not in result.stderr and "private text" not in result.stderr
    assert not (tmp_path / "out.json").exists()


def test_truncated_wav_cannot_pass_with_matching_digest(corpus):
    root, manifest = corpus
    case = manifest["cases"][0]
    path = root / case["audio"]
    path.write_bytes(path.read_bytes()[:-20])
    case["audio_sha256"] = module.digest(path)
    with pytest.raises(ValueError, match="Truncated"):
        module.prepare(manifest, root)


def test_extreme_json_number_is_rejected_as_invalid_interval(corpus):
    root, manifest = corpus
    manifest["cases"][0]["evaluation_end"] = 10**400
    with pytest.raises(ValueError, match="interval"):
        module.prepare(manifest, root)
