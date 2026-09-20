#!/usr/bin/env python3
"""Convert explicit provider files into a private DER-only 120-second pilot.

This is not a complete multilingual cohort and cannot approve deployment.
The caller selects source files BEFORE inference; this command never sees scores.
"""

import argparse
import json
from pathlib import Path

from prepare_conversation_evaluation import load_json, number
from run_sortformer_evaluation import sha256, write_private_json


def clip_turns(turns, end=120):
    result = []
    for row in turns:
        a, b, label = row["start"], row["end"], row["speaker"]
        if not number(a) or not number(b) or not 0 <= a < b:
            raise ValueError("Invalid reference timing")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Missing reference speaker")
        if a < end:
            result.append(dict(start=a, end=min(b, end), speaker=label))
    if not result:
        raise ValueError("No reference speech in fixed pilot interval")
    return result


def jcre3_turns(info):
    rows = info["utterances"]
    if any(not number(r["start"]) or not number(r["end"]) for r in rows):
        raise ValueError("Invalid reference milliseconds")
    return clip_turns(
        [dict(start=r["start"] / 1000, end=r["end"] / 1000, speaker=r["speaker"]) for r in rows]
    )


def ami_turns(payload):
    rows = payload["rows"]
    if len(rows) != 1:
        raise ValueError("Expected one explicitly selected AMI row")
    r = rows[0]["row"]
    return clip_turns(
        [
            dict(start=a, end=b, speaker=s)
            for a, b, s in zip(
                r["timestamps_start"], r["timestamps_end"], r["speakers"], strict=True
            )
        ]
    )


def main():
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=("en", "ja", "zh"), required=True)
    for name in ("audio", "reference", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new private output directory")
    hashes = {name: sha256(getattr(args, name)) for name in ("audio", "reference")}
    expected_rate = 44100 if args.language == "ja" else 16000
    x, rate = sf.read(args.audio, frames=expected_rate * 120, always_2d=True)
    if rate != expected_rate or len(x) != expected_rate * 120 or not np.isfinite(x).all():
        raise ValueError("Expected complete 120s audio at provider sample rate")
    if args.language == "ja":
        if x.shape[1] != 2:
            raise ValueError("Expected Japanese stereo source")
        audio = resample_poly(x.mean(axis=1), 160, 441)
        turns = jcre3_turns(load_json(args.reference))
    elif args.language == "en":
        if x.shape[1] != 1:
            raise ValueError("Expected AMI IHM mono source")
        audio = x[:, 0]
        turns = ami_turns(load_json(args.reference))
    else:
        from praatio import textgrid

        if x.shape[1] != 8:
            raise ValueError("Expected AliMeeting far-field 8-channel source")
        audio = x[:, 0]
        grid = textgrid.openTextgrid(str(args.reference), includeEmptyIntervals=False)
        turns = clip_turns(
            [
                dict(start=e.start, end=e.end, speaker=name)
                for name in grid.tierNames
                for e in grid.getTier(name).entries
                if e.label.strip()
            ]
        )
    if any(sha256(getattr(args, name)) != value for name, value in hashes.items()):
        raise ValueError("Provider input changed")
    args.output.mkdir(mode=0o700, parents=True)
    sf.write(args.output / "audio.wav", audio, 16000, subtype="PCM_16")
    (args.output / "audio.wav").chmod(0o600)
    write_private_json(args.output / "reference.json", turns)
    lock = dict(
        language=args.language,
        evaluation_start=0,
        evaluation_end=120,
        provider_sha256=hashes,
        audio_sha256=sha256(args.output / "audio.wav"),
        reference_sha256=sha256(args.output / "reference.json"),
        metric="DER_only",
        complete_multilingual_cohort=False,
        deploy_allowed=False,
    )
    write_private_json(args.output / "lock.json", lock)
    print(json.dumps(dict(language=args.language, turn_count=len(turns), deploy_allowed=False)))


if __name__ == "__main__":
    main()
