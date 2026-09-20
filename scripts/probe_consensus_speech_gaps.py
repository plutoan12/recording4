"""Generate additive ASR candidates only where two diarizers agree speech is missing."""

import argparse
import math
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def merge_spans(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def consensus_gaps(words, predictions, duration, *, word_guard=0.1, minimum=0.5):
    if not math.isfinite(duration) or duration <= 0 or len(predictions) < 2:
        raise ValueError("Invalid consensus inputs")
    if not 0 <= word_guard <= 1 or not 0 < minimum <= duration:
        raise ValueError("Invalid gap policy")
    timelines = []
    for turns in predictions:
        spans = []
        for turn in turns:
            start, end = turn["start"], turn["end"]
            if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= duration:
                raise ValueError("Invalid prediction interval")
            spans.append((start, end))
        timelines.append(merge_spans(spans))
    common = timelines[0]
    for timeline in timelines[1:]:
        common = merge_spans(
            (max(a, c), min(b, d))
            for a, b in common
            for c, d in timeline
            if max(a, c) < min(b, d)
        )
    for word in words:
        if word.get("timing_valid") is False:
            continue
        start, end = word["start"], word["end"]
        if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start <= end <= duration:
            raise ValueError("Invalid word interval")
        occupied_start, occupied_end = max(0, start - word_guard), min(duration, end + word_guard)
        remaining = []
        for left, right in common:
            if occupied_end <= left or occupied_start >= right:
                remaining.append([left, right])
            else:
                if left < occupied_start:
                    remaining.append([left, occupied_start])
                if occupied_end < right:
                    remaining.append([occupied_end, right])
        common = remaining
    return [(start, end) for start, end in common if end - start >= minimum]


def main():
    import numpy as np
    import soundfile as sf
    from faster_whisper import WhisperModel

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "baseline", "primary", "alternate", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    names = ["audio", "baseline", "primary", "alternate"]
    fingerprints = {name: sha256(getattr(args, name)) for name in names}
    baseline = load_json(args.baseline)
    predictions = [load_json(args.primary), load_json(args.alternate)]
    if baseline["sha256"]["audio"] != fingerprints["audio"]:
        raise ValueError("Baseline audio changed")
    if any(prediction["source_sha256"] != fingerprints["audio"] for prediction in predictions):
        raise ValueError("Prediction audio changed")
    audio, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
        raise ValueError("Require finite mono 16k audio")
    duration = len(audio) / rate
    cores = consensus_gaps(
        baseline["original"], [prediction["turns"] for prediction in predictions], duration
    )
    model = WhisperModel(
        "small", device="cpu", compute_type="int8", cpu_threads=2, local_files_only=True
    )
    candidates = []
    audits = []
    for index, (start, end) in enumerate(cores):
        crop_start, crop_end = max(0, start - 1), min(duration, end + 1)
        begin, finish = int(crop_start * rate), int(crop_end * rate)
        segments, _ = model.transcribe(
            audio[begin:finish],
            language="en",
            beam_size=5,
            vad_filter=False,
            word_timestamps=True,
        )
        words = []
        for segment in segments:
            for word in segment.words or []:
                word_start = float(word.start) + begin / rate
                word_end = float(word.end) + begin / rate
                if not all(math.isfinite(x) for x in (word_start, word_end)):
                    raise ValueError("Nonfinite retry timing")
                if max(start, word_start) < min(end, word_end) and normalize(word.word):
                    words.append(dict(start=word_start, end=word_end, text=word.word))
        candidate_id = f"consensus-gap-{index}"
        audits.append(
            dict(
                id=candidate_id,
                start=start,
                end=end,
                crop_start=crop_start,
                crop_end=crop_end,
                proposed_words=len(words),
            )
        )
        if words:
            candidates.append(dict(id=candidate_id, start=start, end=end, words=words))
    if any(sha256(getattr(args, name)) != digest for name, digest in fingerprints.items()):
        raise ValueError("Inputs changed")
    result = dict(
        source_sha256=fingerprints["audio"],
        baseline=baseline["original"],
        candidates=candidates,
        audit=audits,
        policy=dict(word_guard_seconds=0.1, minimum_gap_seconds=0.5, context_seconds=1),
        sha256=fingerprints,
        selection_uses_reference=False,
        accepted_words=0,
        deployment_allowed=False,
    )
    write_private_json(args.output, result)
    print(
        dict(
            gap_count=len(cores),
            gap_seconds=sum(end - start for start, end in cores),
            candidate_groups=len(candidates),
            proposed_words=sum(len(item["words"]) for item in candidates),
        )
    )


if __name__ == "__main__":
    main()
