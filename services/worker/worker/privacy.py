"""Server-owned privacy redaction backends.

Every backend is invoked with an explicit executable/model path and is fail
closed when the output is missing.  Model files stay outside the repository;
the worker receives their paths through deployment configuration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
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


def _deface(source: Path, output: Path, mosaic_size: int, sensitive: bool) -> None:
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
            *(["--thresh", "0.05", "--mask-scale", "1.5"] if sensitive else []),
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


def _egoblur_timing(source: Path) -> tuple[int, int]:
    """Require the integer frame rate and frame count Gen1 can preserve."""
    message = "EgoBlur 영상 시각을 확인할 수 없습니다. 정수 고정 FPS 영상이나 deface를 사용하세요."
    binary = _executable("R4_FFPROBE_BINARY", "ffprobe", message)
    try:
        result = subprocess.run(
            [
                binary, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate,r_frame_rate,nb_frames",
                "-of", "json", str(source),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )  # fmt: skip
        stream = json.loads(result.stdout)["streams"][0]
        rate = Fraction(stream["avg_frame_rate"])
        frames = int(stream["nb_frames"])
        if rate <= 0 or rate.denominator != 1 or rate != Fraction(stream["r_frame_rate"]):
            raise ValueError("unsupported frame rate")
        if frames <= 0:
            raise ValueError("missing frames")
        return rate.numerator, frames
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ZeroDivisionError,
    ) as exc:
        raise PrivacyError(message) from exc


def _egoblur(source: Path, output: Path, mosaic_size: int) -> None:
    """Keep Gen1's redacted frames at the source rate and restore its audio."""
    del mosaic_size  # EgoBlur applies Gaussian blur; tile size is not applicable.
    binary = _executable(
        "R4_EGOBLUR_BINARY",
        "egoblur-gen1",
        "EgoBlur 실행 파일이 없습니다. R4_EGOBLUR_BINARY를 설정하세요.",
    )
    model = os.environ.get("R4_EGOBLUR_FACE_MODEL")
    if not model or not Path(model).is_file():
        raise PrivacyError("EgoBlur 얼굴 모델이 없습니다. R4_EGOBLUR_FACE_MODEL을 설정하세요.")
    timing = _egoblur_timing(source)
    ffmpeg = _executable("R4_FFMPEG_BINARY", "ffmpeg", "EgoBlur 원음 보존에는 FFmpeg가 필요합니다.")
    with tempfile.TemporaryDirectory(prefix="r4-egoblur-") as directory:
        redacted, merged = Path(directory) / "redacted.mp4", Path(directory) / "merged.mp4"
        _run(
            [
                binary,
                "--face_model_path",
                model,
                "--input_video_path",
                str(source),
                "--output_video_path",
                str(redacted),
                "--output_video_fps",
                str(timing[0]),
            ],
            redacted,
            3600,
            "EgoBlur 얼굴 블러 실패: 모델·입력 영상을 확인하세요.",
        )
        if _egoblur_timing(redacted) != timing:
            raise PrivacyError("EgoBlur 결과의 프레임률·개수가 원본과 달라 적용하지 않았습니다.")
        # Gen1 writes an image sequence without audio. Only the redacted video
        # stream is copied; audio comes from the already edited/rendered source.
        _run(
            [
                ffmpeg, "-nostdin", "-v", "error",
                "-i", str(redacted), "-i", str(source),
                "-map", "0:v:0", "-map", "1:a:0?", "-c", "copy",
                "-movflags", "+faststart", str(merged),
            ],
            merged,
            600,
            "EgoBlur 원음 결합에 실패했습니다.",
        )  # fmt: skip
        shutil.copyfile(merged, output)


def redact_faces(
    source: Path,
    output: Path,
    mosaic_size: int,
    backend: PrivacyBackend = "deface",
    deface_sensitive: bool = False,
) -> None:
    """Apply a configured face-redaction backend to a rendered video."""
    if backend == "deface":
        _deface(source, output, mosaic_size, deface_sensitive)
    elif backend == "openscrub":
        _openscrub(source, output, mosaic_size)
    elif backend == "egoblur":
        _egoblur(source, output, mosaic_size)
    else:  # defensive guard for callers that bypass Pydantic validation
        raise PrivacyError(f"지원하지 않는 프라이버시 백엔드입니다: {backend}")
