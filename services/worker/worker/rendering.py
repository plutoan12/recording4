"""FFmpeg + pysubs2 integration. Only server-owned local media paths are accepted."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline.editing import EditSpec, clip_cues
from pipeline.subtitle_files import plain_ass
from pipeline.subtitle_templates import SubtitleTemplate, resolve_template, styled_document
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules

__all__ = [
    "RenderError",
    "ffmpeg_binary",
    "plain_ass",
    "render_clip",
    "subtitles_filter",
    "write_subtitles",
]


class RenderError(RuntimeError):
    pass


def ffmpeg_binary() -> str:
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        raise RenderError("FFmpeg가 없습니다. 워커 이미지를 사용하거나 FFmpeg를 설치하세요.")
    return binary


def write_subtitles(
    path: Path,
    spec: EditSpec,
    rules: SubtitleRules = DEFAULT_RULES,
    template: SubtitleTemplate | str | None = None,
) -> None:
    """굽는 자막 ASS 파일을 씁니다.

    모양은 템플릿이 정합니다. 주지 않으면 `spec.subtitle_template`(없으면 default)을
    씁니다. 줄바꿈과 분할은 여기서 확정합니다. libass 자동 줄바꿈에 맡기지 않습니다.
    """
    if template is None:
        template = getattr(spec, "subtitle_template", None)
    try:
        chosen = resolve_template(template)
    except ValueError as exc:
        raise RenderError(str(exc)) from None
    cues = (
        clip_cues(spec.cues, spec.start, spec.end) if getattr(spec, "burn_subtitles", True) else []
    )
    document = styled_document(
        apply_rules(cues, rules),
        chosen,
        width=spec.width,
        height=spec.height,
        duration=spec.end - spec.start,
        title=spec.title,
        font_size=getattr(spec, "font_size", None),
    )
    document.save(str(path), encoding="utf-8")


def fonts_dir() -> str | None:
    """템플릿 글꼴이 든 디렉터리. 워커 이미지는 시스템 글꼴로 설치하므로 비어 있습니다.

    로컬에서 `scripts/fetch_fonts.py --out .fonts`로 받았다면 `R4_FONTS_DIR`로 알려 줍니다.
    """
    value = os.environ.get("R4_FONTS_DIR", "").strip()
    return value or None


def subtitles_filter(filename: str = "captions.ass") -> str:
    """FFmpeg subtitles 필터 문자열. 글꼴 디렉터리가 있으면 libass에 함께 넘깁니다."""
    directory = fonts_dir()
    if not directory:
        return f"subtitles={filename}"
    # 필터 인자에서 콜론·역슬래시·따옴표는 구분자라 이스케이프합니다.
    escaped = directory.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles={filename}:fontsdir='{escaped}'"


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
    return f"{frame},setsar=1,{subtitles_filter()},format=yuv420p"


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
