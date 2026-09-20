"""Offline speech-gap retry experiment; prediction-only selection, no speaker reassignment."""

import argparse
from pathlib import Path

from prepare_conversation_evaluation import load_json, number
from run_sortformer_evaluation import sha256, write_private_json


def union(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def retry_regions(baseline, alternate, duration):
    if not number(duration) or not 0 < duration <= 120:
        raise ValueError("This experiment requires at most 120 seconds")
    for t in baseline + alternate:
        if (
            not number(t["start"])
            or not number(t["end"])
            or not 0 <= t["start"] < t["end"] <= duration
        ):
            raise ValueError("Invalid prediction interval")
    cores = union((t["start"], t["end"]) for t in alternate)
    for a, b in union((t["start"], t["end"]) for t in baseline):
        remaining = []
        for left, right in cores:
            if b <= left or a >= right:
                remaining.append([left, right])
            else:
                if left < a:
                    remaining.append([left, a])
                if b < right:
                    remaining.append([b, right])
        cores = remaining
    crops = union((max(0, a - 1), min(duration, b + 1)) for a, b in cores)
    return cores, crops


def inside(word, cores):
    if word.get("timing_valid") is False:
        return False
    midpoint = (word["start"] + word["end"]) / 2
    return any(a <= midpoint < b for a, b in cores)


def splice(baseline, retries, cores):
    # Keep context words from the baseline only; never duplicate crop padding.
    kept = [w for w in baseline if not inside(w, cores)]
    additions = [w for w in retries if inside(w, cores)]
    return sorted(kept + additions, key=lambda w: (w["start"], w["end"]))


def main():
    import numpy as np
    import soundfile as sf
    from faster_whisper import WhisperModel

    p = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "baseline", "alternate", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    fingerprints = {k: sha256(getattr(args, k)) for k in ["audio", "baseline", "alternate"]}
    predictions = [load_json(args.baseline), load_json(args.alternate)]
    if any(v["source_sha256"] != fingerprints["audio"] for v in predictions):
        raise ValueError("Different source audio")
    audio, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError("Require finite 16k mono audio")
    duration = len(audio) / rate
    cores, crops = retry_regions(*(v["turns"] for v in predictions), duration)
    model = WhisperModel(
        "small", device="cpu", compute_type="int8", cpu_threads=2, local_files_only=True
    )

    def recognize(samples, offset, vad):
        segments, _ = model.transcribe(
            samples, language="en", beam_size=5, vad_filter=vad, word_timestamps=True
        )
        words = []
        for segment in segments:
            for w in segment.words or []:
                start, end = float(w.start), float(w.end)
                if not number(start) or not number(end):
                    raise ValueError("Nonfinite ASR timing")
                words.append(
                    dict(
                        start=start + offset,
                        end=end + offset,
                        text=w.word,
                        timing_valid=0 <= start < end <= len(samples) / rate,
                    )
                )
        return words

    original = recognize(audio, 0, True)
    retries = []
    failed_crops = []
    effective_cores = list(cores)
    for a, b in crops:
        begin, end = int(a * rate), int(b * rate)
        crop_words = recognize(audio[begin:end], begin / rate, False)
        retries.extend(crop_words)
        if any(not w["timing_valid"] for w in crop_words):
            failed_crops.append(dict(start=a, end=b, reason="invalid_word_timing"))
            effective_cores = [[x, y] for x, y in effective_cores if y <= a or x >= b]
    candidate = splice(original, retries, effective_cores)
    if any(sha256(getattr(args, k)) != v for k, v in fingerprints.items()):
        raise ValueError("Inputs changed")
    result = dict(
        sha256=fingerprints,
        language="en",
        duration=duration,
        model="faster-whisper-small",
        compute_type="int8",
        beam_size=5,
        baseline_vad=True,
        retry_vad=False,
        cores=cores,
        effective_cores=effective_cores,
        failed_crops=failed_crops,
        crops=crops,
        original=original,
        retries=retries,
        candidate=candidate,
        speaker_assignment_changed=False,
        deploy_allowed=False,
    )
    write_private_json(args.output, result)
    print(
        dict(
            crop_count=len(crops),
            core_seconds=sum(b - a for a, b in cores),
            baseline_words=len(original),
            candidate_words=len(candidate),
            deploy_allowed=False,
        )
    )


if __name__ == "__main__":
    main()
