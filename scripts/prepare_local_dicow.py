"""Prepare the frozen English local DiCoW pilot from existing private evaluation artifacts."""

import argparse
import hashlib
import json
from pathlib import Path

from pyannote.core import Annotation, Segment, Timeline
from pyannote.metrics.diarization import DiarizationErrorRate
from run_sortformer_evaluation import write_private_json

from pipeline.speaker_disagreement import compare_turns, overlap_retry_windows

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--inputs-root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = args.inputs_root
out = args.output
out.mkdir(mode=0o700, exist_ok=False)
refpath = root / "reference-link-20260920/en-words-reviewed.json"
ref = json.loads(refpath.read_text())
audio = root / "multilingual-20260920/en.wav"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


if (
    ref["audio_sha256"] != sha(audio)
    or ref.get("word_timing_source") != "human_manual_AMI"
    or (ref["evaluation_start"], ref["evaluation_end"]) != (0, 120)
):
    raise ValueError("Reference or audio changed")
pred = {
    m: json.loads((root / f"multilingual-20260920/en-{m}.json").read_text())
    for m in ["community", "sortformer"]
}
if not all(v["source_sha256"] == sha(audio) for v in pred.values()):
    raise ValueError("Prediction audio changed")
windows = overlap_retry_windows(
    compare_turns(pred["community"]["turns"], pred["sortformer"]["turns"], 120), 120
)


def ann(rows):
    a = Annotation()
    for i, t in enumerate(rows):
        a[Segment(t["start"], t["end"]), i] = t["speaker"]
    return a.support()


labels = sorted({w["speaker"] for w in ref["segments"]})
manifest = []
slots = []
for model, p in pred.items():
    mapping = DiarizationErrorRate(collar=0, skip_overlap=False).optimal_mapping(
        ann(ref["segments"]), ann(p["turns"]), uem=Timeline([Segment(0, 120)])
    )
    if set(mapping) != {t["speaker"] for t in p["turns"]}:
        raise ValueError("Unmapped predicted targets require explicit insertion slots")
    inverse = {v: k for k, v in mapping.items()}
    # Decode ALL predicted targets: reference mapping only attaches evaluation text.
    for i, window in enumerate(windows):
        a, b = window["start"], window["end"]
        for target in sorted({t["speaker"] for t in p["turns"]}):
            words = [
                w
                for w in ref["segments"]
                if w["speaker"] == mapping.get(target) and w["start"] < b and w["end"] > a
            ]
            manifest.append(
                dict(
                    id=f"{model}-{i}-{target}",
                    audio=str(audio),
                    language="en",
                    target=target,
                    turns=p["turns"],
                    start=a,
                    end=b,
                    reference=" ".join(w["text"] for w in words),
                )
            )
        for label in labels:
            words = [
                w
                for w in ref["segments"]
                if w["speaker"] == label and w["start"] < b and w["end"] > a
            ]
            slots.append(
                dict(
                    model=model,
                    window=i,
                    reference=" ".join(w["text"] for w in words),
                    row_id=f"{model}-{i}-{inverse[label]}" if label in inverse else None,
                    boundary_words=sum(w["start"] < a or w["end"] > b for w in words),
                )
            )
write_private_json(out / "manifest.json", manifest)
write_private_json(out / "slots.json", slots)
write_private_json(
    out / "protocol.json",
    dict(
        windows=windows,
        reference_sha256=sha(refpath),
        audio_sha256=sha(audio),
        manifest_sha256=sha(out / "manifest.json"),
        slots_sha256=sha(out / "slots.json"),
        boundary_policy=(
            "include full text of every intersecting manual word; "
            "conservative clipped-word diagnostic"
        ),
        missing_speaker_policy="empty hypothesis, reference remains",
        empty_reference_policy="insertions counted, individual CER undefined",
        decode_rows=len(manifest),
        deployment_allowed=False,
    ),
)
print("windows", len(windows), "rows", len(manifest), "scoring slots", len(slots))
