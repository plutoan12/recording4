#!/usr/bin/env python3
"""Evaluate new read speech and a separately annotated real conversation."""

import argparse
import json
import os
from pathlib import Path

from verify_transcribe import distance, squeeze

from worker.analysis import diarize, transcribe


def main():
    import subprocess

    from pyannote.core import Annotation, Segment
    from pyannote.metrics.diarization import DiarizationErrorRate

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = (
        json.loads(args.output.read_text())
        if args.output.exists()
        else {"read_speech": [], "real_conversation": None}
    )
    for lang in ["ko", "en", "ja", "zh"]:
        directory = args.root / f"new-{lang}-speech"
        expected = json.loads((directory / "expected.json").read_text())["sentences"]
        for i, entry in enumerate(expected):
            if any(r["id"] == f"fleurs-{lang}-new-{i}" for r in report["read_speech"]):
                continue
            cues = transcribe(directory / f"human{i}.wav", language=lang, model="small")
            actual = " ".join(c.text for c in cues)
            ref = squeeze(entry["text"]).casefold()
            hyp = squeeze(actual).casefold()
            row = dict(
                id=f"fleurs-{lang}-new-{i}",
                language=lang,
                reference_characters=len(ref),
                errors=distance(ref, hyp),
                cer=distance(ref, hyp) / max(1, len(ref)),
                hypothesis=actual,
            )
            report["read_speech"].append(row)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(row["id"], round(row["cer"], 4), flush=True)
    path = args.root / "ami-new"
    audio = args.root / "ami-first120.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path / "source.wav"),
            "-t",
            "120",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio),
        ],
        check=True,
    )
    ref = json.loads((path / "reference.json").read_text())
    truth = Annotation()
    for i, (a, b, lab) in enumerate(
        zip(ref["timestamps_start"], ref["timestamps_end"], ref["speakers"], strict=True)
    ):
        if a < 120 and b > 0:
            truth[Segment(max(0, a), min(120, b)), i] = lab
    turns = diarize(audio, token=os.environ["R4_HF_TOKEN"])
    prediction = Annotation()
    for i, t in enumerate(turns):
        prediction[Segment(t.start, t.end), i] = t.speaker
    metric = DiarizationErrorRate(collar=0.0, skip_overlap=False)
    details = metric(truth, prediction, detailed=True)
    report["real_conversation"] = {k: float(v) for k, v in details.items()}
    report["real_conversation"].update(
        reference_speakers=len(truth.labels()),
        predicted_speakers=len(prediction.labels()),
        duration=120,
        source="diarizers-community/ami ihm test row0",
        collar=0,
        skip_overlap=False,
    )
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(report["real_conversation"], flush=True)


if __name__ == "__main__":
    main()
