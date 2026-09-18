"""Optional open-source analysis providers, loaded only when explicitly requested."""

from __future__ import annotations

from pathlib import Path

from pipeline.editing import Cue


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
    cues = [
        Cue(start=s.start, end=s.end, text=s.text.strip())
        for s in result.segments
        if s.text.strip() and s.end > s.start
    ]
    if not cues:
        raise RuntimeError("대본을 오디오에 맞추지 못했습니다. 언어와 음성을 확인하세요.")
    return cues


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
