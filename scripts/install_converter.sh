#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
"$PYTHON" -m venv "$ROOT/.venv-converter"
"$ROOT/.venv-converter/bin/python" -m pip install pysubs2==1.8.0 imageio-ffmpeg==0.6.0 Pillow==11.3.0
echo "설치 완료: sh scripts/convert_subtitles.sh --help"
