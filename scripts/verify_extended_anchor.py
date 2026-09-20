"""Verify whether later audio supplies clean anchors for an unchanged evaluation candidate."""

import argparse
import itertools
import math
from pathlib import Path

from prepare_conversation_evaluation import load_json
from probe_voice_anchors import solo_spans, voice_check
from run_sortformer_evaluation import sha256, write_private_json


def _merged(turns, label, start, end):
    result = []
    for turn in sorted(
        (t for t in turns if t["speaker"] == label and t["start"] < end and t["end"] > start),
        key=lambda t: (t["start"], t["end"]),
    ):
        a, b = max(start, turn["start"]), min(end, turn["end"])
        if result and a <= result[-1][1]:
            result[-1][1] = max(result[-1][1], b)
        else:
            result.append([a, b])
    return result


def _duration(intervals):
    return sum(b - a for a, b in intervals)


def _intersection(left, right):
    return sum(max(0, min(b, d) - max(a, c)) for a, b in left for c, d in right)


def map_labels(original, extended, evaluation_end, minimum_coverage=0.8):
    """Map anonymous labels only when temporal support is unique and bidirectionally strong."""
    if not math.isfinite(minimum_coverage) or not 0 <= minimum_coverage <= 1:
        raise ValueError("Invalid mapping coverage")
    old_labels = sorted({t["speaker"] for t in original})
    new_labels = sorted({t["speaker"] for t in extended if t["start"] < evaluation_end})
    if len(new_labels) < len(old_labels):
        raise ValueError("Extended prediction has fewer labels in the shared interval")
    old = {x: _merged(original, x, 0, evaluation_end) for x in old_labels}
    new = {x: _merged(extended, x, 0, evaluation_end) for x in new_labels}
    support = {(a, b): _intersection(old[a], new[b]) for a in old_labels for b in new_labels}
    assignments = []
    for chosen in itertools.permutations(new_labels, len(old_labels)):
        mapping = dict(zip(old_labels, chosen, strict=True))
        assignments.append((sum(support[a, b] for a, b in mapping.items()), mapping))
    assignments.sort(key=lambda x: x[0], reverse=True)
    if len(assignments) > 1 and assignments[0][0] == assignments[1][0]:
        raise ValueError("Ambiguous label mapping")
    mapping = assignments[0][1]
    audit = {}
    for a, b in mapping.items():
        overlap = support[a, b]
        old_coverage = overlap / _duration(old[a]) if _duration(old[a]) else 0
        new_purity = overlap / _duration(new[b]) if _duration(new[b]) else 0
        old_best = max(support[a, x] for x in new_labels)
        new_best = max(support[x, b] for x in old_labels)
        unique = (
            support[a, b] > 0
            and [x for x in new_labels if support[a, x] == old_best] == [b]
            and [x for x in old_labels if support[x, b] == new_best] == [a]
        )
        accepted = unique and old_coverage >= minimum_coverage and new_purity >= minimum_coverage
        audit[a] = dict(
            extended_label=b,
            overlap_seconds=overlap,
            original_coverage=old_coverage,
            extended_purity=new_purity,
            unique_mutual_best=unique,
            accepted=accepted,
        )
        if not accepted:
            raise ValueError("Label mapping lacks fixed temporal support")
    return mapping, audit


def later_solo_spans(turns, evaluation_end, duration):
    result = solo_spans(turns, duration)
    return {
        label: [(max(a, evaluation_end), b) for a, b in spans if b - max(a, evaluation_end) >= 0.5]
        for label, spans in result.items()
    }


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    parser = argparse.ArgumentParser(description=__doc__)
    for name in [
        "evaluation-audio",
        "extended-audio",
        "original-prediction",
        "extended-prediction",
        "proposals",
        "prior-verification",
        "model",
        "output",
    ]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--alternative-prediction", type=Path)
    args = parser.parse_args()
    files = [
        "evaluation_audio",
        "extended_audio",
        "original_prediction",
        "extended_prediction",
        "proposals",
        "prior_verification",
    ]
    if args.alternative_prediction:
        files.append("alternative_prediction")
    fingerprints = {name: sha256(getattr(args, name)) for name in files}
    proposal = load_json(args.proposals)
    prior = load_json(args.prior_verification)
    original = load_json(args.original_prediction)
    extended = load_json(args.extended_prediction)
    alternative = load_json(args.alternative_prediction) if args.alternative_prediction else None
    evaluation, rate = sf.read(args.evaluation_audio, dtype="float32")
    audio, extended_rate = sf.read(args.extended_audio, dtype="float32")
    if rate != 16000 or extended_rate != rate or evaluation.ndim != 1 or audio.ndim != 1:
        raise ValueError("Require mono 16k audio")
    if not np.isfinite(evaluation).all() or not np.isfinite(audio).all():
        raise ValueError("Require finite audio")
    if len(audio) <= len(evaluation) or not np.array_equal(audio[: len(evaluation)], evaluation):
        raise ValueError("Extended audio does not exactly preserve evaluation prefix")
    if proposal["source_sha256"] != fingerprints["evaluation_audio"]:
        raise ValueError("Proposal evaluation audio changed")
    if original["source_sha256"] != fingerprints["evaluation_audio"]:
        raise ValueError("Original prediction audio changed")
    if extended["source_sha256"] != fingerprints["extended_audio"]:
        raise ValueError("Extended prediction audio changed")
    if alternative and alternative["source_sha256"] != fingerprints["extended_audio"]:
        raise ValueError("Alternative prediction audio changed")
    if prior["sha256"]["proposals"] != fingerprints["proposals"]:
        raise ValueError("Prior verification used different proposals")
    evaluation_end = len(evaluation) / rate
    # Validate every original turn before using it for anonymous-label identity mapping.
    solo_spans(original["turns"], evaluation_end)
    mapping, mapping_audit = map_labels(original["turns"], extended["turns"], evaluation_end)
    spans = later_solo_spans(extended["turns"], evaluation_end, len(audio) / rate)
    encoder = EncoderClassifier.from_hparams(
        source=str(args.model), savedir="/tmp/extended-anchor-ecapa", run_opts={"device": "cpu"}
    )

    def embed(samples):
        with torch.no_grad():
            vector = (
                encoder.encode_batch(torch.from_numpy(samples.copy()).unsqueeze(0))
                .flatten()
                .numpy()
            )
        return vector / max(np.linalg.norm(vector), 1e-8)

    vectors, pairs, seconds = {}, {}, {}
    for label, intervals in spans.items():
        pieces = [audio[int(a * rate) : int(b * rate)] for a, b in intervals]
        samples = np.concatenate(pieces) if pieces else np.empty(0, dtype="float32")
        seconds[label] = len(samples) / rate
        if len(samples) < rate:
            continue
        pairs[label] = [embed(part) for part in np.array_split(samples, 2)]
        vectors[label] = embed(samples)
    alternative_vectors, alternative_seconds = {}, {}
    if alternative:
        alternative_spans = later_solo_spans(
            alternative["turns"], evaluation_end, len(audio) / rate
        )
        for label, intervals in alternative_spans.items():
            pieces = [audio[int(a * rate) : int(b * rate)] for a, b in intervals]
            samples = np.concatenate(pieces) if pieces else np.empty(0, dtype="float32")
            alternative_seconds[label] = len(samples) / rate
            if len(samples) >= rate:
                alternative_vectors[label] = embed(samples)
    prior_by_id = {x["id"]: x for x in prior["audit"]}
    candidate_ids = [x["id"] for x in proposal["candidates"]]
    if len(prior_by_id) != len(prior["audit"]) or set(prior_by_id) != set(candidate_ids):
        raise ValueError("Prior verification candidates changed")
    audits = []
    for item in proposal["candidates"]:
        target = mapping[item["target"]]
        status = "missing_clean_anchor"
        similarity = margin = None
        if target in vectors:
            query = embed(audio[int(item["start"] * rate) : int(item["end"] * rate)])
            similarity = float(np.dot(query, vectors[target]))
            competitors = {label: v for label, v in vectors.items() if label != target}
            if competitors:
                cross = [
                    float(np.dot(x, y))
                    for label, other in pairs.items()
                    if label != target
                    for x in pairs[target]
                    for y in other
                ]
                status = voice_check(float(np.dot(*pairs[target])), cross)["status"]
                margin = similarity - max(float(np.dot(query, v)) for v in competitors.values())
            else:
                status = "missing_competing_anchor"
        else:
            query = embed(audio[int(item["start"] * rate) : int(item["end"] * rate)])
        voice_passed = (
            status == "candidate_only"
            and similarity is not None
            and margin is not None
            and similarity >= 0.6
            and margin >= 0.15
        )
        prior_audit = prior_by_id[item["id"]]
        accepted = voice_passed and not prior_audit["reasons"]
        audits.append(
            dict(
                id=item["id"],
                target_extended_label=target,
                anchor_seconds=seconds,
                anchor_status=status,
                voice_similarity=similarity,
                voice_margin=margin,
                alternative_anchor_seconds=alternative_seconds,
                alternative_voice_similarities={
                    label: float(np.dot(query, vector))
                    for label, vector in alternative_vectors.items()
                },
                alternative_evidence_only=alternative is not None,
                prior_reasons=prior_audit["reasons"],
                accepted=accepted,
            )
        )
    if any(sha256(getattr(args, name)) != digest for name, digest in fingerprints.items()):
        raise ValueError("Inputs changed")
    result = dict(
        audit=audits,
        mapping=mapping,
        mapping_audit=mapping_audit,
        sha256=fingerprints,
        accepted_words=sum(
            len(item["words"])
            for item, audit in zip(proposal["candidates"], audits, strict=True)
            if audit["accepted"]
        ),
        evaluation_output_changed=False,
        deployment_allowed=False,
    )
    write_private_json(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
