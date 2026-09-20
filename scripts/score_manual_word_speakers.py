#!/usr/bin/env python3
"""Isolate speaker assignment using manual words/times, NOT end-to-end ASR accuracy."""

import argparse
import re
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_conversation_diarization import score_segments

from pipeline.alignment import WordTiming, squeeze
from pipeline.editing import Cue
from pipeline.speakers import MULTIPLE_SPEAKERS, SpeakerTurn, review_speakers


def score(words, turns, duration=120, *, minimum_word_coverage=0.0):
    from pyannote.core import Annotation, Segment, Timeline
    from pyannote.metrics.diarization import DiarizationErrorRate

    review_speakers([], [], [], minimum_word_coverage=minimum_word_coverage)
    # Use the same strict fixed-window reference/prediction validation as DER.
    der = score_segments(words, turns, 0, duration)

    def annotation(rows):
        out = Annotation()
        for i, row in enumerate(rows):
            out[Segment(row["start"], row["end"]), i] = row["speaker"]
        return out.support()

    mapping = DiarizationErrorRate(collar=0, skip_overlap=False).optimal_mapping(
        annotation(words), annotation(turns), uem=Timeline([Segment(0, duration)])
    )
    predictions = [SpeakerTurn(**{k: t[k] for k in ("start", "end", "speaker")}) for t in turns]
    counts = dict(correct=0, wrong=0, unresolved=0)
    boundary = 0
    weak_coverage = dict(correct=0, wrong=0)
    for w in words:
        text = w["text"]
        if not isinstance(text, str) or not squeeze(text):
            raise ValueError("Missing manual word")
        size = len(squeeze(text))
        if type(w.get("boundary_clipped", False)) is not bool:
            raise ValueError("Invalid boundary flag")
        if w.get("boundary_clipped"):
            counts["unresolved"] += size
            boundary += size
            continue
        cue = Cue(start=w["start"], end=w["end"], text=text)
        review = review_speakers(
            [cue],
            predictions,
            [[WordTiming(w["start"], w["end"], text)]],
            stage=2,
            minimum_word_coverage=minimum_word_coverage,
        )[0]
        assigned = review["words"][0]["speaker"] if len(review["words"]) == 1 else None
        kind = (
            "unresolved"
            if assigned in (None, MULTIPLE_SPEAKERS)
            else "correct"
            if mapping.get(assigned) == w["speaker"]
            else "wrong"
        )
        counts[kind] += size
        if kind in weak_coverage:
            spans = sorted(
                (max(w["start"], t["start"]), min(w["end"], t["end"]))
                for t in turns
                if t["speaker"] == assigned
                and max(w["start"], t["start"]) < min(w["end"], t["end"])
            )
            edge, covered = w["start"], 0.0
            for a, b in spans:
                covered += max(0.0, b - max(edge, a))
                edge = max(edge, b)
            # Diagnostic only: use the existing stage-2 majority criterion (0.8).
            # Never change primary word counts using this additional view.
            if covered / (w["end"] - w["start"]) < 0.8:
                weak_coverage[kind] += size
    return dict(
        **counts,
        minimum_word_coverage=minimum_word_coverage,
        total_characters=sum(counts.values()),
        boundary_unresolved_characters=boundary,
        assigned_characters_below_80_percent_coverage=weak_coverage,
        oracle_words_and_timing=True,
        asr_accuracy_measured=False,
        mapping="DER_optimal_anonymous_speaker_mapping",
        der=der,
        deploy_allowed=False,
    )


def validate_reference(reference):
    if (
        reference.get("word_timing_source") != "human_manual_AMI"
        or reference.get("asr_evaluated") is not False
        or (reference.get("evaluation_start"), reference.get("evaluation_end")) != (0, 120)
        or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("pilot_lock_sha256", "")))
    ):
        raise ValueError("Manual reference provenance or window missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("reference", "prediction", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--minimum-word-coverage", type=float, default=0.0)
    args = parser.parse_args()
    reference, prediction = load_json(args.reference), load_json(args.prediction)
    validate_reference(reference)
    if reference["audio_sha256"] != prediction["source_sha256"]:
        raise ValueError(
            "Different audio; analysis copies require a separate provenance comparison"
        )
    result = score(
        reference["segments"],
        prediction["turns"],
        reference["evaluation_end"],
        minimum_word_coverage=args.minimum_word_coverage,
    )
    result["sha256"] = {k: sha256(getattr(args, k)) for k in ("reference", "prediction")}
    write_private_json(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
