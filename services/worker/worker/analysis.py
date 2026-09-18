"""Optional open-source analysis providers, loaded only when explicitly requested."""

from __future__ import annotations

from pathlib import Path

from pipeline.editing import Cue


def transcribe(
    source: Path, *, model: str = "small", language: str | None = None, device: str = "cpu"
) -> list[Cue]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
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


def detect_scenes(source: Path, *, threshold: float = 27.0) -> list[dict]:
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:
        raise RuntimeError(
            "장면 감지 의존성이 없습니다. pip install '.[analysis]'를 실행하세요."
        ) from exc
    return [
        {"start": start.get_seconds(), "end": end.get_seconds()}
        for start, end in detect(
            str(source), ContentDetector(threshold=threshold), start_in_scene=True
        )
    ]
