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
import subprocess
import wave
from pathlib import Path

import numpy as np

from pipeline.editing import Cue
from worker.analysis import realign_subtitles, sync_subtitles

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
    source: Path, truth: list[Cue], offset: float, limit: float, method: str = "shift"
) -> dict:
    """한 조건에서 한 방법을 잽니다. 거부와 실패를 통과로 세지 않습니다.

    두 방법은 재는 것이 다릅니다. shift는 이동값이 하나라 그 값 자체도 봅니다.
    align은 자막마다 시각을 따로 받으므로 이동값 하나로 판정할 수 없고, 자막
    시각의 오차만 봅니다.
    """
    pushed = [Cue(start=c.start + offset, end=c.end + offset, text=c.text) for c in truth]
    try:
        if method == "align":
            moved, meta = realign_subtitles(source, pushed, language="ko")
        else:
            moved, meta = sync_subtitles(source, pushed)
        errors = [
            max(abs(a.start - b.start), abs(a.end - b.end))
            for a, b in zip(moved, truth, strict=True)
        ]
        same = [c.text for c in moved] == [c.text for c in truth]
        passed = same and max(errors) <= limit + 1e-9
        found = {
            "pass": passed,
            "max_error_seconds": round(max(errors), 3),
            "text_preserved": same,
        }
        if method == "align":
            found["max_shift_seconds"] = meta["max_shift_seconds"]
        else:
            found["offset_seconds"] = meta["offset_seconds"]
            found["pass"] = passed and abs(meta["offset_seconds"] + offset) <= limit + 1e-9
        return found
    except (ValueError, RuntimeError) as exc:
        return {"pass": False, "rejected": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=float, default=0.5)
    # 같은 조건에서 두 방법을 나란히 잽니다. 손으로 따로 돌려 비교하지 않게 합니다.
    parser.add_argument("--method", choices=("shift", "align", "both"), default="shift")
    args = parser.parse_args()
    methods = ("shift", "align") if args.method == "both" else (args.method,)
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
        for method in methods:
            for offset in (0.0, 2.5):
                key = f"{method}:{offset}" if len(methods) > 1 else str(offset)
                with (
                    (args.out / spec[0] / f"{method}-{offset}.log").open("w") as log,
                    contextlib.redirect_stdout(log),
                    contextlib.redirect_stderr(log),
                ):
                    logging.disable(logging.CRITICAL)
                    entry["cases"][key] = evaluate(source, truth, offset, args.limit, method)
                    logging.disable(logging.NOTSET)
        results.append(entry)
        (args.out / "results.json").write_text(
            json.dumps(
                {"limit": args.limit, "methods": list(methods), "results": results},
                ensure_ascii=False,
                indent=2,
            )
        )
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    return 0 if all(c["pass"] for r in results for c in r["cases"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
