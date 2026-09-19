#!/usr/bin/env python3
"""배경음 분리가 실제로 무엇을 남기고 무엇을 지우는지 잽니다.

더빙은 원본 오디오를 통째로 바꿉니다. 배경음 분리를 켜면 목소리만 빼고 남은
소리를 대사 아래에 깝니다. 문제는 **분리가 근사**라는 것입니다. 배경음이
얼마나 남는지, 목소리가 얼마나 지워지는지는 돌려 봐야 압니다.

재는 방법은 **아는 두 소리를 섞어 보는 것**입니다. 목소리(espeak-ng 합성)와
순음(사인파)을 따로 만들어 섞고, 분리한 결과에서 각각이 얼마나 남았는지
주파수로 셉니다. 순음은 한 주파수에만 있으므로 그 칸의 힘을 보면 되고,
목소리는 그 칸 밖에 퍼져 있습니다.

표본 만들기와 재기를 나눕니다. 합성 음성(espeak-ng)은 워커 이미지에 없어서
표본은 **바깥에서** 만들고, 분리는 워커 이미지 **안에서** 돌립니다. 정렬 검증이
make_speech_sample.py와 verify_align.py로 나뉜 것과 같은 이유입니다.

    python3 scripts/verify_separation.py --make --out /tmp/separation   # ffmpeg, espeak-ng
    docker run --rm -v /tmp/separation:/audio ... verify_separation.py --directory /audio

표본 폴더는 **읽기만** 합니다. 분리 결과는 임시 폴더에 씁니다.

**수치 두 개로 음질을 말할 수 없습니다.** 이 검사는 "분리가 돌고 있고 결과가
예전과 크게 달라지지 않았다"를 보는 것입니다. 실제로 들어 보는 것을 대신하지
않습니다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

# numpy는 **재는 쪽**에서만 씁니다. 표본 만들기(--make)는 러너에서 도는데
# 거기에는 numpy가 없습니다. 맨 위에서 들이면 표본도 못 만듭니다(CI 실측:
# ModuleNotFoundError: No module named 'numpy').

TONE_HZ = 440.0
RATE = 44100
SECONDS = 6.0
# 순음이 들어 있다고 볼 주파수 폭(Hz). 창 함수와 반올림으로 옆 칸까지 번집니다.
BAND_HZ = 20.0


def run(command: list[str]) -> None:
    done = subprocess.run(command, capture_output=True, timeout=600)
    if done.returncode:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-4:]
        raise RuntimeError(f"{command[0]} 실패:\n" + "\n".join(tail))


def tone(path: Path) -> Path:
    """배경음 자리에 놓을 순음. 한 주파수에만 있어 남았는지 세기 쉽습니다."""
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency={TONE_HZ}:duration={SECONDS}:sample_rate={RATE}",
            "-c:a", "pcm_s16le", str(path),
        ]
    )  # fmt: skip
    return path


def speech(path: Path, text: str = "안녕하세요 배경음 분리를 검증합니다") -> Path:
    """목소리 자리에 놓을 합성 음성. 정렬 검증과 같은 espeak-ng를 씁니다."""
    raw = path.with_name(f"raw-{path.name}")
    run(["espeak-ng", "-v", "ko", "-s", "150", "-w", str(raw), text])
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(raw),
            "-ar", str(RATE), "-ac", "1", "-t", str(SECONDS), "-c:a", "pcm_s16le", str(path),
        ]
    )  # fmt: skip
    return path


def mix(voice: Path, music: Path, path: Path) -> Path:
    """둘을 같은 크기로 섞습니다. 실제 영상의 음악 위 대사와 같은 모양입니다."""
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-i", str(voice), "-i", str(music),
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=shortest:normalize=0[a]",
            "-map", "[a]", "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(path),
        ]
    )  # fmt: skip
    return path


def samples(path: Path):  # noqa: ANN201 - numpy를 여기서만 들입니다.
    """WAV를 -1~1 사이 한 갈래 소리로 읽습니다."""
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
        channels, width = handle.getnchannels(), handle.getsampwidth()
    if width != 2:
        raise RuntimeError(f"16비트 WAV만 읽습니다: {path} ({width * 8}비트)")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    return data.reshape(-1, channels).mean(axis=1) if channels > 1 else data


def powers(data, rate: int) -> tuple[float, float]:  # noqa: ANN001
    """(순음 칸의 힘, 그 밖의 힘). 둘을 나눠 보면 무엇이 남았는지 보입니다."""
    import numpy as np

    if not data.size:
        return 0.0, 0.0
    spectrum = np.abs(np.fft.rfft(data * np.hanning(data.size))) ** 2
    freqs = np.fft.rfftfreq(data.size, 1 / rate)
    band = np.abs(freqs - TONE_HZ) <= BAND_HZ
    return float(spectrum[band].sum()), float(spectrum[~band].sum())


def ratio(after: float, before: float) -> float:
    """남은 비율. 원래 없던 것은 0으로 봅니다."""
    return after / before if before > 0 else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/tmp/separation"))
    parser.add_argument("--directory", type=Path, default=None, help="이미 만든 표본 폴더")
    parser.add_argument("--make", action="store_true", help="표본만 만들고 끝냅니다.")
    parser.add_argument("--device", default="cpu")
    # 품질 목표가 아니라 회귀 감시용 한계입니다. 표본이 하나라 값은 흔들립니다.
    parser.add_argument(
        "--min-kept", type=float, default=0.50, help="배경음이 남아야 하는 최소 비율"
    )
    parser.add_argument(
        "--max-voice", type=float, default=0.60, help="목소리가 남아도 되는 최대 비율"
    )
    args = parser.parse_args()

    directory = args.directory or args.out
    if args.make or args.directory is None:
        directory.mkdir(parents=True, exist_ok=True)
        voice, music = speech(directory / "voice.wav"), tone(directory / "music.wav")
        mix(voice, music, directory / "mixed.wav")
        print(f"표본을 만들었습니다: {directory}/mixed.wav")
        if args.make:
            return 0

    mixed = directory / "mixed.wav"
    if not mixed.exists():
        print(f"섞은 소리가 없습니다: {mixed}. --make로 먼저 만드세요.")
        return 2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/worker"))
    from worker.separation import MissingDependency, separate_background

    # 결과는 표본 폴더가 **아니라** 임시 폴더에 씁니다. 컨테이너 안에서 돌 때
    # 표본 폴더는 바깥에서 붙여 준 자리라 쓸 수가 없습니다. 이미지는 uid 10001로
    # 도는데 그 폴더는 러너가 만들었습니다(CI 실측: soundfile.LibsndfileError:
    # Error opening '/audio/background.wav': System error.). 읽기만 하면 되는
    # 자리에 쓰려 한 것이 잘못이었습니다.
    with tempfile.TemporaryDirectory(prefix="separation-") as work:
        try:
            result = separate_background(mixed, Path(work) / "background.wav", device=args.device)
        except MissingDependency as exc:
            print(f"분리를 돌릴 수 없습니다: {exc}")
            return 2
        before_tone, before_rest = powers(samples(mixed), RATE)
        after_tone, after_rest = powers(samples(result.background), result.sample_rate)
        seconds, rate = result.seconds, result.sample_rate
    kept, left = ratio(after_tone, before_tone), ratio(after_rest, before_rest)

    print(f"섞은 소리 {seconds:.1f}초, {rate}Hz")
    print(f"  배경음({TONE_HZ:.0f}Hz 순음) 남은 비율: {kept:.2f} (한계 {args.min_kept:.2f} 이상)")
    print(f"  그 밖의 소리(목소리) 남은 비율: {left:.2f} (한계 {args.max_voice:.2f} 이하)")

    problems = []
    if kept < args.min_kept:
        problems.append(
            f"배경음이 {kept:.2f}만 남았습니다. 이대로면 음악을 살리려고 켠 설정이 "
            "음악을 지웁니다."
        )
    if left > args.max_voice:
        problems.append(f"목소리가 {left:.2f} 남았습니다. 더빙 대사와 원본 목소리가 겹쳐 들립니다.")
    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n이 수치는 '분리가 돌고 예전과 크게 달라지지 않았다'까지입니다.")
    print("음질은 사람이 들어야 압니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
