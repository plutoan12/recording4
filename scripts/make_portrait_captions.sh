#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/packages/pipeline${PYTHONPATH:+:$PYTHONPATH}"
exec "$ROOT/.venv-converter/bin/python" -m pipeline.portrait_captions "$@"
