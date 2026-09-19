#!/usr/bin/env python3
"""화자 분리 검증용으로 목소리가 둘인 음성을 만듭니다.

정답을 우리가 정해야 검증이 됩니다. 그래서 서로 확실히 다른 두 목소리를
번갈아 넣고 각 조각의 화자를 기록합니다. 사람 목소리 조각이 있으면 한쪽
화자로 쓰고, 없으면 espeak 두 목소리를 씁니다.

    python3 scripts/make_two_speaker_sample.py --out /tmp/two --human /tmp/human
"""

from __future__ import annotations

import argparse
from pathlib import Path

from make_speech_sample import synthesize
from speech_sample import build_sample

LINES_A = ["첫 번째 화자가 말하는 문장입니다", "같은 화자가 한 번 더 말합니다"]
LINES_B = ["다른 화자가 이어서 말합니다", "두 번째 화자의 마지막 문장입니다"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--human", type=Path, default=None, help="사람 목소리 조각이 있는 폴더")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    human = sorted((args.human or Path("/nonexistent")).glob("human*.wav"))
    if len(human) >= 2:
        # 사람 목소리 조각에는 LINES_A의 글을 붙입니다. 실제로 하는 말과
        # 다릅니다. 화자 분리는 누가 언제 말했는지만 보므로 상관없지만, 이
        # 음성을 전사 검증에 쓰면 안 됩니다.
        first = [(path, text) for path, text in zip(human[:2], LINES_A, strict=False)]
        print(f"화자 A: 사람 목소리 {len(first)}조각")
    else:
        first = [
            (synthesize(text, args.out / f"a{index}.wav", voice="ko+m3", speed=150), text)
            for index, text in enumerate(LINES_A)
        ]
        print("화자 A: espeak ko+m3")
    second = [
        (synthesize(text, args.out / f"b{index}.wav", voice="ko+f2", speed=165), text)
        for index, text in enumerate(LINES_B)
    ]
    print("화자 B: espeak ko+f2")

    # 번갈아 넣어야 한 화자가 통째로 몰리지 않습니다.
    pieces = [first[0], second[0], first[1], second[1]]
    build_sample(pieces, args.out, labels=["A", "B", "A", "B"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
