#!/usr/bin/env python3
"""Compare legacy and word-level speaker assignment on the same 11 saved WAVs.

Unresolved characters count against correct coverage, never as correct labels.
The source text belongs to a known isolated speaker; activity matching uses the
same energy proxy as measure_diarization_stress, not manually annotated DER.
"""

import argparse
import hashlib
import io
import itertools
import json
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np
from measure_diarization_stress import render_case, score

from pipeline.alignment import WordTiming, squeeze
from pipeline.editing import Cue
from pipeline.speakers import MULTIPLE_SPEAKERS, SpeakerTurn, assign_speakers, review_speakers
from worker.analysis import align_speaker_words, diarize


def verify_fixture(path, rendered, case):
    import soundfile as sf

    x = rendered
    with io.BytesIO() as buffer:
        sf.write(buffer, x, 16000, format="WAV", subtype="PCM_16")
        buffer.seek(0)
        regenerated, _ = sf.read(buffer, dtype="int16")
    actual, rate = sf.read(path, dtype="int16")
    if rate != 16000 or not np.array_equal(actual, regenerated):
        raise ValueError(f"Source/recipe no longer describes fixture: {case['case']}")


def main():
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", type=int, choices=[1, 2, 3, 4], default=1)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--reconsider", action="store_true")
    args = parser.parse_args()
    if args.reconsider and args.stage != 4:
        parser.error("--reconsider requires --stage 4")
    pieces = []
    for name in ["mono-a0.wav", "mono-b0.wav", "mono-a1.wav", "mono-b1.wav"]:
        x, sr = sf.read(args.directory / name, dtype="float32")
        assert sr == 16000
        pieces.append(x * (0.08 / max(np.sqrt(np.mean(x * x)), 1e-8)))
    texts = [
        s["text"] for s in json.loads((args.directory / "expected.json").read_text())["sentences"]
    ]
    cases = json.loads((args.fixtures / "metrics.json").read_text())["cases"]
    results = []
    args.output.mkdir(parents=True, exist_ok=True)
    for case in cases:
        path = args.fixtures / (case["case"] + ".wav")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        mixture, truth, active = render_case(
            pieces, case["overlap_fraction_of_shorter_clip"], case["snr_db"], case["seed"]
        )
        verify_fixture(path, mixture, case)
        cues = [
            Cue(start=t["start"], end=t["end"], text=text)
            for t, text in zip(truth, texts, strict=True)
        ]
        cache = args.cache / (case["case"] + "-raw.json") if args.cache else None
        if cache and cache.exists():
            raw = json.loads(cache.read_text())
            assert raw["sha256"] == before
            turns = [SpeakerTurn(**t) for t in raw["turns"]]
            words = [[WordTiming(**w) for w in ws] for ws in raw["words"]]
        else:
            turns = diarize(path, token=os.environ["R4_HF_TOKEN"], device="cpu")
            words = align_speaker_words(path, cues, language="en", device="cpu")
            if cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(
                    json.dumps(
                        dict(
                            sha256=before,
                            turns=[asdict(t) for t in turns],
                            words=[[asdict(w) for w in ws] for ws in words],
                        )
                    )
                )
        old = assign_speakers(cues, turns)
        reviews = review_speakers(cues, turns, words, stage=min(args.stage, 2))
        if args.stage >= 3:
            from worker.speaker_recovery import recover_speaker_reviews

            reviews = recover_speaker_reviews(
                path,
                cues,
                turns,
                words,
                language="en",
                stage=args.stage,
                audit_dir=args.output / (case["case"] + "-audit"),
                reconsider=args.reconsider,
            )
        labs = sorted({t.speaker for t in turns})
        n = active.shape[1]
        centers = (np.arange(n) + 0.5) * 0.02
        pred = np.zeros((len(labs), n), bool)
        for t in turns:
            pred[labs.index(t.speaker)] |= (centers >= t.start) & (centers < t.end)
        permutations = list(itertools.permutations(labs + [None] * max(0, 2 - len(labs)), 2))
        best = max(
            permutations,
            key=lambda perm: sum(
                np.logical_and(active[i], pred[labs.index(lab)]).sum() if lab is not None else 0
                for i, lab in enumerate(perm)
            ),
        )
        mapping = dict(zip(["A", "B"], best, strict=True))
        counts = {
            "total_characters": 0,
            "legacy_correct": 0,
            "legacy_wrong": 0,
            "legacy_unresolved": 0,
            "word_correct": 0,
            "word_wrong": 0,
            "word_unresolved": 0,
        }
        for cue, t, legacy, review in zip(cues, truth, old, reviews, strict=True):
            total = len(squeeze(cue.text))
            expected = mapping[t["speaker"]]
            counts["total_characters"] += total
            counts[
                "legacy_unresolved"
                if legacy in (None, MULTIPLE_SPEAKERS)
                else "legacy_correct"
                if legacy == expected
                else "legacy_wrong"
            ] += total
            if not review["alignment_available"]:
                counts["word_unresolved"] += total
                continue
            for word in review["words"]:
                label = word["speaker"]
                length = len(squeeze(word["text"]))
                counts[
                    "word_unresolved"
                    if label in (None, MULTIPLE_SPEAKERS)
                    else "word_correct"
                    if label == expected
                    else "word_wrong"
                ] += length
        assert counts["total_characters"] == sum(
            counts[k] for k in ["word_correct", "word_wrong", "word_unresolved"]
        )
        r = {
            "case": case["case"],
            "requested_stage": args.stage,
            "oracle_cue_text_and_boundaries": True,
            "recovery_rejections": [
                reason for r in reviews for reason in r.get("recovery_rejections", [])
            ],
            "sha256": before,
            "baseline": score(turns, truth, active),
            "review_segments": sum(r["needs_review"] for r in reviews),
            "aligned_segments": sum(r["alignment_available"] for r in reviews),
            **counts,
        }
        assert before == hashlib.sha256(path.read_bytes()).hexdigest()
        (args.output / (case["case"] + "-words.json")).write_text(
            json.dumps(reviews, ensure_ascii=False, indent=2)
        )
        results.append(r)
        (args.output / "comparison.json").write_text(json.dumps(results, indent=2))
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
