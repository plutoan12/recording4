"""Full-window ordered character error diagnostic; not speaker-aware ASR accuracy."""

import argparse
import re
import unicodedata
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json


def normalize(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFC", text).casefold())


def main():
    from jiwer import process_characters

    p = argparse.ArgumentParser(description=__doc__)
    for name in ["reference", "prediction", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    ref, pred = load_json(args.reference), load_json(args.prediction)
    if (
        ref["audio_sha256"] != pred["sha256"]["audio"]
        or (ref["evaluation_start"], ref["evaluation_end"]) != (0, pred["duration"])
        or ref.get("word_timing_source") != "human_manual_AMI"
        or pred.get("language") != "en"
    ):
        raise ValueError("Reference audio, provenance, language or window mismatch")
    expected = normalize("".join(w["text"] for w in ref["segments"]))
    if not expected:
        raise ValueError("Empty reference")
    scores = {}
    for label in ["original", "candidate"]:
        actual = normalize("".join(w["text"] for w in pred[label]))
        result = process_characters(expected, actual)
        scores[label] = dict(
            reference_characters=len(expected),
            hypothesis_characters=len(actual),
            hits=result.hits,
            substitutions=result.substitutions,
            deletions=result.deletions,
            insertions=result.insertions,
            cer=result.cer,
        )
    result = dict(
        scores=scores,
        sha256={k: sha256(getattr(args, k)) for k in ["reference", "prediction"]},
        core_seconds=sum(b - a for a, b in pred["cores"]),
        crop_count=len(pred["crops"]),
        failed_crops=len(pred["failed_crops"]),
        baseline_invalid_timing_words=sum(not w["timing_valid"] for w in pred["original"]),
        normalization="NFC + casefold + remove non-word and underscore",
        boundary_clipped_reference_words=sum(w["boundary_clipped"] for w in ref["segments"]),
        metric_scope="ordered_full_window_CER_not_speaker_aware",
        deployment_allowed=False,
    )
    write_private_json(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
