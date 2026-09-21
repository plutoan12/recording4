"""FFmpeg + pysubs2 integration. Only server-owned local media paths are accepted."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pipeline.editing import EditSpec, clip_cues
from pipeline.reframe import Point, crop_x, follow
from pipeline.subtitle_files import plain_ass
from pipeline.subtitle_stickers import (
    add_sticker_events,
    clip_stickers,
    image_overlays,
    overlay_filter_graph,
)
from pipeline.subtitle_templates import SubtitleTemplate, resolve_template, styled_document
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules, pacing_rules
from pipeline.trimming import (
    Span,
    keeps,
    kept_seconds,
    moved,
    moved_cues,
    moved_span,
    select_expression,
    trims,
)

__all__ = [
    "RenderError",
    "audio_filter_args",
    "clip_keeps",
    "clip_path",
    "ffmpeg_binary",
    "plain_ass",
    "render_clip",
    "stickers_dir",
    "subtitles_filter",
    "trim_filters",
    "trimmed_spec",
    "video_filter_args",
    "write_subtitles",
]

# 자르고 나서 이보다 짧게 남으면 영상이라 보기 어렵습니다.
MIN_TRIMMED_SECONDS = 0.5

# 잡음 제거 세기. FFmpeg 내장 `afftdn`의 잡음 바닥(dB)입니다. 낮출수록 많이
# 깎이고 목소리도 같이 깎입니다. 잰 값이 아니라 정한 값입니다.
DENOISE = {"soft": "afftdn=nf=-20", "strong": "afftdn=nf=-35"}


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
    쓰고, `spec.subtitle_preset`·`spec.subtitle_animation`이 있으면 그 값으로 바꿉니다.
    줄바꿈과
    분할은 여기서 확정합니다. libass 자동 줄바꿈에 맡기지 않습니다.
    """
    if template is None:
        template = getattr(spec, "subtitle_template", None)
    animation = getattr(spec, "subtitle_animation", None)
    preset = getattr(spec, "subtitle_preset", None)
    try:
        chosen = resolve_template(template)
        if preset is not None:
            chosen = chosen.with_preset(preset)
        if animation:
            chosen = chosen.with_animation(animation)
    except ValueError as exc:
        raise RenderError(str(exc)) from None
    # 끊는 방식을 고르면 그 규칙을 씁니다. 비우면 부르는 쪽이 준 규칙 그대로입니다.
    pacing = getattr(spec, "subtitle_pacing", None)
    if pacing:
        try:
            rules = pacing_rules(pacing, getattr(spec, "caption_language", None), rules)
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
    # 벡터 스티커는 자막과 같은 문서에 들어갑니다. 이미지 스티커는 합성 단계(overlay)입니다.
    add_sticker_events(
        document,
        clip_stickers(getattr(spec, "stickers", None) or [], spec.start, spec.end),
        width=spec.width,
        height=spec.height,
        duration=spec.end - spec.start,
    )
    document.save(str(path), encoding="utf-8")


def stickers_dir() -> Path | None:
    """이미지 스티커(PNG)를 두는 디렉터리. `R4_STICKERS_DIR`로 알려 줍니다."""
    value = os.environ.get("R4_STICKERS_DIR", "").strip()
    return Path(value) if value else None


def video_filter_args(spec: EditSpec, *, base_chain: str) -> list[str]:
    """`-vf` 또는 (이미지 스티커가 있으면) `-i … -filter_complex … -map` 인자.

    영상 스트림 매핑까지 돌려주므로 부르는 쪽은 `-map 0:v:0`을 넣지 않습니다.
    """
    overlays = image_overlays(
        clip_stickers(getattr(spec, "stickers", None) or [], spec.start, spec.end),
        stickers_dir(),
        width=spec.width,
        height=spec.height,
        duration=spec.end - spec.start,
    )
    if not overlays:
        return ["-map", "0:v:0", "-vf", base_chain]
    inputs, graph, out = overlay_filter_graph(base_chain, overlays)
    return [*inputs, "-filter_complex", graph, "-map", f"[{out}]"]


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


def video_filter(spec: EditSpec, path: Sequence[Point] = ()) -> str:
    """영상 필터 체인. `path`가 있으면 가로 중심이 그 경로를 따라갑니다."""
    w, h = spec.width, spec.height
    if spec.mode == "crop":
        # 식에 쉼표가 있어 작은따옴표로 묶습니다(묶지 않으면 필터 구분자입니다).
        x = f"'{crop_x(path, spec.focus_x)}'" if path else f"(iw-ow)*{spec.focus_x}"
        frame = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}:{x}:(ih-oh)*{spec.focus_y}"
        )
    else:
        frame = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return f"{frame},setsar=1,{subtitles_filter()},format=yuv420p"


def clip_keeps(source: Path, spec: EditSpec, speech: Sequence[Span] | None = None) -> list[Span]:
    """이 구간에서 남길 토막. `spec.silence`가 비어 있으면 통째로 하나입니다.

    발화 구간을 주지 않으면 여기서 찾습니다(Silero VAD, 실패하면 FFmpeg
    무음 감지). 테스트와 미리 재기는 직접 넣어 씁니다.
    """
    whole = [(0.0, spec.end - spec.start)]
    chosen = getattr(spec, "keep", None)
    if chosen:
        # 사람이 화면에서 고친 토막입니다. 기계가 다시 덮지 않습니다.
        return [(float(start), float(end)) for start, end in chosen]
    settings = getattr(spec, "silence", None)
    if settings is None:
        return whole
    if speech is None:
        from worker.analysis import speech_spans

        speech = speech_spans(source)
    return keeps(speech, start=spec.start, end=spec.end, settings=settings)


def clip_path(
    source: Path,
    spec: EditSpec,
    kept: Sequence[Span],
    faces: Sequence[Point] | None = None,
) -> list[Point]:
    """가로 중심이 따라갈 경로. 쓰지 않으면 빈 목록입니다.

    **무음 컷과 같은 시간축을 씁니다.** `crop`은 자르기(`select`) 뒤에 오므로
    얼굴 시각도 잘린 뒤의 시각으로 옮겨야 합니다. 잘려 나간 자리의 점은
    버립니다.
    """
    settings = getattr(spec, "reframe", None)
    if settings is None or spec.mode != "crop":
        return []
    if faces is None:
        from worker.analysis import face_track

        faces = face_track(source, start=spec.start, end=spec.end)[0]
    if trims(kept):
        shifted = [(moved(at, kept), value) for at, value in faces]
        faces = [(at, value) for at, value in shifted if at is not None]
    return follow(faces, settings=settings)


def trimmed_spec(spec: EditSpec, kept: Sequence[Span]) -> EditSpec:
    """자른 뒤의 시간축으로 옮긴 편집 지시.

    구간이 0초에서 시작하고 자막·스티커가 이미 옮겨져 있으므로, 뒤따르는
    `clip_cues`·`clip_stickers`는 그대로 지나갑니다.
    """
    length = kept_seconds(kept)
    if length < MIN_TRIMMED_SECONDS:
        raise RenderError(
            f"무음을 자르고 나면 {length:.1f}초만 남습니다. 구간을 넓히거나 컷을 약하게 하세요."
        )
    stickers = []
    for sticker in clip_stickers(getattr(spec, "stickers", None) or [], spec.start, spec.end):
        span = moved_span(sticker.start, sticker.end, kept)
        if span:
            stickers.append(sticker.model_copy(update={"start": span[0], "end": span[1]}))
    return spec.model_copy(
        update={
            "start": 0.0,
            "end": length,
            "cues": moved_cues(clip_cues(spec.cues, spec.start, spec.end), kept),
            "stickers": stickers,
            "silence": None,
            "keep": None,
        }
    )


def trim_filters(kept: Sequence[Span]) -> tuple[str, list[str]]:
    """(영상 체인 앞머리, 음성 필터 조각). 자를 것이 없으면 빈 값입니다.

    `select`는 남길 프레임만 통과시키고 `setpts`가 남은 프레임의 시각을 도로
    0부터 세어 빈자리를 없앱니다. 식에 쉼표가 있어 작은따옴표로 묶습니다
    (묶지 않으면 필터 인자 구분자로 읽힙니다).
    """
    if not trims(kept):
        return "", []
    expression = select_expression(kept)
    return (
        f"select='{expression}',setpts=N/FRAME_RATE/TB,",
        [f"aselect='{expression}'", "asetpts=N/SR/TB"],
    )


def audio_filter_args(spec: EditSpec, kept: Sequence[Span]) -> list[str]:
    """`-filter:a` 인자. 무음 컷과 잡음 제거를 한 체인으로 잇습니다.

    **자르기가 먼저입니다.** 버릴 구간까지 잡음을 깎는 것은 헛일이고, 잡음
    제거가 이어 붙인 자리의 이음매를 뭉개는 편이 낫습니다.
    """
    chain = trim_filters(kept)[1]
    level = getattr(spec, "denoise", None)
    if level:
        chain.append(DENOISE[level])
    return ["-filter:a", ",".join(chain)] if chain else []


def render_clip(
    source: Path,
    output: Path,
    spec: EditSpec,
    *,
    rules: SubtitleRules = DEFAULT_RULES,
    speech: Sequence[Span] | None = None,
    faces: Sequence[Point] | None = None,
) -> None:
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or source == output:
        raise RenderError("유효한 원본과 별도 출력 경로가 필요합니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    kept = clip_keeps(source, spec, speech)
    prefix, _ = trim_filters(kept)
    # 자른 뒤에는 시간축이 달라집니다. 자막·스티커·얼굴 경로를 먼저 옮깁니다.
    shown = trimmed_spec(spec, kept) if trims(kept) else spec
    path = clip_path(source, spec, kept, faces)
    with tempfile.TemporaryDirectory(prefix="r4-render-") as directory:
        temp = Path(directory)
        write_subtitles(temp / "captions.ass", shown, rules)
        try:
            filters = video_filter_args(shown, base_chain=prefix + video_filter(shown, path))
        except ValueError as exc:
            raise RenderError(str(exc)) from None
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
            *filters,
            "-map",
            "0:a:0?",
            *audio_filter_args(spec, kept),
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
