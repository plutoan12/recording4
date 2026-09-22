"""FFmpeg + pysubs2 integration. Only server-owned local media paths are accepted."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pipeline.editing import Cue, EditSpec, clip_cues, concat_cues
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

__all__ = [
    "RenderError",
    "ffmpeg_binary",
    "has_audio",
    "plain_ass",
    "render_clip",
    "render_preview",
    "stickers_dir",
    "subtitles_filter",
    "transition_graph",
    "video_filter_args",
    "write_subtitles",
]

# 잡음 제거 세기. FFmpeg 내장 `afftdn`의 잡음 바닥(dB)입니다. 낮출수록 많이
# 깎이고 목소리도 같이 깎입니다. 잰 값이 아니라 정한 값입니다.
DENOISE = {"soft": "afftdn=nf=-20", "strong": "afftdn=nf=-35"}

# 배경음악을 깔 때 말소리 기준으로 음량을 낮추는 값. 잰 값이 아니라 정한 값입니다.
DUCK = "sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400"


class RenderError(RuntimeError):
    pass


def ffmpeg_binary() -> str:
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        raise RenderError("FFmpeg가 없습니다. 워커 이미지를 사용하거나 FFmpeg를 설치하세요.")
    return binary


def stickers_dir() -> Path | None:
    """이미지 스티커(PNG)를 두는 디렉터리. `R4_STICKERS_DIR`로 알려 줍니다."""
    value = os.environ.get("R4_STICKERS_DIR", "").strip()
    return Path(value) if value else None


def sticker_overlays(spec: EditSpec) -> list:
    """이미지 스티커 오버레이 목록. **두 렌더 경로가 같은 것을 씁니다.**

    한쪽에서만 부르면 그 경로의 결과에서 스티커가 조용히 사라집니다(실제로
    그런 적이 있습니다). 디렉터리가 없으면 `image_overlays`가 ValueError 를
    내고 `render_clip` 이 RenderError 로 바꿔 알립니다.
    """
    return image_overlays(
        clip_stickers(getattr(spec, "stickers", None) or [], spec.start, spec.end),
        stickers_dir(),
        width=spec.width,
        height=spec.height,
        duration=getattr(spec, "output_seconds", spec.end - spec.start),
    )


def overlay_chain(
    base_label: str, overlays: list, first_input: int
) -> tuple[list[str], list[str], str]:
    """이미 만들어진 영상 라벨 뒤에 스티커를 얹습니다.

    `overlay_filter_graph`는 `[0:v]`에서 시작하는 단순 경로용입니다. 구간을
    이어 붙이는 그래프 경로에서는 시작 라벨이 `[vout]`이라 그대로 쓸 수 없어
    여기서 조각만 만듭니다. (추가 `-i` 인자, 그래프 조각, 마지막 라벨)입니다.
    """
    inputs: list[str] = []
    parts: list[str] = []
    current = base_label
    for index, item in enumerate(overlays):
        inputs += ["-i", str(item.path)]
        stream = first_input + index
        scaled = f"ss{index}"
        out = f"sticker{index}"
        parts.append(f"[{stream}:v]scale={item.width}:-1[{scaled}]")
        parts.append(
            f"[{current}][{scaled}]overlay=x={item.center_x:.0f}-w/2:y={item.center_y:.0f}-h/2"
            f":enable='between(t,{item.start:.3f},{item.end:.3f})'[{out}]"
        )
        current = out
    return inputs, parts, current


def video_filter_args(spec: EditSpec, *, base_chain: str) -> list[str]:
    """`-vf` 또는 (이미지 스티커가 있으면) `-i … -filter_complex … -map` 인자.

    영상 스트림 매핑까지 돌려주므로 부르는 쪽은 `-map 0:v:0`을 넣지 않습니다.
    """
    overlays = sticker_overlays(spec)
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


def has_audio(source: Path) -> bool:
    """소리가 들어 있는지. 없는 영상에 음성 그래프를 붙이면 FFmpeg가 멈춥니다."""
    probe = shutil.which("ffprobe") or ffmpeg_binary().replace("ffmpeg", "ffprobe")
    try:
        found = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(found.stdout.strip())


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
    segments = getattr(spec, "segments", None)
    if not getattr(spec, "burn_subtitles", True):
        cues = []
    elif segments:
        # 이어 붙인 시간축으로 옮깁니다. 빠진 구간의 자막은 함께 빠집니다.
        cues = concat_cues(spec.cues, segments)
    else:
        cues = clip_cues(spec.cues, spec.start, spec.end)
    length = getattr(spec, "output_seconds", spec.end - spec.start)
    document = styled_document(
        apply_rules(cues, rules),
        chosen,
        width=spec.width,
        height=spec.height,
        duration=length,
        title=spec.title,
        font_size=getattr(spec, "font_size", None),
    )
    # 벡터 스티커는 자막과 같은 문서에 들어갑니다. 이미지 스티커는 합성 단계(overlay)입니다.
    add_sticker_events(
        document,
        clip_stickers(getattr(spec, "stickers", None) or [], spec.start, spec.end),
        width=spec.width,
        height=spec.height,
        duration=length,
    )
    document.save(str(path), encoding="utf-8")


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


def source_time(spec: EditSpec, at: float) -> float:
    """결과 영상의 `at`초가 원본의 몇 초인지. 구간을 이어 붙였으면 그것을 따라갑니다."""
    offset = 0.0
    for span in spec.spans:
        if at < offset + span.output_seconds:
            return span.start + (at - offset) * span.speed
        offset += span.output_seconds
    return spec.spans[-1].end


def write_preview_subtitles(
    path: Path, spec: EditSpec, at: float, rules: SubtitleRules = DEFAULT_RULES
) -> None:
    """그 순간에 떠 있는 자막만 0초로 옮겨 담습니다. 한 장을 뽑을 때 씁니다."""
    frozen = spec.model_copy(update={"fade_in": 0.0, "fade_out": 0.0})
    shown = (
        concat_cues(spec.cues, spec.segments)
        if spec.segments
        else clip_cues(spec.cues, spec.start, spec.end)
    )
    now = [
        Cue(start=0, end=1, text=cue.text)
        for cue in apply_rules(shown, rules)
        if cue.start <= at < cue.end
    ]
    write_subtitles(path, frozen.model_copy(update={"cues": now, "segments": []}), rules)


def render_preview(
    source: Path,
    output: Path,
    spec: EditSpec,
    at: float,
    *,
    rules: SubtitleRules = DEFAULT_RULES,
) -> None:
    """결과의 `at`초 한 장을 PNG로 뽑습니다. 전체를 합성하지 않습니다."""
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or source == output:
        raise RenderError("유효한 원본과 별도 출력 경로가 필요합니다.")
    if not 0 <= at < spec.output_seconds:
        raise RenderError("미리볼 시각이 결과 길이 밖입니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r4-preview-") as directory:
        temp = Path(directory)
        # 자막을 0초에 두었으므로 그 자리에 seek해서 한 장만 뽑습니다.
        write_preview_subtitles(temp / "captions.ass", spec, at, rules)
        command = [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(round(source_time(spec, at), 3)),
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            video_filter(spec),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(temp / "result.png"),
        ]
        run_ffmpeg(command, temp, output, produced="result.png")


def tempo_chain(speed: float) -> str:
    """배속을 소리에도 겁니다. atempo는 한 번에 0.5~2.0배까지라 필요하면 이어 붙입니다."""
    if speed == 1.0:
        return ""
    steps, remaining = [], speed
    while remaining > 2.0:
        steps.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        steps.append("atempo=0.5")
        remaining /= 0.5
    steps.append(f"atempo={remaining:g}")
    return "," + ",".join(steps)


def simple(spec: EditSpec) -> bool:
    """예전의 단순한 한 구간 경로로 충분한지.

    구간 고르기·페이드·전환·잡음 제거·리프레이밍 가운데 하나라도 있으면
    그래프 경로로 갑니다.
    """
    return not (
        spec.segments
        or spec.fade_in
        or spec.fade_out
        or getattr(spec, "denoise", None)
        or getattr(spec, "transition", None)
    )


# 겹쳐 잇기가 눈에 띄지도 않으면서 계산만 복잡해지는 아래쪽 한계.
MIN_OVERLAP = 0.05


def transition_seconds(spec: EditSpec) -> float:
    """실제로 쓸 전환 길이. 토막보다 길게 겹칠 수는 없습니다.

    xfade는 두 토막을 `duration`만큼 겹치므로 **가장 짧은 토막의 절반**까지로
    줄입니다. 그래도 너무 짧으면 0이고, 부르는 쪽은 전환 없이 딱 붙입니다.
    탐지 결과 때문에 렌더가 실패하면 사람이 고칠 방법이 없습니다.
    """
    settings = getattr(spec, "transition", None)
    spans = spec.spans
    if settings is None or len(spans) < 2:
        return 0.0
    shortest = min(span.output_seconds for span in spans)
    usable = min(settings.seconds, shortest / 2)
    return round(usable, 3) if usable >= MIN_OVERLAP else 0.0


def output_seconds(spec: EditSpec) -> float:
    """결과 길이. 전환을 넣으면 이음매마다 겹친 만큼 짧아집니다."""
    overlap = transition_seconds(spec)
    return spec.output_seconds - max(0, len(spec.spans) - 1) * overlap


def transition_graph(spec: EditSpec, count: int, overlap: float) -> list[str]:
    """토막을 xfade/acrossfade로 겹쳐 잇는 그래프 조각. 출력은 [vx]·[ax]입니다.

    xfade의 `offset`은 **지금까지 이어 붙인 길이**에서 겹칠 만큼 당긴 자리입니다.
    한 번 겹칠 때마다 결과가 그만큼 짧아지므로 다음 offset도 함께 당겨집니다.
    """
    kind = spec.transition.kind
    spans = spec.spans
    parts: list[str] = []
    video, sound = "[v0]", "[a0]"
    elapsed = spans[0].output_seconds
    for index in range(1, count):
        offset = round(elapsed - overlap, 3)
        last = index == count - 1
        video_out = "[vx]" if last else f"[vt{index}]"
        sound_out = "[ax]" if last else f"[at{index}]"
        parts.append(
            f"{video}[v{index}]xfade=transition={kind}:duration={overlap}:"
            f"offset={offset}{video_out}"
        )
        parts.append(f"{sound}[a{index}]acrossfade=d={overlap}{sound_out}")
        video, sound = video_out, sound_out
        elapsed = offset + spans[index].output_seconds
    return parts


def complex_filter(
    spec: EditSpec, *, audio: str, music: str | None, path: Sequence[Point] = ()
) -> tuple[str, str]:
    """(filter_complex, 소리 출력 이름). 영상 출력은 늘 [vout]입니다.

    구간마다 잘라 배속을 걸고 이어 붙인 뒤(concat 또는 xfade), 화면을 맞추고
    자막을 굽습니다. 같은 입력을 여러 번 쓰려면 먼저 split해야 해서 구간이
    둘 이상이면 나눕니다.

    `spec.transition`이 있으면 딱 붙이는 대신 겹쳐 잇습니다. 겹친 만큼
    짧아지므로 길이는 `transition_seconds`를 빼고 셉니다. `spec.denoise`는
    소리에만 겁니다.
    """
    spans, parts = spec.spans, []
    count = len(spans)
    if count > 1:
        parts.append(f"[0:v]split={count}" + "".join(f"[vin{i}]" for i in range(count)))
        parts.append(f"{audio}asplit={count}" + "".join(f"[ain{i}]" for i in range(count)))
        sources = [(f"[vin{i}]", f"[ain{i}]") for i in range(count)]
    else:
        sources = [("[0:v]", audio)]
    for index, span in enumerate(spans):
        video_in, audio_in = sources[index]
        parts.append(
            f"{video_in}trim=start={span.start}:end={span.end},"
            f"setpts=(PTS-STARTPTS)/{span.speed}[v{index}]"
        )
        parts.append(
            f"{audio_in}atrim=start={span.start}:end={span.end},"
            f"asetpts=PTS-STARTPTS{tempo_chain(span.speed)}[a{index}]"
        )
    overlap = transition_seconds(spec)
    if count > 1 and overlap:
        parts += transition_graph(spec, count, overlap)
        video_label, audio_label = "[vx]", "[ax]"
    elif count > 1:
        joined = "".join(f"[v{i}][a{i}]" for i in range(count))
        parts.append(f"{joined}concat=n={count}:v=1:a=1[vc][ac]")
        video_label, audio_label = "[vc]", "[ac]"
    else:
        video_label, audio_label = "[v0]", "[a0]"

    total = output_seconds(spec)
    if spec.denoise:
        parts.append(f"{audio_label}{DENOISE[spec.denoise]}[adn]")
        audio_label = "[adn]"
    fades = []
    if spec.fade_in:
        fades.append(f"fade=t=in:st=0:d={spec.fade_in}")
    if spec.fade_out:
        fades.append(f"fade=t=out:st={round(total - spec.fade_out, 3)}:d={spec.fade_out}")
    parts.append(video_label + ",".join([video_filter(spec, path), *fades]) + "[vout]")

    sound = [f.replace("fade=", "afade=") for f in fades]
    if sound:
        parts.append(audio_label + ",".join(sound) + "[af]")
        audio_label = "[af]"
    if music is not None:
        parts.append(
            f"{music}atrim=start=0:end={total},asetpts=PTS-STARTPTS,"
            f"volume={spec.music_gain_db}dB" + ("," + ",".join(sound) if sound else "") + "[mus]"
        )
        if spec.music_duck:
            # 말소리를 기준으로 배경음악만 낮춥니다. 말소리는 두 갈래로 나눠 씁니다.
            parts.append(f"{audio_label}asplit=2[speech][key]")
            parts.append(f"[mus][key]{DUCK}[duck]")
            parts.append("[speech][duck]amix=inputs=2:normalize=0:duration=first[aout]")
        else:
            parts.append(f"{audio_label}[mus]amix=inputs=2:normalize=0:duration=first[aout]")
        audio_label = "[aout]"
    return ";".join(parts), audio_label


def moved_face_time(at: float, spec: EditSpec) -> float | None:
    """원본 시각을 이어 붙인 뒤의 시각으로. 빠진 구간이면 `None`입니다.

    `crop`은 자르고 이어 붙인 **뒤에** 오므로 얼굴 시각도 그 시간축이어야
    합니다. 배속을 걸면 그만큼 당겨집니다.
    """
    offset = 0.0
    for span in spec.spans:
        if span.start <= at <= span.end:
            return offset + (at - span.start) / span.speed
        offset += span.output_seconds
    return None


def clip_path(spec: EditSpec, faces: Sequence[Point] | None) -> list[Point]:
    """가로 중심이 따라갈 경로. 쓰지 않으면 빈 목록입니다.

    `mode="crop"`이고 `reframe`을 켰을 때만 씁니다(`pad`는 화면 전체를 남기므로
    따라갈 것이 없습니다). 검출기가 얼굴을 못 찾았으면 빈 목록이고, 그때 crop은
    지금까지대로 `focus_x` 고정입니다.
    """
    settings = getattr(spec, "reframe", None)
    if settings is None or spec.mode != "crop" or not faces:
        return []
    moved = [(moved_face_time(at, spec), value) for at, value in faces]
    return follow([(at, value) for at, value in moved if at is not None], settings=settings)


def render_clip(
    source: Path,
    output: Path,
    spec: EditSpec,
    *,
    rules: SubtitleRules = DEFAULT_RULES,
    music: Path | None = None,
    has_audio: bool | None = None,
    faces: Sequence[Point] | None = None,
) -> None:
    source, output = source.resolve(), output.resolve()
    if not source.is_file() or source == output:
        raise RenderError("유효한 원본과 별도 출력 경로가 필요합니다.")
    if spec.music_asset_id is not None and music is None:
        raise RenderError("배경음악 원본을 내려받지 못했습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r4-render-") as directory:
        temp = Path(directory)
        write_subtitles(temp / "captions.ass", spec, rules)
        path = clip_path(spec, faces)
        try:
            command = (
                simple_command(source, temp, spec, path)
                if simple(spec) and music is None and not path
                else graph_command(source, temp, spec, music, has_audio, path)
            )
        except ValueError as exc:
            # 스티커 디렉터리처럼 **설정** 때문에 못 만드는 경우입니다. 작업
            # 오류로 보여 줄 수 있게 렌더 오류로 바꿉니다.
            raise RenderError(str(exc)) from None
        run_ffmpeg(command, temp, output)


ENCODE = [
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
]


def simple_command(
    source: Path, temp: Path, spec: EditSpec, path: Sequence[Point] = ()
) -> list[str]:
    """한 구간을 그대로 잘라 내는 예전 경로. 결과가 달라지지 않게 그대로 둡니다."""
    return [
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
        *video_filter_args(spec, base_chain=video_filter(spec, path)),
        "-map",
        "0:a:0?",
        *ENCODE,
        str(temp / "result.mp4"),
    ]


def graph_command(
    source: Path,
    temp: Path,
    spec: EditSpec,
    music: Path | None,
    has_audio: bool | None,
    path: Sequence[Point] = (),
) -> list[str]:
    """구간 이어 붙이기·배속·페이드·배경음악을 쓰는 경로."""
    if has_audio is None:
        # 소리가 있는지 모르면 **있다고 봅니다.** 없다고 잘못 보면 원본 소리를 조용히
        # 버리게 되는데, 그쪽이 훨씬 나쁩니다.
        has_audio = True
    command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    command += ["-i", str(source)]
    audio = "[0:a]"
    if not has_audio:
        command += ["-f", "lavfi", "-t", str(spec.end + 1), "-i", "anullsrc=r=48000:cl=stereo"]
        audio = "[1:a]"
    music_label = None
    if music is not None:
        # 음악이 짧으면 되풀이합니다. 길면 아래 -t가 잘라 냅니다.
        command += ["-stream_loop", "-1", "-i", str(music)]
        music_label = f"[{len(command_inputs(command)) - 1}:a]"
    graph, audio_out = complex_filter(spec, audio=audio, music=music_label, path=path)
    # 이미지 스티커는 이어 붙이기·페이드가 끝난 [vout] 위에 얹습니다. 단순 경로만
    # 얹으면 구간·전환·잡음 제거를 쓸 때 스티커가 조용히 사라집니다.
    overlays = sticker_overlays(spec)
    video_out = "[vout]"
    if overlays:
        inputs, parts, last = overlay_chain("vout", overlays, len(command_inputs(command)))
        command += inputs
        graph = ";".join([graph, *parts])
        video_out = f"[{last}]"
    command += ["-filter_complex", graph, "-map", video_out, "-map", audio_out]
    command += [
        *ENCODE,
        "-t",
        str(round(output_seconds(spec), 3)),
        str(temp / "result.mp4"),
    ]
    return command


def command_inputs(command: list[str]) -> list[str]:
    return [value for flag, value in zip(command, command[1:], strict=False) if flag == "-i"]


def run_ffmpeg(command: list[str], temp: Path, output: Path, produced: str = "result.mp4") -> None:
    try:
        completed = subprocess.run(command, cwd=temp, capture_output=True, timeout=3600)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("영상 합성이 1시간 제한을 넘었습니다.") from exc
    if completed.returncode:
        # Do not expose full commands/paths or credentials in job errors.
        raise RenderError("FFmpeg 합성 실패: 설치된 코덱·subtitles 필터·입력 영상을 확인하세요.")
    shutil.copyfile(temp / produced, output)
