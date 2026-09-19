"""정렬 검증용 음성 묶음을 만드는 공통 도구.

문장 조각을 무음으로 이어 붙이고, 각 문장이 실제로 언제 시작·끝나는지
FFmpeg로 재서 기록합니다. 문턱은 조각마다 그 파일의 최대 음량에서 내려
잡습니다. 합성 음성이든 사람 목소리든 같은
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
_MAX_VOLUME = re.compile(r"max_volume:\s*(-?[\d.]+) dB")

# 발화로 볼 음량을 파일의 최대 음량에서 이만큼 아래로 잡습니다. 고정 문턱은
# 녹음마다 다른 잡음 바닥에 걸립니다(측정: 사람 목소리 조각에서 -40dB 고정
# 문턱이 앞 무음을 0.08초로 봤지만, 실제 말은 1.6초 뒤에 시작).
HEADROOM = 35.0

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


def max_volume(path: Path) -> float | None:
    """파일의 최대 음량(dB). 못 재면 None입니다."""
    done = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    found = _MAX_VOLUME.findall(done.stderr)
    return float(found[-1]) if found else None


def noise_floor(path: Path) -> str:
    """이 파일에서 발화로 볼 음량 문턱. 파일마다 다시 잽니다.

    사람 녹음은 말이 없어도 실내 잡음이 남습니다. 그 잡음이 고정 문턱보다
    크면 잡음이 시작된 지점을 말이 시작된 지점으로 잘못 적습니다. 그래서
    파일의 최대 음량을 재고 거기서 내려 잡습니다.
    """
    peak = max_volume(path)
    return "-40dB" if peak is None else f"{peak - HEADROOM:.1f}dB"


def speech_span(path: Path, noise: str | None = None) -> tuple[float, float]:
    """파일 안에서 실제로 소리가 나는 구간 (시작, 끝). 못 찾으면 파일 전체."""
    if noise is None:
        noise = noise_floor(path)
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


def concat_listing(pieces: list[Path]) -> str:
    """ffmpeg concat 목록. 경로는 절대 경로로 적습니다.

    이름만 적으면 목록 파일이 있는 폴더 기준으로 풀립니다. 다른 폴더의
    조각(사람 목소리)은 그렇게 하면 찾지 못하는데, ffmpeg는 그 조각을
    빼고도 성공으로 끝냅니다. 그러면 정답은 29초인데 음성은 1초인 묶음이
    조용히 만들어집니다.
    """
    return "".join(f"file '{path.resolve()}'\n" for path in pieces)


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
        threshold = noise_floor(piece)
        begin, finish = speech_span(piece, threshold)
        # 고정 문턱으로도 재서 같이 남깁니다. 정답 시각이 문턱 때문에 얼마나
        # 움직였는지 보이지 않으면, 검증이 통과해도 무엇을 통과한 것인지
        # 알 수 없습니다.
        fixed_begin, _ = speech_span(piece, "-40dB")
        entry = {
            "text": text,
            "start": round(cursor + begin, 3),
            "end": round(cursor + finish, 3),
            "lead_silence": round(begin, 3),
            "threshold": threshold,
            "lead_silence_at_40db": round(fixed_begin, 3),
        }
        if labels:
            entry["speaker"] = labels[index]
        expected.append(entry)
        cursor += duration(piece) + GAP
        ordered.append(piece)
        ordered.append(silence)

    listing = out / "concat.txt"
    listing.write_text(concat_listing(ordered), encoding="utf-8")
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
    # 묶기가 조각을 빠뜨려도 ffmpeg는 성공으로 끝날 수 있습니다(측정: 사람
    # 목소리 조각이 다른 폴더에 있어 29초짜리가 1초로 묶였고, 검증은 "발화
    # 구간이 없다"는 엉뚱한 실패로 나타났습니다). 길이를 직접 확인합니다.
    made = duration(sample)
    if abs(made - cursor) > 0.2:
        raise RuntimeError(
            f"묶은 음성이 {made:.2f}초입니다. 조각 길이 합은 {cursor:.2f}초입니다. "
            "조각 경로를 확인하세요. 빠진 조각이 있으면 정답과 음성이 어긋납니다."
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
            f" (앞 무음 {item['lead_silence']:.2f}초, 문턱 {item['threshold']},"
            f" -40dB로 재면 {item['lead_silence_at_40db']:.2f}초){speaker}  {item['text']}"
        )
    return payload
