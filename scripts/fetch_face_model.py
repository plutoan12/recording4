#!/usr/bin/env python3
"""자동 리프레이밍의 얼굴 검출 모델을 받습니다(MediaPipe BlazeFace, 230KB).

MediaPipe 1.0에는 모델이 **들어 있지 않습니다.** 옛 `mediapipe.solutions`는
모델을 품고 있었지만 그 API는 사라졌고, 지금의 Tasks API는 `.tflite` 파일을
따로 받아 경로를 넘겨야 합니다.

받지 않아도 리프레이밍은 돕니다. 그때는 OpenCV 내장 검출기로 내려가고
정확도가 낮아집니다. 어느 쪽을 썼는지는 `face_track()`이 함께 돌려줍니다.

    python3 scripts/fetch_face_model.py --out .models

받은 경로를 워커의 `R4_FACE_MODEL`에 넣습니다. 글꼴과 같은 방식으로 **고정
URL과 SHA-256**으로만 받습니다(받아 온 것이 바뀌면 그 자리에서 멈춥니다).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)
SHA256 = "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f"
NAME = "blaze_face_short_range.tflite"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(".models"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / NAME
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == SHA256:
        print(f"이미 있습니다: {target}")
        return 0
    print(f"받는 중: {URL}")
    with urllib.request.urlopen(URL, timeout=120) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        print(f"체크섬이 다릅니다.\n  기대: {SHA256}\n  받음: {digest}")
        return 1
    target.write_bytes(data)
    print(f"저장: {target} ({len(data):,} 바이트)")
    print(f"워커에 R4_FACE_MODEL={target.resolve()} 를 넣으세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
