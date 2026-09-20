#!/usr/bin/env python3
"""Make a fixed-gain analysis copy; no denoising, timing changes or reference input."""

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
from run_sortformer_evaluation import sha256, write_private_json


def analysis_gain(audio):
    """Raise quiet PCM by at most 20 dB toward -1 dBFS peak, never attenuate."""
    audio = np.asarray(audio)
    if audio.ndim != 1 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Expected finite nonempty mono audio")
    peak = float(np.max(np.abs(audio)))
    if peak > 1:
        raise ValueError("Expected normalized PCM")
    gain = 1.0 if peak == 0 else max(1.0, min(10.0, 10 ** (-1 / 20) / peak))
    result = audio.astype(np.float64) * gain
    return result, dict(
        gain_db=20 * math.log10(gain),
        peak_before=peak,
        peak_after=float(np.max(np.abs(result))),
        denoising=False,
    )


def main():
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = args.output.with_suffix(".gain.json")
    if args.output.exists() or metadata.exists():
        parser.error("Use new output paths")
    source_sha = sha256(args.audio)
    audio, rate = sf.read(args.audio, dtype="float64")
    result, info = analysis_gain(audio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        sf.write(stream, result, rate, format="WAV", subtype="PCM_16")
    encoded, encoded_rate = sf.read(args.output, dtype="float64")
    if encoded_rate != rate or encoded.shape != result.shape:
        raise ValueError("Encoded audio timing changed")
    info["peak_after_float"] = info["peak_after"]
    info["peak_after"] = float(np.max(np.abs(encoded)))
    if source_sha != sha256(args.audio):
        raise ValueError("Source changed")
    info.update(
        source_sha256=source_sha,
        output_sha256=sha256(args.output),
        samples=len(audio),
        sample_rate=rate,
        deploy_allowed=False,
    )
    write_private_json(metadata, info)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
