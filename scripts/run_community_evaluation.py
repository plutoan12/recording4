#!/usr/bin/env python3
"""Run cached Community-1 diarization on one private WAV outside production."""

import argparse
import math
import os
import time
import wave
from pathlib import Path

from run_sortformer_evaluation import sha256, write_private_json


def validated_turns(turns, duration):
    result = []
    for turn in turns:
        start, end, speaker = float(turn.start), float(turn.end), str(turn.speaker)
        if (
            not all(math.isfinite(value) for value in (start, end))
            or not 0 <= start < end <= duration
            or not speaker
        ):
            raise ValueError("Invalid diarization turn")
        result.append(dict(start=start, end=end, speaker=speaker))
    if not result:
        raise ValueError("No diarization turns")
    return sorted(result, key=lambda turn: (turn["start"], turn["end"], turn["speaker"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    with wave.open(str(args.audio), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16000, 2):
            parser.error("Expected mono 16 kHz PCM16 WAV")
        duration = source.getnframes() / source.getframerate()
    if duration <= 0:
        parser.error("Empty audio")
    audio_sha = sha256(args.audio)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from worker.analysis import diarize

    started = time.monotonic()
    turns = validated_turns(
        diarize(args.audio, token="offline-cache-only", device=args.device), duration
    )
    elapsed = time.monotonic() - started
    if sha256(args.audio) != audio_sha:
        raise ValueError("Audio changed during inference")
    write_private_json(
        args.output,
        dict(
            schema=1,
            source_sha256=audio_sha,
            model="pyannote/speaker-diarization-community-1",
            model_revision=args.model_revision,
            device=args.device,
            duration_seconds=duration,
            elapsed_seconds=elapsed,
            turns=turns,
            deploy_allowed=False,
        ),
    )
    print({"turn_count": len(turns), "deploy_allowed": False})


if __name__ == "__main__":
    main()
