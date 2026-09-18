"""ffprobe 래퍼.

형식·길이·해상도 검사만 담당합니다. 트랙 존재 확인만으로 발화 존재를 판정하지
않습니다. 오디오 신호 분석은 별도 단계입니다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

PROBE_TIMEOUT_SECONDS = 120


class ProbeError(RuntimeError):
    """ffprobe 실행이나 결과 해석에 실패했습니다."""


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration_seconds: float
    width: int | None
    height: int | None
    has_audio: bool
    container: str | None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe(path_or_url: str) -> MediaInfo:
    """ffprobe로 파일을 검사합니다."""
    if not ffprobe_available():
        raise ProbeError("ffprobe를 찾을 수 없습니다.")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name",
        "-show_streams",
        "-of",
        "json",
        path_or_url,
    ]
    try:
        completed = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe 실행이 시간 제한을 넘었습니다.") from exc
    if completed.returncode != 0:
        raise ProbeError(f"ffprobe 실패: {completed.stderr.strip()[:500]}")
    return parse_probe_output(completed.stdout)


def parse_probe_output(raw: str) -> MediaInfo:
    """ffprobe JSON 출력을 해석합니다. 테스트가 이 함수를 직접 부릅니다."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProbeError("ffprobe 출력을 해석할 수 없습니다.") from exc

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    duration_raw = fmt.get("duration")
    if duration_raw is None and video is not None:
        duration_raw = video.get("duration")
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError):
        raise ProbeError("영상 길이를 확인할 수 없습니다.") from None
    if duration <= 0:
        raise ProbeError("영상 길이가 0 이하입니다.")

    return MediaInfo(
        duration_seconds=duration,
        width=_as_int(video.get("width")) if video else None,
        height=_as_int(video.get("height")) if video else None,
        has_audio=has_audio,
        container=fmt.get("format_name"),
    )


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
