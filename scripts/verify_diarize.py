#!/usr/bin/env python3
"""화자 분리를 실제로 돌려 보고 화자가 갈리는지 확인합니다.

공급자가 둘입니다.

- `pyannote`: 운영 기본값. 게이트 모델이라 `R4_HF_TOKEN`이 있어야 돕니다.
- `embedding`: 공개 목소리 특징 모델. 토큰이 필요 없어 어디서나 돕니다.

기본값 `auto`는 토큰이 있으면 pyannote, 없으면 embedding으로 갑니다.
**embedding이 통과했다고 pyannote가 검증된 것은 아닙니다.** 둘은 다른
모델이고 품질도 다릅니다. 어느 쪽으로 쟀는지 항상 출력합니다.

    R4_HF_TOKEN=... python scripts/verify_diarize.py --directory /audio
    python scripts/verify_diarize.py --directory /audio --provider embedding

make_two_speaker_sample.py가 만든 음성은 조각마다 화자가 정해져 있습니다.
그 정답과 분리 결과를 맞춰 봅니다.

판정 기준:

- 화자를 둘 이상 찾을 것. 하나만 찾으면 분리하지 못한 것입니다.
- 정답 화자마다 분리 결과의 표시가 하나로 몰릴 것(A는 A끼리, B는 B끼리).
- 모든 문장에 화자가 붙을 것. 겹치는 화자 구간이 없으면 비어 있습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.editing import Cue
from pipeline.speakers import assign_speakers, speaker_totals
from worker.analysis import diarize, diarize_by_embedding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--min-speakers", type=int, default=None)
    parser.add_argument("--max-speakers", type=int, default=None)
    parser.add_argument("--provider", choices=["auto", "pyannote", "embedding"], default="auto")
    args = parser.parse_args()

    token = os.environ.get("R4_HF_TOKEN")
    provider = args.provider
    if provider == "auto":
        provider = "pyannote" if token else "embedding"
    if provider == "pyannote" and not token:
        print("R4_HF_TOKEN이 없습니다. pyannote 약관에 동의한 계정의 토큰이 필요합니다.")
        return 2

    expected = json.loads((args.directory / "expected.json").read_text(encoding="utf-8"))
    sentences = expected["sentences"]
    if any("speaker" not in item for item in sentences):
        print("정답 화자 표시가 없습니다. make_two_speaker_sample.py로 만든 음성을 쓰세요.")
        return 2
    audio = args.directory / "sample.wav"

    print(f"공급자 {provider}, 음성 {audio}, 문장 {len(sentences)}개")
    if provider == "embedding":
        # 이 공급자는 화자 수를 스스로 세지 않습니다. 정답에 있는 화자 수를 줍니다.
        speakers = args.max_speakers or len({item["speaker"] for item in sentences})
        turns = diarize_by_embedding(audio, device="cpu", speakers=speakers)
    else:
        turns = diarize(
            audio,
            token=token,
            device="cpu",
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
        )
    print(f"화자 구간 {len(turns)}개")
    for turn in turns:
        print(f"  {turn.start:>6.2f} ~ {turn.end:>6.2f}  {turn.speaker}")
    print(f"화자별 발화 시간: {speaker_totals(turns)}")

    cues = [Cue(start=item["start"], end=item["end"], text=item["text"]) for item in sentences]
    labels = assign_speakers(cues, turns)

    print(f"\n{'문장':>4} {'정답':>6} {'분리 결과':>12}")
    grouped: dict[str, Counter] = defaultdict(Counter)
    for index, (item, label) in enumerate(zip(sentences, labels, strict=True), start=1):
        print(f"{index:>4} {item['speaker']:>6} {str(label):>12}")
        grouped[item["speaker"]][label] += 1

    problems: list[str] = []
    found = {t.speaker for t in turns}
    if len(found) < 2:
        problems.append(f"화자를 {len(found)}명만 찾았습니다. 둘 이상이어야 합니다.")
    if any(label is None for label in labels):
        problems.append("화자가 붙지 않은 문장이 있습니다.")

    # 정답 화자별로 분리 결과가 한 표시로 몰려야 합니다. 표시 이름 자체는
    # 공급자가 정하므로(SPEAKER_00 등) 이름이 아니라 묶임만 봅니다.
    chosen: dict[str, str] = {}
    for truth, counts in grouped.items():
        winner, hits = counts.most_common(1)[0]
        chosen[truth] = winner
        if hits != sum(counts.values()):
            problems.append(f"정답 화자 {truth}의 문장이 여러 표시로 갈렸습니다: {dict(counts)}")
    if len(set(chosen.values())) < len(chosen):
        problems.append(f"서로 다른 화자가 같은 표시로 묶였습니다: {chosen}")

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print(f"\n{provider} 화자 분리가 두 목소리를 갈랐습니다: {chosen}")
    if provider == "embedding":
        print("이 결과는 pyannote를 검증하지 않습니다. 둘은 다른 모델입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
