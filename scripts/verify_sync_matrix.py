#!/usr/bin/env python3
"""Controlled videos built from human speech; do not confuse with field footage.

Use fetch_korean_speech.py --count 9 --offset 30 first. No paid services.
The baseline truth comes from the clean clips, never from noisy derived audio.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import subprocess
import wave
from pathlib import Path

import numpy as np

from pipeline.editing import Cue
from worker.analysis import SyncOptions, sync_subtitles

RATE = 16000
VARIANTS = [
    ("short", 3, 1.0, 1.0, None, False, 0.0),
    ("long_repeated", 27, 1.0, 1.0, None, False, 0.0),
    ("dense", 9, 0.15, 1.0, None, False, 0.0),
    ("long_pauses", 9, 5.0, 1.0, None, False, 0.0),
    ("fast", 9, 1.0, 1.25, None, False, 0.0),
    ("slow", 9, 1.0, 0.8, None, False, 0.0),
    ("quiet_voice", 9, 1.0, 1.0, None, False, 0.0),
    ("noise_15db", 9, 1.0, 1.0, 15, False, 0.0),
    ("noise_5db", 9, 1.0, 1.0, 5, False, 0.0),
    ("music_intro", 9, 1.0, 1.0, 15, True, 8.0),
]


def read_audio(path: Path) -> np.ndarray:
    with wave.open(str(path)) as stream:
        assert stream.getframerate() == RATE and stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        return (
            np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(float) / 32768
        )


def write_audio(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        stream.writeframes((np.clip(audio, -0.999, 0.999) * 32767).astype("<i2").tobytes())


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=600)


def make_variant(directory: Path, out: Path, spec: tuple) -> tuple[Path, list[Cue], float]:
    name, count, gap, speed, snr, music, intro = spec
    expected = json.loads((directory / "expected.json").read_text())["sentences"]
    clips = [read_audio(directory / f"human{i}.wav") for i in range(len(expected))]
    local_ends = []
    cursor = 1.0
    for item, clip in zip(expected, clips, strict=True):
        local_ends.append(item["end"] - cursor)
        cursor += len(clip) / RATE + 1.0
    chunks = [np.zeros(round((1 + intro) * RATE))]
    cursor = 1 + intro
    truth = []
    for n in range(count):
        i = n % len(clips)
        truth.append(
            Cue(
                start=(cursor + expected[i]["lead_silence"]) / speed,
                end=(cursor + local_ends[i]) / speed,
                text=expected[i]["text"],
            )
        )
        chunks.extend([clips[i], np.zeros(round(gap * RATE))])
        cursor += len(clips[i]) / RATE + gap
    audio = np.concatenate(chunks)
    if snr is not None:
        rng = np.random.default_rng(20260919)
        rms = float(np.sqrt(np.mean(audio**2)))
        noise = rng.standard_normal(len(audio))
        noise = noise / np.sqrt(np.mean(noise**2)) * rms / (10 ** (snr / 20))
        audio = audio + noise
    if music:
        t = np.arange(len(audio)) / RATE
        audio += 0.04 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 330 * t)) / 2
    if name == "quiet_voice":
        audio *= 0.126  # -18 dB gain; timing stays unchanged.
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / "raw.wav"
    write_audio(raw, audio)
    sound = folder / "sound.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", f"atempo={speed}", str(sound)])
    video = folder / "video.mp4"
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=320x180:r=10",
            "-i",
            str(sound),
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video),
        ]
    )
    return video, truth, cursor / speed


def evaluate(
    source: Path,
    truth: list[Cue],
    offset: float,
    limit: float,
    options: SyncOptions | None = None,
) -> dict:
    pushed = [Cue(start=c.start + offset, end=c.end + offset, text=c.text) for c in truth]
    try:
        moved, meta = (
            sync_subtitles(source, pushed, options) if options else sync_subtitles(source, pushed)
        )
        errors = [
            max(abs(a.start - b.start), abs(a.end - b.end))
            for a, b in zip(moved, truth, strict=True)
        ]
        same = [c.text for c in moved] == [c.text for c in truth]
        return {
            "pass": same
            and max(errors) <= limit + 1e-9
            and abs(meta["offset_seconds"] + offset) <= limit + 1e-9,
            "max_error_seconds": round(max(errors), 3),
            "text_preserved": same,
            "offset_seconds": meta["offset_seconds"],
            "boundary_support": meta.get("boundary_support", 0),
            "recovery_used": meta.get("recovery_used", False),
        }
    except (ValueError, RuntimeError) as exc:
        return {"pass": False, "rejected": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=float, default=0.5)
    parser.add_argument("--profile", choices=["standard", "quiet", "long_cues"], default="standard")
    parser.add_argument("--offsets", type=float, nargs="+", default=[0.0, 2.5])
    args = parser.parse_args()
    if any(not math.isfinite(value) for value in args.offsets):
        parser.error("offsets는 유한한 초 단위 값이어야 합니다.")
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in VARIANTS:
        source, truth, duration = make_variant(args.directory, args.out, spec)
        entry = {
            "variant": spec[0],
            "duration_seconds": round(duration, 3),
            "cue_count": len(truth),
            "cases": {},
        }
        for offset in args.offsets:
            if min(c.start for c in truth) + offset < 0:
                parser.error("offsets가 기준 자막을 영상 시작 앞으로 옮깁니다.")
            with (
                (args.out / spec[0] / f"{offset}.log").open("w") as log,
                contextlib.redirect_stdout(log),
                contextlib.redirect_stderr(log),
            ):
                logging.disable(logging.CRITICAL)
                entry["cases"][str(offset)] = evaluate(
                    source, truth, offset, args.limit, SyncOptions(profile=args.profile)
                )
                logging.disable(logging.NOTSET)
        results.append(entry)
        (args.out / "results.json").write_text(
            json.dumps(
                {
                    "limit": args.limit,
                    "profile": args.profile,
                    "offsets": args.offsets,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    return 0 if all(c["pass"] for r in results for c in r["cases"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
