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
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for dataset in [args.dataset] if args.dataset else CANDIDATES:
        print(f"데이터셋 {dataset}")
        chosen = pick_split(dataset)
        if not chosen:
            continue
        config, split = chosen
        print(f"  config={config} split={split}")
        found = rows(dataset, config, split, args.count * 2, args.offset)
        pieces: list[tuple[Path, str]] = []
        for index, row in enumerate(found):
            pair = audio_and_text(row)
            if not pair:
                continue
            source, text = pair
            suffix = Path(urllib.parse.urlparse(source).path).suffix or ".wav"
            raw = args.out / f"raw{index}{suffix}"
            if not download(source, raw):
                continue
            piece = to_mono16k(raw, args.out / f"human{len(pieces)}.wav")
            pieces.append((piece, text))
            print(f"  받음: {text[:40]}")
            if len(pieces) >= args.count:
                break
        if len(pieces) >= 2:
            build_sample(pieces, args.out)
            return 0
        print("  쓸 만한 조각을 충분히 받지 못했습니다.")

    print("\n사람 목소리 조각을 받지 못했습니다. 네트워크나 데이터셋 주소를 확인하세요.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
