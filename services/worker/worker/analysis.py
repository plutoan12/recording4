"""Optional open-source analysis providers, loaded only when explicitly requested."""

from __future__ import annotations

from pathlib import Path

from pipeline.alignment import WordTiming, cues_for_lines
from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn


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
    if not cues:
        raise RuntimeError("대본을 오디오에 맞추지 못했습니다. 언어와 음성을 확인하세요.")
    return cues


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
