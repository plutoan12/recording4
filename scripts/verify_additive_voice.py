"""Test independent acoustic and ASR support for gap additions; preserve all baseline words."""

import argparse
import copy
import math
from pathlib import Path

from prepare_additive_retry import overlaps
from prepare_conversation_evaluation import load_json
from probe_voice_anchors import solo_spans, voice_check
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def reasons(anchor_status, similarity, margin, expected, recognized, duration):
    failures = []
    if duration < 0.5:
        failures.append("query_too_short")
    if anchor_status != "candidate_only":
        failures.append("unreliable_anchor")
    if not all(math.isfinite(x) for x in (similarity, margin)) or similarity < 0.6 or margin < 0.15:
        failures.append("insufficient_voice_match")
    if not normalize(expected) or normalize(expected) != normalize(recognized):
        failures.append("independent_asr_disagrees")
    return failures


def append_preserving_baseline(baseline, additions):
    result = copy.deepcopy(baseline)
    for word in sorted(additions, key=lambda w: (w["start"], w["end"])):
        # Refuse colliding additions from different models rather than picking a winner.
        if any(overlaps(word["start"], word["end"], old) for old in result):
            raise ValueError("Addition collides with an existing word")
        index = next(
            (i for i, old in enumerate(result) if old["start"] > word["start"]), len(result)
        )
        result.insert(index, dict(word, added=True))
    return result


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from faster_whisper import WhisperModel
    from speechbrain.inference.speaker import EncoderClassifier

    p = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "proposals", "model", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    fingerprints = {k: sha256(getattr(args, k)) for k in ["audio", "proposals"]}
    proposal = load_json(args.proposals)
    if proposal["source_sha256"] != fingerprints["audio"]:
        raise ValueError("Audio changed")
    audio, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError("Require finite mono 16k audio")
    encoder = EncoderClassifier.from_hparams(
        source=str(args.model), savedir="/tmp/additive-ecapa", run_opts={"device": "cpu"}
    )
    asr = WhisperModel(
        "small", device="cpu", compute_type="int8", cpu_threads=2, local_files_only=True
    )

    def embed(samples):
        with torch.no_grad():
            vector = (
                encoder.encode_batch(torch.from_numpy(samples.copy()).unsqueeze(0))
                .flatten()
                .numpy()
            )
        return vector / max(np.linalg.norm(vector), 1e-8)

    audits = []
    additions = []
    for item in proposal["candidates"]:
        a, b = item["start"], item["end"]
        if not 0 <= a < b <= len(audio) / rate:
            raise ValueError("Invalid candidate interval")
        spans = solo_spans(item["turns"], len(audio) / rate)
        vectors = {}
        pairs = {}
        solo_seconds = {}
        for label, intervals in spans.items():
            # Anchor audio must be disjoint from the candidate, including context.
            fragments = []
            for x, y in intervals:
                for left, right in [(x, min(y, a - 1)), (max(x, b + 1), y)]:
                    if right - left >= 0.5:
                        fragments.append(audio[int(left * rate) : int(right * rate)])
            samples = np.concatenate(fragments) if fragments else np.empty(0, dtype="float32")
            solo_seconds[label] = len(samples) / rate
            if len(samples) < rate:
                continue
            pairs[label] = [embed(part) for part in np.array_split(samples, 2)]
            vectors[label] = embed(samples)
        target = item["target"]
        anchor_status = "missing_clean_anchor"
        similarity = margin = -1.0
        if target in vectors:
            query = embed(audio[int(a * rate) : int(b * rate)])
            similarity = float(np.dot(query, vectors[target]))
            if len(vectors) > 1:
                cross = [
                    float(np.dot(x, y))
                    for label, other in pairs.items()
                    if label != target
                    for x in pairs[target]
                    for y in other
                ]
                anchor_status = voice_check(float(np.dot(*pairs[target])), cross)["status"]
                margin = similarity - max(
                    float(np.dot(query, v)) for label, v in vectors.items() if label != target
                )
            else:
                anchor_status = "missing_competing_anchor"
        begin, end = max(0, int((a - 1) * rate)), min(len(audio), int((b + 1) * rate))
        segments, _ = asr.transcribe(
            audio[begin:end], language="en", beam_size=5, vad_filter=False, word_timestamps=True
        )
        recognized = []
        for segment in segments:
            for word in segment.words or []:
                start, finish = float(word.start) + begin / rate, float(word.end) + begin / rate
                if max(a, start) < min(b, finish):
                    recognized.append(word.word)
        expected = " ".join(w["text"] for w in item["words"])
        failures = reasons(anchor_status, similarity, margin, expected, " ".join(recognized), b - a)
        if not failures:
            additions.extend(item["words"])
        audits.append(
            dict(
                id=item["id"],
                duration=b - a,
                anchor_seconds=solo_seconds,
                target_anchor_available=target in vectors,
                comparison_available=target in vectors and len(vectors) > 1,
                anchor_status=anchor_status,
                voice_similarity=similarity,
                voice_margin=margin,
                independent_asr_text=" ".join(recognized),
                reasons=failures,
                proposed_words=len(item["words"]),
                accepted=not failures,
            )
        )
    candidate = append_preserving_baseline(proposal["baseline"], additions)
    if any(sha256(getattr(args, k)) != v for k, v in fingerprints.items()):
        raise ValueError("Inputs changed")
    result = dict(
        original=proposal["baseline"],
        candidate=candidate,
        audit=audits,
        sha256=fingerprints,
        accepted_words=len(additions),
        deploy_allowed=False,
        voice_identity_proven=False,
    )
    write_private_json(args.output, result)
    print(
        [
            dict(
                id=x["id"],
                reasons=x["reasons"],
                voice_similarity=x["voice_similarity"],
                voice_margin=x["voice_margin"],
                anchor_status=x["anchor_status"],
            )
            for x in audits
        ]
    )


if __name__ == "__main__":
    main()
