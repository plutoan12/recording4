#!/usr/bin/env python3
"""공개 한국어 음성 데이터에서 사람 목소리 조각을 받아 검증용 음성을 만듭니다.

지금까지 정렬 검증은 espeak 합성 음성으로만 했습니다. 합성 음성은 사람
목소리와 조건이 달라서, 거기서 나온 정확도를 그대로 믿을 수 없습니다.
이 스크립트는 Hugging Face datasets-server에서 공개 한국어 낭독 음성을 몇
조각 받아 같은 형식의 sample.wav와 expected.json을 만듭니다.

    python3 scripts/fetch_korean_speech.py --out /tmp/human --count 3

네트워크를 타므로 CI에서 필요할 때만 돌립니다. 받지 못하면 조용히 넘어가지
않고 종료 코드 2로 실패합니다. 검증을 건너뛴 것과 통과한 것은 구분해야
합니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from speech_sample import build_sample, to_mono16k

SERVER = "https://datasets-server.huggingface.co"
# 공개 CC 라이선스 한국어 낭독 음성. 앞에서부터 차례로 시도합니다.
CANDIDATES = ["Bingsu/zeroth-korean", "kresnik/zeroth_korean"]
TEXT_COLUMNS = ("text", "sentence", "transcription", "transcript")


def fetch_json(url: str, timeout: int = 60) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - 고정 호스트
        return json.loads(response.read().decode("utf-8"))


def pick_split(dataset: str) -> tuple[str, str] | None:
    """이 데이터셋에서 쓸 config와 split을 고릅니다. test를 먼저 봅니다."""
    url = f"{SERVER}/splits?dataset={urllib.parse.quote(dataset)}"
    try:
        found = fetch_json(url).get("splits", [])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"  splits 조회 실패: {type(exc).__name__}")
        return None
    if not found:
        return None
    for name in ("test", "validation", "dev", "train"):
        for item in found:
            if item.get("split") == name:
                return item["config"], item["split"]
    first = found[0]
    return first["config"], first["split"]


def rows(dataset: str, config: str, split: str, count: int, offset: int = 0) -> list[dict]:
    url = (
        f"{SERVER}/rows?dataset={urllib.parse.quote(dataset)}"
        f"&config={urllib.parse.quote(config)}&split={urllib.parse.quote(split)}"
        f"&offset={offset}&length={count}"
    )
    try:
        return fetch_json(url).get("rows", [])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"  rows 조회 실패: {type(exc).__name__}")
        return []


def sample_id(texts: list[str]) -> str:
    """이 표본이 무엇인지 한 줄로 가리키는 값. 문장 목록에서만 만듭니다.

    행 번호(--offset)는 표본을 고정하지 못합니다. 같은 --offset 30으로 30분
    간격을 두고 받았더니 **문장 아홉 개가 전부 다르게** 왔습니다(측정:
    2026-09-19 CI run #306 대 #328). 그래서 잰 값에는 행 번호가 아니라 이
    값을 함께 남깁니다. 그러지 않으면 서로 다른 음성에서 나온 숫자를 같은
    표에 놓고 견주게 됩니다.
    """
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:12]


def find_window(
    dataset: str, config: str, split: str, count: int, expect: str, limit: int, block: int = 100
) -> list[tuple[str, str]] | None:
    """기록해 둔 표본을 행 순서가 바뀌어도 찾아냅니다.

    앞에서부터 훑으며 연속한 count개의 문장 묶음이 expect와 같은지 봅니다.
    찾지 못하면 None입니다. 조용히 다른 표본으로 넘어가지 않습니다.
    """
    collected: list[tuple[str, str]] = []
    offset = 0
    while offset < limit:
        got = rows(dataset, config, split, block, offset)
        if not got:
            break
        for row in got:
            if pair := audio_and_text(row):
                collected.append(pair)
        for start in range(max(0, len(collected) - count + 1)):
            window = collected[start : start + count]
            if len(window) == count and sample_id([text for _, text in window]) == expect:
                print(f"  기록해 둔 표본을 {start}번째 쓸 수 있는 행에서 찾았습니다.")
                return window
        offset += block
    return None


def audio_and_text(row: dict) -> tuple[str, str] | None:
    """행에서 오디오 주소와 원문을 꺼냅니다. 형식이 다르면 None입니다."""
    values = row.get("row", {})
    source = None
    for value in values.values():
        if isinstance(value, list) and value and isinstance(value[0], dict) and "src" in value[0]:
            source = value[0]["src"]
            break
    text = next(
        (values[c] for c in TEXT_COLUMNS if isinstance(values.get(c), str) and values[c].strip()),
        None,
    )
    return (source, text.strip()) if source and text else None


def download(url: str, target: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - 조회 결과 주소
            target.write_bytes(response.read())
    except (urllib.error.URLError, OSError) as exc:
        print(f"  내려받기 실패: {type(exc).__name__}")
        return False
    return target.stat().st_size > 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0, help="서로 다른 표본을 가져올 시작 행")
    parser.add_argument("--dataset", default=None, help="지정하면 이 데이터셋만 씁니다.")
    # 행 번호는 표본을 고정하지 못합니다(sample_id 설명 참고). 기록해 둔 표본을
    # 다시 쓰려면 그 표본 id를 줍니다. 찾지 못하면 실패합니다. 다른 표본으로
    # 조용히 갈아타면 같은 이름의 조건에서 다른 숫자가 나옵니다.
    parser.add_argument(
        "--expect", default=None, help="기록해 둔 표본 id. 행 순서가 바뀌어도 찾습니다"
    )
    parser.add_argument("--search", type=int, default=500, help="--expect를 찾을 때 훑을 행 수")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for dataset in [args.dataset] if args.dataset else CANDIDATES:
        print(f"데이터셋 {dataset}")
        chosen = pick_split(dataset)
        if not chosen:
            continue
        config, split = chosen
        print(f"  config={config} split={split}")
        if args.expect:
            chosen = find_window(dataset, config, split, args.count, args.expect, args.search)
            if chosen is None:
                print(f"  표본 {args.expect}를 앞 {args.search}행에서 찾지 못했습니다.")
                continue
        else:
            found = rows(dataset, config, split, args.count * 2, args.offset)
            chosen = [pair for row in found if (pair := audio_and_text(row))]
        pieces: list[tuple[Path, str]] = []
        for index, (source, text) in enumerate(chosen):
            suffix = Path(urllib.parse.urlparse(source).path).suffix or ".wav"
            raw = args.out / f"raw{index}{suffix}"
            if not download(source, raw):
                # 기록해 둔 표본을 고른 뒤라면 한 조각만 빠져도 다른 표본이
                # 됩니다. 건너뛰고 채우면 id가 거짓말을 합니다.
                if args.expect:
                    print("  기록해 둔 표본의 조각을 받지 못했습니다.")
                    pieces = []
                    break
                continue
            piece = to_mono16k(raw, args.out / f"human{len(pieces)}.wav")
            pieces.append((piece, text))
            print(f"  받음: {text[:40]}")
            if len(pieces) >= args.count:
                break
        if len(pieces) >= 2:
            build_sample(pieces, args.out)
            # 표본 id는 실제로 쓴 문장에서 만듭니다. 고르려던 것이 아니라
            # 쓴 것을 가리켜야 합니다.
            identifier = sample_id([text for _, text in pieces])
            path = args.out / "expected.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sample_id"] = identifier
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"표본 id {identifier} (문장 {len(pieces)}개)")
            return 0
        print("  쓸 만한 조각을 충분히 받지 못했습니다.")

    print("\n사람 목소리 조각을 받지 못했습니다. 네트워크나 데이터셋 주소를 확인하세요.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
