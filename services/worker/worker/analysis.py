"""Optional open-source analysis providers, loaded only when explicitly requested."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pipeline.alignment import (
    WordTiming,
    cues_for_lines,
    snap_starts,
    spans_from_timestamps,
)
from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn
from worker.rendering import ffmpeg_binary


class MissingDependency(RuntimeError):
    """선택 의존성이 없습니다. 설치 안내는 외부 입력이 아니므로 그대로 보여줍니다."""


def transcribe(
    source: Path, *, model: str = "small", language: str | None = None, device: str = "cpu"
) -> list[Cue]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise MissingDependency(
            "STT 의존성이 없습니다. pip install '.[analysis]'를 실행하세요."
        ) from exc
    engine = WhisperModel(
        model, device=device, compute_type="int8" if device == "cpu" else "float16"
    )
    segments, _ = engine.transcribe(
        str(source), language=language, vad_filter=True, word_timestamps=True
    )
    return [
        Cue(start=s.start, end=s.end, text=s.text.strip())
        for s in segments
        if s.text.strip() and s.end > s.start
    ]


def align_text(
    source: Path,
    text: str,
    *,
    model: str = "small",
    language: str | None = None,
    device: str = "cpu",
) -> list[Cue]:
    """이미 있는 대본을 오디오에 맞춰 시각을 붙입니다.

    전사가 아니라 정렬입니다. 글자는 입력한 그대로 두고 시간만 찾습니다.
    사용자가 손으로 고친 대본이나 타이밍 없이 받은 대본에 씁니다.

    대본에 줄바꿈이 있으면 그 줄이 자막 하나가 됩니다. 정렬기의 줄 유지
    옵션은 시각을 밀어서(측정: 첫 자막 1초 지연) 쓰지 않습니다. 대신 한
    덩어리로 정렬해 정확한 단어 시각을 받고 줄 나누기는 우리가 합니다.
    맞출 수 없으면 정렬기가 나눈 구간을 그대로 씁니다.
    """
    if not text.strip():
        raise ValueError("정렬할 대본이 비어 있습니다.")
    try:
        import stable_whisper
    except ImportError as exc:
        raise MissingDependency(
            "자막 정렬 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        ) from exc
    engine = stable_whisper.load_faster_whisper(
        model, device=device, compute_type="int8" if device == "cpu" else "float16"
    )
    result = engine.align(str(source), text, language=language)
    cues = cues_for_lines(text.splitlines(), word_timings(result)) or [
        Cue(start=s.start, end=s.end, text=s.text.strip())
        for s in result.segments
        if s.text.strip() and s.end > s.start
    ]
    # 단어 시각이 무음 안쪽으로 당겨지거나 발화 중간으로 밀리는 경우가 있어
    # 자막 시작을 그 자막이 걸친 발화의 시작에 맞춥니다.
    cues = snap_starts(cues, speech_spans(source))
    if not cues:
        raise RuntimeError("대본을 오디오에 맞추지 못했습니다. 언어와 음성을 확인하세요.")
    return cues


_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")
_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")


def vad_spans(source: Path) -> list[tuple[float, float]]:
    """Silero VAD로 발화 구간을 찾습니다. 못 쓰면 빈 목록입니다.

    faster-whisper에 들어 있는 VAD라 새 의존성이 없습니다. 실제 녹음은
    배경 잡음이 있어서 무음 감지(FFmpeg silencedetect)로는 발화 구간을
    찾지 못합니다(측정: 사람 목소리에서 자막이 1.57초 늦게 시작). VAD는
    잡음이 있어도 사람 목소리를 찾습니다.
    """
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except ImportError:
        return []
    try:
        audio = decode_audio(str(source), sampling_rate=16000)
        # 기본값은 발화 앞뒤에 400ms를 덧붙입니다. 그대로 쓰면 자막이 그만큼
        # 일찍 시작합니다(측정: 첫 자막 0.59초, 실제 1.00초). 여유를 끕니다.
        try:
            stamps = get_speech_timestamps(audio, VadOptions(speech_pad_ms=0))
        except TypeError:  # 이 버전에 없는 설정
            stamps = get_speech_timestamps(audio)
    except Exception:  # noqa: BLE001 - 다듬기 실패가 정렬을 막지 않습니다.
        return []
    return spans_from_timestamps(stamps)


def silence_spans(
    source: Path, *, noise: str = "-35dB", minimum: float = 0.25
) -> list[tuple[float, float]]:
    """무음 사이를 발화 구간으로 봅니다. VAD를 못 쓸 때의 대안입니다.

    디지털 무음이 또렷한 음성에서만 믿을 만합니다. FFmpeg가 없거나 실패하면
    빈 목록입니다.
    """
    try:
        binary = ffmpeg_binary()
    except Exception:  # noqa: BLE001 - FFmpeg가 없으면 다듬지 않고 넘어갑니다.
        return []
    try:
        done = subprocess.run(
            [
                binary,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-af",
                f"silencedetect=noise={noise}:duration={minimum}",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    starts = [float(v) for v in _SILENCE_START.findall(done.stderr)]
    ends = [float(v) for v in _SILENCE_END.findall(done.stderr)]
    # 무음이 끝나는 지점부터 다음 무음이 시작되는 지점까지가 발화입니다.
    begins = ([] if starts and starts[0] <= 0.01 else [0.0]) + ends
    finishes = starts[1:] if starts and starts[0] <= 0.01 else starts
    return [(b, f) for b, f in zip(begins, finishes, strict=False) if f > b]


def speech_spans(source: Path) -> list[tuple[float, float]]:
    """발화 구간 목록. VAD를 먼저 쓰고 안 되면 무음 감지로 내려갑니다."""
    found = vad_spans(source)
    return found if found else silence_spans(source)


def diarize(
    source: Path,
    *,
    token: str | None,
    device: str = "cpu",
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[SpeakerTurn]:
    """누가 언제 말했는지 구간으로 나눕니다. 무엇을 말했는지는 다루지 않습니다.

    pyannote 모델이 Hugging Face 게이트 모델이라 토큰과 약관 동의가 필요합니다.
    토큰이 없으면 호출 전에 막습니다. 모델은 첫 실행 때 내려받습니다.
    """
    if not token:
        raise MissingDependency(
            "화자 분리에는 Hugging Face 토큰이 필요합니다. pyannote 모델 약관에 동의한 뒤 "
            "R4_HF_TOKEN을 설정하세요."
        )
    try:
        # whisperx 버전에 따라 위치가 다릅니다. 둘 다 받아 줍니다.
        try:
            from whisperx.diarize import DiarizationPipeline
        except ImportError:
            from whisperx import DiarizationPipeline
    except ImportError as exc:
        raise MissingDependency(
            "화자 분리 의존성이 없습니다. pip install '.[subtitles]'를 실행하세요."
        ) from exc
    pipeline = DiarizationPipeline(use_auth_token=token, device=device)
    frame = pipeline(str(source), min_speakers=min_speakers, max_speakers=max_speakers)
    turns = [
        SpeakerTurn(start=float(row.start), end=float(row.end), speaker=str(row.speaker))
        for row in frame.itertuples()
        if float(row.end) > float(row.start)
    ]
    if not turns:
        raise RuntimeError("화자를 찾지 못했습니다. 음성이 있는 원본인지 확인하세요.")
    return sorted(turns, key=lambda t: t.start)


def word_timings(result) -> list[WordTiming]:  # noqa: ANN001
    """정렬 결과에서 단어 시각을 모읍니다. 단어가 없으면 빈 목록입니다."""
    found: list[WordTiming] = []
    for segment in getattr(result, "segments", []):
        for word in getattr(segment, "words", None) or []:
            text = getattr(word, "word", "") or ""
            start, end = getattr(word, "start", None), getattr(word, "end", None)
            if text.strip() and start is not None and end is not None:
                found.append(WordTiming(start=float(start), end=float(end), text=text))
    return found


def detect_scenes(source: Path, *, threshold: float = 27.0) -> list[dict]:
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise MissingDependency(
            "장면 감지 의존성이 없습니다. pip install '.[analysis]'를 실행하세요."
        ) from exc
    return [
        {"start": start.get_seconds(), "end": end.get_seconds()}
        for start, end in detect(
            str(source), ContentDetector(threshold=threshold), start_in_scene=True
        )
    ]
