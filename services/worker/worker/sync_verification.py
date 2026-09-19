"""Verify source-language timing; never align translated text against source audio."""

from __future__ import annotations

import math
import re
import subprocess
import tempfile
from pathlib import Path
from statistics import median

from pipeline.alignment import squeeze
from pipeline.editing import Cue
from worker.rendering import ffmpeg_binary
from worker.sync_evidence import refine_offset


class UnverifiedSync(ValueError):
    """Safe, fixed explanation that can be shown without exposing provider logs."""


def text_shift(original: list[Cue], aligned: list[Cue]) -> tuple[float, int] | None:
    if len(original) != len(aligned) or len(original) < 3:
        return None
    if any(squeeze(a.text) != squeeze(b.text) for a, b in zip(original, aligned, strict=True)):
        return None
    if any(not math.isfinite(c.start + c.end) or c.end <= c.start for c in aligned):
        return None
    deltas = [(b.start - a.start, b.end - a.end) for a, b in zip(original, aligned, strict=True)]
    shift = median((start + end) / 2 for start, end in deltas)
    # Captions often include lead/tail padding. Word boundaries need not equal
    # caption boundaries: estimate a constant shift from their centers, while
    # requiring the aligned words to fit inside the shifted caption interval.
    indices = [
        i
        for i, (start, end) in enumerate(deltas)
        if abs((start + end) / 2 - shift) <= 0.5 and start >= shift - 0.5 and end <= shift + 0.5
    ]
    if len(indices) < max(3, math.ceil(len(original) * 0.6)):
        return None
    extent = max(c.end for c in original) - min(c.start for c in original)
    coverage = max(original[i].end for i in indices) - min(original[i].start for i in indices)
    if coverage < extent * 0.5:
        return None
    return float(shift), len(indices)


def denoise_for_sync(source: Path, target: Path) -> None:
    """A local analysis copy; no stretch, trimming, or modification of source."""
    try:
        subprocess.run(
            [
                ffmpeg_binary(),
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-af",
                "highpass=f=100,afftdn=nr=12:tn=1,dynaudnorm=f=150:g=15:p=0.9:m=100",
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UnverifiedSync("분석용 잡음 제거에 실패했습니다. 기존 대본을 유지합니다.") from exc


def verify_sync(source, cues, options, acoustic, align):  # noqa: ANN001
    if not cues:
        raise ValueError("보정할 자막이 없습니다.")
    options.arguments()
    if options.fix_framerate:
        raise UnverifiedSync("검증된 싱크 보정은 일정 이동만 지원합니다. 프레임률 보정을 끄세요.")
    report = {}
    coarse = None
    try:
        moved, report = acoustic(source, cues, options)
        coarse = float(report["offset_seconds"])
    except ValueError:
        # An acoustic failure is not converted to success without new evidence.
        coarse = None
    if coarse is not None:
        try:
            evidence = refine_offset(source, cues, coarse)
        except ValueError as exc:
            raise UnverifiedSync("원음에 싱크를 검증할 시간 근거가 부족합니다.") from exc
        if evidence and abs(evidence[0] - coarse) <= 0.5:
            return moved, {
                **report,
                "verified_by": "source_boundaries",
                "boundary_support": evidence[1],
                "denoised": False,
            }
    if not options.source_language:
        raise UnverifiedSync("싱크 근거가 부족합니다. 원문 음성 언어를 선택해 다시 시도하세요.")
    if not re.fullmatch(r"[a-z]{2,3}", options.source_language):
        raise UnverifiedSync("원문 음성 언어를 확인하세요.")
    normalized = [Cue(start=c.start, end=c.end, text=" ".join(c.text.split())) for c in cues]
    text = "\n".join(c.text for c in normalized)

    def estimate(path):
        try:
            aligned = align(
                path,
                text,
                model=options.model,
                language=options.source_language,
                device=options.device,
                strict=True,
            )
            return text_shift(normalized, aligned)
        except (ValueError, RuntimeError):
            return None

    def finish(shift, support, denoised, boundary=0):
        if (
            abs(shift) >= options.max_offset_seconds - 0.01
            or min(c.start for c in cues) + shift < 0
        ):
            raise UnverifiedSync("검증한 보정값이 허용 시간 범위를 벗어납니다.")
        return [Cue(start=c.start + shift, end=c.end + shift, text=c.text) for c in cues], {
            **report,
            "offset_seconds": round(shift, 3),
            "framerate_scale": 1.0,
            "profile": options.profile,
            "verified_by": "source_text",
            "source_language": options.source_language,
            "denoised": denoised,
            "text_support": support,
            "boundary_support": boundary,
            "recovery_used": coarse is None,
            "audio_normalized": denoised or report.get("audio_normalized", False),
        }

    raw = estimate(source)
    if raw is not None and coarse is not None:
        if abs(raw[0] - coarse) > 0.5:
            raise UnverifiedSync(
                "발화 보정과 원문 대사 정렬이 충돌합니다. 보정을 적용하지 않습니다."
            )
        return finish(coarse, raw[1], False)
    with tempfile.TemporaryDirectory(prefix="r4-sync-denoise-") as directory:
        cleaned = Path(directory) / "analysis.wav"
        denoise_for_sync(source, cleaned)
        clean = estimate(cleaned)
    candidates = [result for result in (raw, clean) if result is not None]
    if not candidates:
        raise UnverifiedSync("원문 대사 정렬의 근거가 부족합니다. 기존 대본을 유지합니다.")
    shifts = [result[0] for result in candidates]
    if max(shifts) - min(shifts) > 0.5:
        raise UnverifiedSync("원음과 잡음 제거 사본의 정렬이 충돌합니다. 보정을 적용하지 않습니다.")
    shift = float(median(shifts))
    if coarse is not None and abs(coarse - shift) > 0.5:
        raise UnverifiedSync("발화 보정과 원문 대사 정렬이 충돌합니다. 보정을 적용하지 않습니다.")
    if coarse is not None:
        return finish(coarse, min(result[1] for result in candidates), True)
    evidence = refine_offset(source, cues, shift)
    if len(candidates) < 2 and (not evidence or abs(evidence[0] - shift) > 0.5):
        raise UnverifiedSync("원문 대사 정렬을 교차 검증하지 못했습니다. 기존 대본을 유지합니다.")
    return finish(
        shift, min(result[1] for result in candidates), True, evidence[1] if evidence else 0
    )
