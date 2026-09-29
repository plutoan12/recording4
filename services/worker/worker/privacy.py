"""Server-owned privacy redaction backends.

Every backend is invoked with an explicit executable/model path and is fail
closed when the output is missing.  Model files stay outside the repository;
the worker receives their paths through deployment configuration.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

PrivacyBackend = Literal["deface", "openscrub", "egoblur"]


class PrivacyError(RuntimeError):
    """A privacy transform could not be completed safely."""


def _executable(env_name: str, default: str, message: str) -> str:
    binary = os.environ.get(env_name) or shutil.which(default)
    if not binary:
        raise PrivacyError(message)
    return binary


def _run(command: list[str], output: Path, timeout: int, message: str) -> None:
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PrivacyError(message) from exc
    if completed.returncode or not output.is_file() or output.stat().st_size == 0:
        raise PrivacyError(message)


def _deface(source: Path, output: Path, mosaic_size: int) -> None:
    binary = _executable(
        "R4_DEFACE_BINARY", "deface", "얼굴 모자이크 도구가 없습니다. 워커에 deface를 설치하세요."
    )
    _run(
        [
            binary,
            str(source),
            "--replacewith",
            "mosaic",
            "--mosaicsize",
            str(mosaic_size),
            "--keep-audio",
            "--output",
            str(output),
        ],
        output,
        3600,
        "얼굴 모자이크 실패: 얼굴 검출 모델과 입력 영상을 확인하세요.",
    )


def _openscrub(source: Path, output: Path, mosaic_size: int) -> None:
    binary = _executable(
        "R4_OPENSCRUB_BINARY",
        "openscrub",
        "OpenScrub 실행 파일이 없습니다. R4_OPENSCRUB_BINARY를 설정하세요.",
    )
    model = os.environ.get("R4_OPENSCRUB_FACE_MODEL")
    if not model or not Path(model).is_file():
        raise PrivacyError("OpenScrub 얼굴 모델이 없습니다. R4_OPENSCRUB_FACE_MODEL을 설정하세요.")
    _run(
        [
            binary,
            str(source),
            "--categories",
            "face",
            "--face-model",
            model,
            "--mode",
            "mosaic",
            "--face-expand",
            "0.15",
            "--output",
            str(output),
            "--overwrite",
        ],
        output,
        3600,
        "OpenScrub 얼굴 모자이크 실패: 모델·FFmpeg·입력 영상을 확인하세요.",
    )


def _egoblur(source: Path, output: Path, mosaic_size: int) -> None:
    del mosaic_size  # EgoBlur applies Gaussian blur; tile size is not applicable.
    binary = _executable(
        "R4_EGOBLUR_BINARY",
        "egoblur-gen1",
        "EgoBlur 실행 파일이 없습니다. R4_EGOBLUR_BINARY를 설정하세요.",
    )
    model = os.environ.get("R4_EGOBLUR_FACE_MODEL")
    if not model or not Path(model).is_file():
        raise PrivacyError("EgoBlur 얼굴 모델이 없습니다. R4_EGOBLUR_FACE_MODEL을 설정하세요.")
    _run(
        [
            binary,
            "--face_model_path",
            model,
            "--input_video_path",
            str(source),
            "--output_video_path",
            str(output),
        ],
        output,
        3600,
        "EgoBlur 얼굴 블러 실패: 모델·입력 영상을 확인하세요.",
    )


def redact_faces(
    source: Path,
    output: Path,
    mosaic_size: int,
    backend: PrivacyBackend = "deface",
) -> None:
    """Apply a configured face-redaction backend to a rendered video."""
    if backend == "deface":
        _deface(source, output, mosaic_size)
    elif backend == "openscrub":
        _openscrub(source, output, mosaic_size)
    elif backend == "egoblur":
        _egoblur(source, output, mosaic_size)
    else:  # defensive guard for callers that bypass Pydantic validation
        raise PrivacyError(f"지원하지 않는 프라이버시 백엔드입니다: {backend}")
