#!/usr/bin/env python3
"""Run a local Sortformer checkpoint on one private WAV, outside production.

No reference labels or speaker-count hints enter inference. The caller must use
a separate NeMo environment and a previously downloaded, trusted checkpoint.
Output contains private speaker turns: do not commit it.
"""

import argparse
import hashlib
import json
import math
import os
import time
import wave
from importlib.metadata import version
from pathlib import Path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_private_json(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


def parse_segments(result, duration):
    """NeMo's single-file result is a nested list of 'start end speaker' lines."""
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("Expected exactly one recording")
    if not isinstance(result[0], list):
        raise ValueError("Invalid segment collection")
    turns = []
    for line in result[0]:
        if not isinstance(line, str):
            raise ValueError("Invalid segment")
        start, end, speaker = line.split()
        start, end = float(start), float(end)
        if not all(math.isfinite(x) for x in (start, end)):
            raise ValueError("Non-finite segment")
        if not 0 <= start < end <= duration or speaker not in {f"speaker_{i}" for i in range(4)}:
            raise ValueError("Segment outside recording or unsupported speaker")
        turns.append(dict(start=start, end=end, speaker=speaker))
    # Empty results remain empty for the scorer to count as missed speech.
    return sorted(turns, key=lambda t: (t["start"], t["end"], t["speaker"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audio", "checkpoint", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    raw_path = args.output.with_suffix(".raw.json")
    if args.output.exists() or raw_path.exists() or raw_path == args.output or args.threads < 1:
        parser.error("Use a new output path and positive thread count")
    with wave.open(str(args.audio), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16000, 2):
            parser.error("Expected mono 16 kHz PCM16 WAV")
        duration = source.getnframes() / source.getframerate()
        if duration <= 0:
            parser.error("Empty audio")
    audio_sha = sha256(args.audio)
    checkpoint_sha = sha256(args.checkpoint)
    versions = {name: version(name) for name in ("nemo_toolkit", "torch")}
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["WANDB_MODE"] = "disabled"
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    started = time.monotonic()
    model = SortformerEncLabelModel.restore_from(
        restore_path=str(args.checkpoint), map_location="cpu", strict=True
    )
    model.eval()
    loaded = time.monotonic()
    with torch.inference_mode():
        raw = model.diarize(audio=str(args.audio), batch_size=1)
    inferred = time.monotonic()
    # Preserve evidence even when the strict parser rejects a padded end time.
    write_private_json(
        raw_path,
        dict(source_sha256=audio_sha, checkpoint_sha256=checkpoint_sha, raw=raw),
    )
    turns = parse_segments(raw, duration)
    if audio_sha != sha256(args.audio):
        raise ValueError("Audio changed during inference")
    result = dict(
        schema=1,
        source_sha256=audio_sha,
        checkpoint_sha256=checkpoint_sha,
        model_revision=args.model_revision,
        versions=versions,
        device="cpu",
        threads=args.threads,
        seed=0,
        postprocessing="nemo_diarize_defaults",
        load_seconds=loaded - started,
        inference_seconds=inferred - loaded,
        elapsed_seconds=inferred - started,
        duration_seconds=duration,
        turns=turns,
        deploy_allowed=False,
    )
    write_private_json(args.output, result)
    print(json.dumps({"turn_count": len(turns), "deploy_allowed": False}))


if __name__ == "__main__":
    main()
