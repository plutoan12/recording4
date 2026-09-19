"""Timeline-preserving dubbing and final subtitle rendering using FFmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace

from pipeline.editing import Cue, EditSpec
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules
from worker.rendering import ffmpeg_binary, video_filter, write_subtitles

RATE = 48000


class TimingError(RuntimeError):
    pass


def ffmpeg(args: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(
        [ffmpeg_binary(), "-nostdin", "-y", "-v", "error", *args],
        cwd=cwd,
        capture_output=True,
        timeout=3300,
    )
    if result.returncode:
        raise RuntimeError("FFmpeg 처리 실패. 입력 파일과 워커 필터를 확인하세요.")


def silence(out, frames: int) -> None:
    while frames > 0:
        chunk = min(frames, RATE)
        out.writeframes(b"\0\0" * chunk)
        frames -= chunk


def mix_speech(paths: list[Path], cues: list[Cue], duration: float, output: Path) -> list[Cue]:
    aligned = []
    if len(paths) != len(cues):
        raise ValueError("대본과 음성 개수가 다릅니다.")
    with (
        tempfile.TemporaryDirectory(prefix="r4-dub-") as directory,
        wave.open(str(output), "wb") as out,
    ):
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        position = 0
        for i, (path, cue) in enumerate(zip(paths, cues, strict=True)):
            start = round(cue.start * RATE)
            bound = round((cues[i + 1].start if i + 1 < len(cues) else duration) * RATE)
            if start < position or bound <= start:
                raise TimingError(f"{i+1}번 대사의 구간이 겹칩니다. 대본을 수정하세요.")
            wav = Path(directory) / f"{i}.wav"
            ffmpeg(["-i", str(path), "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
            with wave.open(str(wav), "rb") as speech:
                count = speech.getnframes()
            ratio = count / (bound - start)
            if ratio > 1.15:
                raise TimingError(
                    f"{i+1}번 더빙이 구간보다 깁니다. 번역을 줄여 새 버전을 만드세요."
                )
            if ratio > 1:
                adjusted = Path(directory) / f"{i}-fit.wav"
                ffmpeg(
                    [
                        "-i",
                        str(wav),
                        "-af",
                        f"atempo={ratio}",
                        "-ar",
                        str(RATE),
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(adjusted),
                    ]
                )
                wav = adjusted
            silence(out, start - position)
            with wave.open(str(wav), "rb") as speech:
                count = speech.getnframes()
                if count > bound - start + round(0.02 * RATE):
                    raise TimingError(f"{i+1}번 음성이 다음 구간을 침범합니다.")
                # atempo rounding at a boundary can leave <=20ms of trailing samples.
                count = min(count, bound - start)
                out.writeframes(speech.readframes(count))
            aligned.append(
                cue.model_copy(update={"start": start / RATE, "end": (start + count) / RATE})
            )
            position = start + count
        silence(out, max(0, round(duration * RATE) - position))

    return aligned


def compose_dub(source: Path, audio: Path, output: Path, start: float, duration: float) -> None:
    # Original dialogue is removed; background separation is deliberately not implied.
    ffmpeg(
        [
            "-ss",
            str(start),
            "-i",
            str(source),
            "-i",
            str(audio),
            "-t",
            str(duration),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def render_final(
    source: Path,
    output: Path,
    *,
    cues: list[Cue],
    duration: float,
    start: float = 0,
    clip: EditSpec | None = None,
    width: int = 1920,
    height: int = 1080,
    rules: SubtitleRules = DEFAULT_RULES,
    subtitle_template: str = "classic",
) -> None:
    with tempfile.TemporaryDirectory(prefix="r4-final-") as directory:
        temp = Path(directory)
        width, height = (
            (clip.width, clip.height) if clip else (width - width % 2, height - height % 2)
        )
        if width < 2 or height < 2:
            raise ValueError("유효한 영상 해상도가 필요합니다.")
        captions = SimpleNamespace(
            width=width,
            height=height,
            start=0,
            end=duration,
            cues=cues,
            subtitle_template=subtitle_template,
            title=clip.title if clip else "",
            font_size=clip.font_size if clip else max(20, height // 24),
        )
        write_subtitles(temp / "captions.ass", captions, rules)
        filters = (
            video_filter(clip)
            if clip
            else (f"scale={width}:{height},setsar=1,subtitles=captions.ass,format=yuv420p")
        )
        ffmpeg(
            [
                "-ss",
                str(start),
                "-i",
                str(source.resolve()),
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                filters,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "22",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temp / "final.mp4"),
            ],
            cwd=temp,
        )
        shutil.copyfile(temp / "final.mp4", output)
