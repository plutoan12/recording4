"""FFmpeg + pysubs2 integration. Only server-owned local media paths are accepted."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline.editing import EditSpec
from pipeline.subtitle_templates import build_ass, plain_ass  # noqa: F401 - public compatibility
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules


class RenderError(RuntimeError):
    pass


def ffmpeg_binary() -> str:
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        raise RenderError("FFmpeg가 없습니다. 워커 이미지를 사용하거나 FFmpeg를 설치하세요.")
    return binary


def write_subtitles(path: Path, spec: EditSpec, rules: SubtitleRules = DEFAULT_RULES) -> None:
    path.write_text(build_ass(spec, rules), encoding="utf-8")


def video_filter(spec: EditSpec) -> str:
    w, h = spec.width, spec.height
    if spec.mode == "crop":
        frame = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:(iw-ow)*{spec.focus_x}:(ih-oh)*{spec.focus_y}"
        )
    else:
        frame = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return f"{frame},setsar=1,subtitles=captions.ass,format=yuv420p"


def render_clip(
    source: Path, output: Path, spec: EditSpec, *, rules: SubtitleRules = DEFAULT_RULES
) -> None:
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or source == output:
        raise RenderError("유효한 원본과 별도 출력 경로가 필요합니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r4-render-") as directory:
        temp = Path(directory)
        write_subtitles(temp / "captions.ass", spec, rules)
        command = [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(spec.start),
            "-i",
            str(source),
            "-t",
            str(spec.end - spec.start),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            video_filter(spec),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(temp / "result.mp4"),
        ]
        try:
            completed = subprocess.run(command, cwd=temp, capture_output=True, timeout=3600)
        except subprocess.TimeoutExpired as exc:
            raise RenderError("영상 합성이 1시간 제한을 넘었습니다.") from exc
        if completed.returncode:
            # Do not expose full commands/paths or credentials in job errors.
            raise RenderError(
                "FFmpeg 합성 실패: 설치된 코덱·subtitles 필터·입력 영상을 확인하세요."
            )
        shutil.copyfile(temp / "result.mp4", output)
