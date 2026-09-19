#!/usr/bin/env python3
"""얼굴 검출기 파일을 받아 이미지 안에 둡니다. 빌드할 때 한 번 돕니다.

`opencv-python-headless` **5.0.0** 휠에는 Haar 캐스케이드 XML이 들어 있지
않았습니다(CI 실측: `cv2/data/haarcascade_frontalface_default.xml` 없음.
`cv2.data` 경로는 있는데 파일이 없습니다). 지금은 4.x로 내려 고정했는데, 그
휠이 싣고 있는지는 아직 재지 않았습니다. 임포트 확인이 매번 찍습니다. 싣고
있다고 확인되면 이 내려받기는 지워도 됩니다.

저장소에 900KB짜리 남의 데이터 파일을 넣는 대신 **버전과 체크섬을 고정해서**
받습니다. 워커 이미지는 이미 빌드할 때 PyTorch를 받으므로 망을 쓰는 것 자체가
새로운 조건은 아닙니다. 체크섬이 다르면 빌드가 거기서 멈춥니다.

    python infra/fetch_face_model.py /opt/opencv-data
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

VERSION = "4.10.0"
NAME = "haarcascade_frontalface_default.xml"
URL = f"https://raw.githubusercontent.com/opencv/opencv/{VERSION}/data/haarcascades/{NAME}"
# 2026-09-19에 받은 파일의 sha256입니다. 내용이 바뀌면 빌드가 멈춥니다.
SHA256 = "0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0"


def main() -> int:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/opencv-data")
    directory.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=180) as response:  # noqa: S310 - 고정 https 주소
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        print(f"얼굴 검출기 파일 체크섬이 다릅니다.\n  받은 값: {digest}\n  적어 둔 값: {SHA256}")
        return 1
    (directory / NAME).write_bytes(data)
    print(f"얼굴 검출기 {NAME} ({len(data)}바이트) → {directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
