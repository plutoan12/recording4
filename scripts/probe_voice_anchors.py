"""Probe predicted solo voice anchors; never turn these scores into speaker approval."""

import argparse
import math
from pathlib import Path

from prepare_conversation_evaluation import load_json, number
from run_sortformer_evaluation import sha256, write_private_json


def solo_spans(turns, duration):
    if not number(duration) or duration <= 0:
        raise ValueError("Invalid duration")
    for t in turns:
        if (
            not number(t["start"])
            or not number(t["end"])
            or not 0 <= t["start"] < t["end"] <= duration
            or not isinstance(t["speaker"], str)
            or not t["speaker"]
        ):
            raise ValueError("Invalid turn")
    result = {}
    for label in sorted({t["speaker"] for t in turns}):
        merged = []
        for a, b in sorted((t["start"], t["end"]) for t in turns if t["speaker"] == label):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(b, merged[-1][1])
            else:
                merged.append([a, b])
        for other in turns:
            if other["speaker"] == label:
                continue
            remaining = []
            for a, b in merged:
                if other["end"] <= a or other["start"] >= b:
                    remaining.append([a, b])
                else:
                    if a < other["start"]:
                        remaining.append([a, other["start"]])
                    if other["end"] < b:
                        remaining.append([other["end"], b])
            merged = remaining
        result[label] = [(a, b) for a, b in merged if b - a >= 0.5]
    return result


def voice_check(within, cross):
    if not all(math.isfinite(x) for x in [within, *cross]) or not cross:
        return dict(status="insufficient_evidence")
    maximum = max(cross)
    # Existing recovery voice criteria, fixed before this probe.
    return dict(
        within_similarity=within,
        maximum_cross_similarity=maximum,
        margin=within - maximum,
        status="candidate_only"
        if within >= 0.6 and within - maximum >= 0.15
        else "rejected_acoustic_consistency",
    )


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    p = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "prediction", "model", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    fingerprints = {k: sha256(getattr(args, k)) for k in ["audio", "prediction"]}
    prediction = load_json(args.prediction)
    if prediction["source_sha256"] != fingerprints["audio"]:
        raise ValueError("Different audio")
    audio, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError("Require finite 16k mono audio")
    spans = solo_spans(prediction["turns"], len(audio) / rate)
    encoder = EncoderClassifier.from_hparams(
        source=str(args.model), savedir="/tmp/r4-anchor-model", run_opts={"device": "cpu"}
    )
    vectors, report = {}, {}
    for label, intervals in spans.items():
        pieces = [audio[int(a * rate) : int(b * rate)] for a, b in intervals]
        selected = np.concatenate(pieces) if pieces else np.empty(0, dtype="float32")
        report[label] = dict(solo_seconds=len(selected) / rate, status="missing_clean_anchor")
        if len(selected) < rate:
            continue
        # Two disjoint halves. Consistency does not prove purity or true identity.
        halves = np.array_split(selected, 2)
        embeddings = []
        for half in halves:
            with torch.no_grad():
                v = (
                    encoder.encode_batch(torch.from_numpy(half.copy()).unsqueeze(0))
                    .flatten()
                    .numpy()
                )
            embeddings.append(v / max(np.linalg.norm(v), 1e-8))
        vectors[label] = embeddings
    for label, pair in vectors.items():
        cross = [
            float(np.dot(x, y))
            for other, others in vectors.items()
            if other != label
            for x in pair
            for y in others
        ]
        report[label].update(voice_check(float(np.dot(*pair)), cross))
    if any(sha256(getattr(args, k)) != v for k, v in fingerprints.items()):
        raise ValueError("Inputs changed")
    result = dict(
        sha256=fingerprints,
        anchors=report,
        model="speechbrain/spkrec-ecapa-voxceleb",
        model_hyperparameters_sha256=sha256(args.model / "hyperparams.yaml"),
        identity_mapping_verified=False,
        reference_purity_verified=False,
        deployment_allowed=False,
    )
    write_private_json(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
