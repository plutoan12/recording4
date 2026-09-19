#!/usr/bin/env python3
"""자막 싱크 보정을 실제 음성에 돌려 보고 어긋남을 되돌리는지 잽니다.

make_speech_sample.py가 만든 음성은 문장 시작 시각을 우리가 알고 있습니다.
그 시각으로 자막을 만든 뒤 **아는 만큼 밀어** 놓고 보정을 돌립니다. 보정이
제 일을 했다면 원래 시각 가까이 돌아와야 합니다.

    python scripts/verify_sync.py --directory /audio --offset 2.5

통과만 보면 아무것도 모르므로 실제 오차를 항상 출력합니다.

판정 기준:

- 보정기가 찾은 오프셋이 우리가 민 값과 부호까지 맞을 것(한계 안).
- 보정 뒤 자막 시작 시각이 원래 시각과 한계 안일 것.
- 글자가 하나도 바뀌지 않을 것. 보정은 시각만 옮깁니다.
- 밀지 않은 자막(이미 맞는 자막)을 넣으면 크게 흔들지 않을 것. 맞는 자막을
  흔드는 것이 이 기능에서 가장 나쁜 실패입니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path[:0] = ["/app/packages/pipeline", "/app/services/api", "/app/services/worker"]

from pipeline.editing import Cue  # noqa: E402
from worker.analysis import sync_subtitles  # noqa: E402


def load(directory: Path) -> tuple[Path, list[Cue]]:
    """합성 음성과, 그 음성이 아는 문장 시각으로 만든 자막."""
    expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
    cues = [
        Cue(start=item["start"], end=item["end"], text=item["text"])
        for item in expected["sentences"]
    ]
    return directory / "sample.wav", cues


def report(title: str, truth: list[Cue], moved: list[Cue], found: dict, limit: float) -> list[str]:
    print(f"\n{title}")
    print(f"  보정기가 찾은 오프셋: {found['offset_seconds']:+.3f}초")
    problems: list[str] = []
    for index, (want, got) in enumerate(zip(truth, moved, strict=True), start=1):
        error = got.start - want.start
        print(f"  자막 {index}: 정답 {want.start:.3f}초 / 보정 {got.start:.3f}초 ({error:+.3f}초)")
        if abs(error) > limit:
            problems.append(
                f"{title} 자막 {index}의 오차 {error:+.3f}초가 한계 {limit}초를 넘습니다."
            )
        if got.text != want.text:
            problems.append(f"{title} 자막 {index}의 글자가 바뀌었습니다: {got.text!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--offset", type=float, default=2.5, help="일부러 미는 초")
    parser.add_argument("--limit", type=float, default=0.5, help="허용 오차(초)")
    args = parser.parse_args()

    audio, truth = load(args.directory)
    problems: list[str] = []

    pushed = [Cue(start=c.start + args.offset, end=c.end + args.offset, text=c.text) for c in truth]
    moved, found = sync_subtitles(audio, pushed)
    problems += report(f"{args.offset:+.1f}초 밀어 둔 자막", truth, moved, found, args.limit)
    if abs(found["offset_seconds"] + args.offset) > args.limit:
        problems.append(
            f"보정기가 찾은 오프셋 {found['offset_seconds']:+.3f}초가 "
            f"우리가 민 {-args.offset:+.3f}초와 {args.limit}초 넘게 다릅니다."
        )

    # 이미 맞는 자막을 흔들지 않는지 봅니다. 여기서 흔들리면 기능 자체가 위험합니다.
    kept, found_zero = sync_subtitles(audio, list(truth))
    problems += report("이미 맞는 자막", truth, kept, found_zero, args.limit)

    if problems:
        print("\n실패:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\n통과: 민 자막은 돌아왔고 맞는 자막은 그대로입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
