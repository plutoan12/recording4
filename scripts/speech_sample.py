"""정렬 검증용 음성 묶음을 만드는 공통 도구.

문장 조각을 무음으로 이어 붙이고, 각 문장이 실제로 언제 시작·끝나는지
FFmpeg silencedetect로 재서 기록합니다. 합성 음성이든 사람 목소리든 같은
형식(sample.wav + expected.json)으로 만들어 같은 검증기가 읽습니다.

조각 경계를 발화 시각으로 쓰면 안 됩니다. 녹음이든 합성이든 앞뒤에 무음이
붙어 있어서, 그 값을 안 재면 정렬이 맞아도 틀린 것처럼 보입니다.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")

GAP = 1.0
RATE = 16000


def run(command: list[str]) -> str:
    done = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if done.returncode:
        raise RuntimeError(f"{command[0]} 실패: {done.stderr.strip()[:400]}")
    return done.stdout


def duration(path: Path) -> float:
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ]
    )
    return float(out.strip())


def to_mono16k(source: Path, target: Path) -> Path:
    """정렬에 넣을 오디오는 16kHz 모노로 통일합니다."""
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ar",
            str(RATE),
            "-ac",
            "1",
            str(target),
        ]
    )
    return target


def speech_span(path: Path, noise: str = "-40dB") -> tuple[float, float]:
    """파일 안에서 실제로 소리가 나는 구간 (시작, 끝). 못 찾으면 파일 전체."""
    done = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise}:duration=0.05",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    total = duration(path)
    starts = [float(v) for v in _SILENCE_START.findall(done.stderr)]
    ends = [float(v) for v in _SILENCE_END.findall(done.stderr)]
    begin = ends[0] if starts and starts[0] <= 0.01 and ends else 0.0
    finish = starts[-1] if len(starts) > len(ends) else total
    if finish <= begin:
        return 0.0, total
    return begin, finish


def silence_file(out: Path) -> Path:
    path = out / "silence.wav"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={RATE}:cl=mono",
            "-t",
            str(GAP),
            str(path),
        ]
    )
    return path


def build_sample(
    pieces: list[tuple[Path, str]], out: Path, *, labels: list[str] | None = None
) -> dict:
    """조각을 무음으로 이어 붙이고 문장별 실제 시각을 기록합니다.

    `labels`를 주면 조각마다 화자 표시를 함께 남깁니다. 화자 분리 검증이
    정답으로 씁니다.
    """
    out.mkdir(parents=True, exist_ok=True)
    silence = silence_file(out)
    ordered: list[Path] = [silence]
    expected: list[dict] = []
    cursor = GAP  # 앞에도 무음을 둡니다. 시작부터 말이 나오지 않게 합니다.
    for index, (piece, text) in enumerate(pieces):
        begin, finish = speech_span(piece)
        entry = {
            "text": text,
            "start": round(cursor + begin, 3),
            "end": round(cursor + finish, 3),
            "lead_silence": round(begin, 3),
        }
        if labels:
            entry["speaker"] = labels[index]
        expected.append(entry)
        cursor += duration(piece) + GAP
        ordered.append(piece)
        ordered.append(silence)

    listing = out / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in ordered), encoding="utf-8")
    sample = out / "sample.wav"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-ar",
            str(RATE),
            "-ac",
            "1",
            str(sample),
        ]
    )
    payload = {"gap": GAP, "sentences": expected}
    (out / "expected.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{sample} ({duration(sample):.2f}초), 문장 {len(expected)}개")
    for item in expected:
        speaker = f" [{item['speaker']}]" if "speaker" in item else ""
        print(
            f"  {item['start']:>6.2f}초 ~ {item['end']:>6.2f}초"
            f" (앞 무음 {item['lead_silence']:.2f}초){speaker}  {item['text']}"
        )
    return payload
