"""Local boundary evidence for an existing constant-shift estimate.

Energy is not a speech recognizer. It may refine an independently obtained VAD
estimate, but must never search the whole recording or select a shift by itself.
"""

from __future__ import annotations

import subprocess
import tempfile
from bisect import bisect_left, bisect_right
from pathlib import Path
from statistics import median

from pipeline.editing import Cue
from worker.rendering import RenderError, ffmpeg_binary


def audio_boundaries(source: Path) -> list[tuple[float, float]]:
    import numpy as np

    # Decode to disk and reduce in chunks: long source audio must not be retained
    # as a giant subprocess stdout buffer. Only the 100 Hz envelope stays in RAM.
    with tempfile.TemporaryDirectory(prefix="r4-sync-edges-") as directory:
        raw = Path(directory) / "analysis.f32"
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
                "highpass=f=400",
                "-f",
                "f32le",
                str(raw),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        chunks = []
        with raw.open("rb") as stream:
            while data := stream.read(160 * 4 * 1000):
                samples = np.frombuffer(data, dtype="<f4")
                samples = samples[: len(samples) // 160 * 160]
                if len(samples):
                    chunks.append(np.mean(samples.reshape(-1, 160) ** 2, axis=1))
    if not chunks:
        return []
    return envelope_spans(np.concatenate(chunks))


def envelope_spans(power) -> list[tuple[float, float]]:  # noqa: ANN001
    import numpy as np
    from scipy.ndimage import binary_closing, maximum_filter1d, median_filter, uniform_filter1d

    power = median_filter(power, size=11)
    if not np.isfinite(power).all() or not power.max():
        return []
    background = np.percentile(power, 10)
    if uniform_filter1d(power, size=100).max() < background * 2:
        raise ValueError(
            "오디오가 일정한 잡음·음량에 가까워 싱크 근거가 부족합니다. 기존 대본을 유지합니다."
        )
    # Smooth 110 ms; estimate stationary background from the quietest decile.
    # Use both the background and the local (10 s) peak to avoid treating an
    # entire quiet recording as silence. Closing joins pauses shorter than 0.5 s.
    threshold = np.maximum(background * 1.5, maximum_filter1d(power, size=1001) * 0.001)
    active = binary_closing(power > threshold, structure=np.ones(51))
    edges = np.diff(np.r_[False, active, False].astype(int))
    return [
        (start / 100, end / 100)
        for start, end in zip(np.where(edges == 1)[0], np.where(edges == -1)[0], strict=True)
        if end - start >= 100
    ]


def boundary_consensus(
    spans: list[tuple[float, float]],
    cues: list[Cue],
    coarse: float,
) -> tuple[float, int] | None:
    """Require three distinct, distributed anchors agreeing within 250 ms.

    Both ends must be within 1.5 s of the coarse alignment; a refinement cannot
    move it more than one second. Overlapping captions cannot multiply votes.
    """
    candidates = []
    spans = sorted(spans)
    starts = [s for s, _ in spans]
    previous_end = -1.0
    used = set()
    for cue in sorted(cues, key=lambda c: c.start):
        if cue.start < previous_end:
            continue
        matches = []
        first = bisect_left(starts, cue.start + coarse - 1.5)
        last = bisect_right(starts, cue.start + coarse + 1.5)
        for index in range(first, last):
            start, end = spans[index]
            if index in used:
                continue
            ds, de = start - cue.start, end - cue.end
            if abs(ds - coarse) <= 1.5 and abs(de - coarse) <= 1.5:
                matches.append((abs(ds - de), index, (ds + de) / 2))
        if matches:
            _, index, shift = min(matches)
            used.add(index)
            candidates.append((shift, cue.start, cue.end))
            previous_end = cue.end
    if len(candidates) < 3:
        return None
    candidates.sort()
    shifts = [c[0] for c in candidates]
    # Store index windows, not N copies of N agreeing anchors for long videos.
    groups = [(bisect_left(shifts, s - 0.25), bisect_right(shifts, s + 0.25)) for s in shifts]
    first, last = max(groups, key=lambda bounds: bounds[1] - bounds[0])
    best = candidates[first:last]
    shift = median(c[0] for c in best)
    if len(best) < 3 or max(c[0] for c in best) - min(c[0] for c in best) > 0.5:
        return None
    # An equally supported, distinct answer is ambiguous, not extra confidence.
    for first, last in groups:
        if last - first == len(best):
            middle = (first + last) // 2
            other = shifts[middle] if len(best) % 2 else (shifts[middle - 1] + shifts[middle]) / 2
            if abs(other - shift) > 0.25:
                return None
    extent = max(c.end for c in cues) - min(c.start for c in cues)
    coverage = max(c[2] for c in best) - min(c[1] for c in best)
    if abs(shift - coarse) > 1.0 or coverage < extent * 0.5:
        return None
    return float(shift), len(best)


def refine_offset(source: Path, cues: list[Cue], coarse: float) -> tuple[float, int] | None:
    try:
        spans = audio_boundaries(source)
    except (OSError, subprocess.SubprocessError, RenderError):
        # Optional evidence cannot replace a successful VAD result on decode
        # failure, and cannot authorize recovery of a failed result either.
        return None
    return boundary_consensus(spans, cues, coarse)
