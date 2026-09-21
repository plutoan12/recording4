"""FFmpeg + pysubs2 integration. Only server-owned local media paths are accepted."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pysubs2

from pipeline.editing import Cue, EditSpec, clip_cues, concat_cues
from pipeline.subtitle_files import plain_ass
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules

__all__ = [
    "RenderError",
    "ffmpeg_binary",
    "plain_ass",
    "render_clip",
    "render_preview",
    "write_subtitles",
]

# 배경음악을 깔 때 말소리 기준으로 음량을 낮추는 값. 잰 값이 아니라 정한 값입니다.
DUCK = "sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400"


class RenderError(RuntimeError):
    pass


def ffmpeg_binary() -> str:
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        raise RenderError("FFmpeg가 없습니다. 워커 이미지를 사용하거나 FFmpeg를 설치하세요.")
    return binary


def write_subtitles(path: Path, spec: EditSpec, rules: SubtitleRules = DEFAULT_RULES) -> None:
    subs = pysubs2.SSAFile()
    subs.info.update(PlayResX=str(spec.width), PlayResY=str(spec.height), WrapStyle="0")
    style = pysubs2.SSAStyle(
        fontname="Noto Sans CJK KR",
        fontsize=spec.font_size,
        outline=3,
        shadow=1,
        marginl=50,
        marginr=50,
        marginv=int(spec.height * 0.13),
    )
    subs.styles["Default"] = style
    # 줄바꿈과 분할을 여기서 확정합니다. libass 자동 줄바꿈에 맡기지 않습니다.
    segments = getattr(spec, "segments", None)
    if not getattr(spec, "burn_subtitles", True):
        shown = []
    elif segments:
        # 이어 붙인 시간축으로 옮깁니다. 빠진 구간의 자막은 함께 빠집니다.
        shown = concat_cues(spec.cues, segments)
    else:
        shown = clip_cues(spec.cues, spec.start, spec.end)
    for cue in apply_rules(shown, rules):
        subs.append(
            pysubs2.SSAEvent(
                start=round(cue.start * 1000), end=round(cue.end * 1000), text=plain_ass(cue.text)
            )
        )
    if spec.title:
        title_style = style.copy()
        title_style.alignment = pysubs2.Alignment.TOP_CENTER
        title_style.marginv = int(spec.height * 0.08)
        subs.styles["Title"] = title_style
        subs.append(
            pysubs2.SSAEvent(
                start=0,
                end=round(getattr(spec, "output_seconds", spec.end - spec.start) * 1000),
                text=plain_ass(spec.title),
                style="Title",
            )
        )
    subs.save(str(path), encoding="utf-8")


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
    """예전과 똑같이 한 번에 잘라 내면 되는가. 그러면 필터 그래프를 쓰지 않습니다."""
    return not spec.segments and not spec.fade_in and not spec.fade_out


def complex_filter(spec: EditSpec, *, audio: str, music: str | None) -> tuple[str, str]:
    """(filter_complex, 소리 출력 이름). 영상 출력은 늘 [vout]입니다.

    구간마다 잘라 배속을 걸고 이어 붙인 뒤(concat), 화면을 맞추고 자막을 굽습니다.
    같은 입력을 여러 번 쓰려면 먼저 split해야 해서 구간이 둘 이상이면 나눕니다.
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
    if count > 1:
        joined = "".join(f"[v{i}][a{i}]" for i in range(count))
        parts.append(f"{joined}concat=n={count}:v=1:a=1[vc][ac]")
        video_label, audio_label = "[vc]", "[ac]"
    else:
        video_label, audio_label = "[v0]", "[a0]"

    total = spec.output_seconds
    fades = []
    if spec.fade_in:
        fades.append(f"fade=t=in:st=0:d={spec.fade_in}")
    if spec.fade_out:
        fades.append(f"fade=t=out:st={round(total - spec.fade_out, 3)}:d={spec.fade_out}")
    parts.append(video_label + ",".join([video_filter(spec), *fades]) + "[vout]")

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


def render_clip(
    source: Path,
    output: Path,
    spec: EditSpec,
    *,
    rules: SubtitleRules = DEFAULT_RULES,
    music: Path | None = None,
    has_audio: bool | None = None,
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
        command = (
            simple_command(source, temp, spec)
            if simple(spec) and music is None
            else graph_command(source, temp, spec, music, has_audio)
        )
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


def simple_command(source: Path, temp: Path, spec: EditSpec) -> list[str]:
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
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        video_filter(spec),
        *ENCODE,
        str(temp / "result.mp4"),
    ]


def graph_command(
    source: Path, temp: Path, spec: EditSpec, music: Path | None, has_audio: bool | None
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
    graph, audio_out = complex_filter(spec, audio=audio, music=music_label)
    command += ["-filter_complex", graph, "-map", "[vout]", "-map", audio_out]
    command += [
        *ENCODE,
        "-t",
        str(round(spec.output_seconds, 3)),
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
