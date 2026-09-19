#!/usr/bin/env python3
"""얼굴 검출기가 **없는 얼굴을 보지 않는지** 잽니다.

세로로 자를 때 어디를 남길지 제안하려고 얼굴을 찾습니다. 검출기가 무늬를
얼굴로 착각하면 제안이 엉뚱한 곳을 가리키고, 사람이 맞춰 둔 값을 망칩니다.

**이 검사가 재는 것은 오검출뿐입니다.** 얼굴이 없는 영상을 넣고 "못 찾았다"가
나오는지 봅니다. 진짜 얼굴을 얼마나 잘 찾는지는 **재지 않습니다.** 얼굴이 든
영상 표본이 저장소에 없고, 사람 얼굴 데이터를 여기에 받아 두는 것은 별개의
결정이기 때문입니다. 그 숫자가 필요하면 실제 영상으로 재야 합니다.

    python3 scripts/verify_faces.py --out /tmp/faces

워커 이미지 안에서 돌립니다. OpenCV와 FFmpeg가 필요합니다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 얼굴이 없는 영상들. 무늬와 잡음은 오검출이 잘 나는 조건입니다.
PATTERNS = {
    "움직이는 도형과 색": "testsrc2=size=1280x720:rate=15:duration=8",
    # 잔무늬가 많은 그림입니다. Haar 캐스케이드는 이런 데서 헛것을 잘 봅니다.
    "복잡한 무늬": "mandelbrot=size=1280x720:rate=15,trim=duration=8",
}


def run(command: list[str]) -> None:
    done = subprocess.run(command, capture_output=True, timeout=600)
    if done.returncode:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-4:]
        raise RuntimeError(f"{command[0]} 실패:\n" + "\n".join(tail))


def make(source: str, path: Path) -> Path:
    run(
        [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-f", "lavfi", "-i", source,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )  # fmt: skip
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/tmp/faces"))
    parser.add_argument(
        "--max-coverage",
        type=float,
        default=0.10,
        help="얼굴 없는 영상에서 '찾았다'가 나와도 되는 최대 비율",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/worker"))
    from worker.faces import MissingDependency, suggest

    problems: list[str] = []
    print("얼굴이 없는 영상에서 검출기가 무엇을 보는가")
    for index, (label, source) in enumerate(PATTERNS.items()):
        path = make(source, args.out / f"pattern-{index}.mp4")
        try:
            found = suggest(path)
        except MissingDependency as exc:
            print(f"  {label}: 돌릴 수 없습니다 — {exc}")
            return 2
        print(
            f"  {label}: 표본 {found.samples}장 중 {found.found}장에서 '얼굴' "
            f"({found.coverage:.0%}), 제안 focus_x {found.focus_x}"
        )
        print(f"      {found.reason}")
        if found.coverage > args.max_coverage:
            problems.append(
                f"{label}: 얼굴이 없는데 {found.coverage:.0%}에서 찾았다고 합니다. "
                "이대로면 무늬를 보고 화면을 옮깁니다."
            )
        if found.focus_x != 0.5:
            problems.append(f"{label}: 얼굴이 없는데 가운데가 아닌 {found.focus_x}를 제안했습니다.")

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n없는 얼굴을 보지는 않습니다.")
    print("**진짜 얼굴을 얼마나 잘 찾는지는 이 검사로 알 수 없습니다.**")
    print("Haar 캐스케이드는 정면 얼굴만 그럭저럭 찾습니다. 옆얼굴·가린 얼굴은 놓칩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
