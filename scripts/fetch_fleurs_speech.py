#!/usr/bin/env python3
"""FLEURS 사람 낭독 음성을 소량 받아 동일한 싱크 검증 형식으로 만듭니다.

CC-BY-4.0, https://huggingface.co/datasets/google/fleurs
전체 아카이브를 저장하지 않고 앞에서 count개만 읽습니다. 미달은 실패입니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import urllib.request
from pathlib import Path

from speech_sample import build_sample, to_mono16k

REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
CONFIGS = {"en": "en_us", "ja": "ja_jp", "zh": "cmn_hans_cn", "ko": "ko_kr"}
MAX_CLIP_BYTES = 16_000 * 4 * 120


def transcripts(tsv: str) -> dict[str, str]:
    result = {}
    for line in tsv.splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[1].endswith(".wav") and fields[2].strip():
            result[fields[1]] = fields[2].strip()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=CONFIGS, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--skip", type=int, default=0, help="기존 평가와 겹치지 않게 앞 표본 제외")
    args = parser.parse_args()
    if not 2 <= args.count <= 20:
        parser.error("count는 2~20이어야 합니다.")
    if not 0 <= args.skip <= 100:
        parser.error("skip은 0~100이어야 합니다.")
    # 이전 실행의 표본과 섞이지 않게 새 디렉터리에만 생성합니다.
    args.out.mkdir(parents=True, exist_ok=False)
    base = f"https://huggingface.co/datasets/google/fleurs/resolve/{REVISION}/data/{CONFIGS[args.language]}"
    with urllib.request.urlopen(base + "/dev.tsv", timeout=60) as response:
        texts = transcripts(response.read().decode("utf-8"))
    pieces, records = [], []
    skipped = 0
    with urllib.request.urlopen(base + "/audio/dev.tar.gz", timeout=120) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as archive:
            for member in archive:
                name = Path(member.name).name
                if (
                    not member.isfile()
                    or name not in texts
                    or not 0 < member.size <= MAX_CLIP_BYTES
                ):
                    continue
                if skipped < args.skip:
                    skipped += 1
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                data = stream.read(MAX_CLIP_BYTES + 1)
                if len(data) != member.size:
                    raise ValueError("음성 크기 불일치")
                # 아카이브 경로를 사용하지 않고 고정된 로컬 이름으로 저장합니다.
                raw = args.out / f"raw{len(pieces)}.wav"
                raw.write_bytes(data)
                piece = to_mono16k(raw, args.out / f"human{len(pieces)}.wav")
                pieces.append((piece, texts[name]))
                records.append({"filename": name, "sha256": hashlib.sha256(data).hexdigest()})
                print(f"{args.language}: {len(pieces)}/{args.count}", flush=True)
                if len(pieces) == args.count:
                    break
    if len(pieces) != args.count:
        raise RuntimeError("요청한 개수의 음성을 받지 못했습니다.")
    build_sample(pieces, args.out)
    (args.out / "source.json").write_text(
        json.dumps(
            {
                "dataset": "google/fleurs",
                "revision": REVISION,
                "license": "CC-BY-4.0",
                "language": args.language,
                "config": CONFIGS[args.language],
                "split": "validation",
                "selection": "first matching regular files in dev.tar.gz",
                "skipped_matching_files": args.skip,
                "clips": records,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
