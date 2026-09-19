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
    source: Path,
    truth: list[Cue],
    offset: float,
    limit: float,
    method: str = "shift",
    drift: float = 0.0,
) -> dict:
    """한 조건에서 한 방법을 잽니다. 거부와 실패를 통과로 세지 않습니다.

    두 방법은 재는 것이 다릅니다. shift는 이동값이 하나라 그 값 자체도 봅니다.
    align은 자막마다 시각을 따로 받으므로 이동값 하나로 판정할 수 없고, 자막
    시각의 오차만 봅니다.
    """
    # drift는 자막마다 어긋남을 점점 키웁니다. 이동값 하나로는 고칠 수 없는
    # 모양이라 강제 정렬을 제안한 이유가 바로 이것입니다. 0이면 지금까지처럼
    # 전체가 한 덩어리로 어긋난 경우입니다.
    pushed = [
        Cue(start=c.start + offset + index * drift, end=c.end + offset + index * drift, text=c.text)
        for index, c in enumerate(truth)
    ]
    try:
        if method.startswith("align"):
            # align_nosnap은 자막 시작을 VAD 발화 시작에 맞추는 단계를 끕니다.
            # 그 맞춤이 시작 시각의 정의를 VAD 쪽으로 옮기는지 보려는 것입니다.
            moved, meta = realign_subtitles(
                source, pushed, language="ko", snap=method != "align_nosnap"
            )
        else:
            moved, meta = sync_subtitles(source, pushed)
        starts = [abs(a.start - b.start) for a, b in zip(moved, truth, strict=True)]
        ends = [abs(a.end - b.end) for a, b in zip(moved, truth, strict=True)]
        errors = [max(pair) for pair in zip(starts, ends, strict=True)]
        same = [c.text for c in moved] == [c.text for c in truth]
        passed = same and max(errors) <= limit + 1e-9
        found = {
            "pass": passed,
            "max_error_seconds": round(max(errors), 3),
            # 시작과 끝을 나눠 남깁니다. 합쳐 놓으면 어디가 어긋났는지 안 보입니다.
            # 끝 시각의 정답은 에너지 문턱으로 잰 값이라 말끝 숨소리·잔향만큼
            # 늦습니다(측정: 1.21~1.74초). 자막 길이를 그대로 옮기는 방법은 그
            # 정답과 저절로 맞고, 음성에서 끝을 다시 찾는 방법은 벌을 받습니다.
            # 두 방법을 끝 시각으로 견주면 안 되는 이유입니다.
            "max_start_error_seconds": round(max(starts), 3),
            "max_end_error_seconds": round(max(ends), 3),
            "text_preserved": same,
        }
        if method.startswith("align"):
            found["max_shift_seconds"] = meta["max_shift_seconds"]
        else:
            found["offset_seconds"] = meta["offset_seconds"]
            # 어긋남이 자막마다 다르면 "맞는 이동값" 자체가 없습니다. 그때는
            # 이동값으로 판정하지 않고 자막 시각의 오차만 봅니다.
            if not drift:
                found["pass"] = passed and abs(meta["offset_seconds"] + offset) <= limit + 1e-9
        return found
    except (ValueError, RuntimeError) as exc:
        return {"pass": False, "rejected": str(exc)}


METHODS = ("shift", "align", "align_nosnap")


def pick(value: str, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    """쉼표로 준 방법 목록. `both`는 예전 이름이라 그대로 받습니다.

    `none`은 **하나도 고르지 않음**입니다. 판정에 쓸 때, 아직 보증하지 않는
    조건에서 재기만 하려는 경우에 씁니다.
    """
    if value == "none":
        return ()
    if value == "both":
        return ("shift", "align")
    chosen = tuple(name.strip() for name in value.split(",") if name.strip())
    if unknown := set(chosen) - set(METHODS):
        parser.error(f"모르는 방법입니다: {', '.join(sorted(unknown))}. 쓸 수 있는 값: {METHODS}")
    return chosen or ("shift",)


def summarize(results: list[dict], methods: tuple[str, ...]) -> None:
    """조건마다 방법별 최대 오차를 한 표로 찍습니다. 눈으로 견줄 수 있어야 합니다."""
    print("\n조건별 최대 오차(초) — 시작 / 끝. 작을수록 좋습니다")
    print("끝 시각의 정답은 에너지 문턱이라 말끝 숨소리·잔향만큼 늦습니다.")
    print("길이를 그대로 옮기는 방법은 그 정답과 저절로 맞으므로, 끝으로는 견주지 마세요.")
    head = "  ".join(f"{m:>17}" for m in methods)
    print(f"\n{'조건':22} {'길이(초)':>9}  {head}")
    for entry in results:
        cells = []
        for method in methods:
            worst = [
                case
                for key, case in entry["cases"].items()
                if key.split(":")[0] == method or len(methods) == 1
            ]
            if any("rejected" in case for case in worst):
                cells.append(f"{'거부':>17}")
            else:
                begin = max(c["max_start_error_seconds"] for c in worst)
                finish = max(c["max_end_error_seconds"] for c in worst)
                cells.append(f"{begin:7.3f} /{finish:8.3f}")
        print(f"{entry['variant']:22} {entry['duration_seconds']:9.1f}  " + "  ".join(cells))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=float, default=0.5)
    # 같은 조건에서 두 방법을 나란히 잽니다. 손으로 따로 돌려 비교하지 않게 합니다.
    parser.add_argument("--method", default="shift", help=f"쉼표 구분: {', '.join(METHODS)}")
    # 판정에 넣을 방법. 재기만 하고 아직 보증하지 않는 방법이 있습니다. 재는 것과
    # 보증하는 것을 섞으면, 채택하지도 않은 방법 때문에 CI가 빨개집니다.
    parser.add_argument(
        "--gate", default=None, help="비우면 --method와 같습니다. none이면 판정 안 함"
    )
    # 조건이 10가지라 둘 다 재면 오래 걸립니다. 필요한 조건만 고를 수 있게 합니다.
    parser.add_argument("--variants", default="", help="쉼표로 구분한 조건 이름")
    # 자막마다 어긋남을 점점 키웁니다. 이동값 하나로는 못 고치는 모양입니다.
    parser.add_argument("--drift", type=float, default=0.0, help="자막 하나당 더할 초")
    args = parser.parse_args()
    methods = pick(args.method, parser)
    gated = methods if args.gate is None else pick(args.gate, parser)
    wanted = [name.strip() for name in args.variants.split(",") if name.strip()]
    known = {spec[0] for spec in VARIANTS}
    if unknown := set(wanted) - known:
        parser.error(
            f"모르는 조건입니다: {', '.join(sorted(unknown))}. 쓸 수 있는 값: {sorted(known)}"
        )
    variants = [spec for spec in VARIANTS if not wanted or spec[0] in wanted]
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in variants:
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
                    entry["cases"][key] = evaluate(
                        source, truth, offset, args.limit, method, args.drift
                    )
                    logging.disable(logging.NOTSET)
        results.append(entry)
        (args.out / "results.json").write_text(
            json.dumps(
                {
                    "limit": args.limit,
                    "methods": list(methods),
                    "gated": list(gated),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    summarize(results, methods)
    failed = [
        key
        for entry in results
        for key, case in entry["cases"].items()
        if not case["pass"] and key.split(":")[0] in gated
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
