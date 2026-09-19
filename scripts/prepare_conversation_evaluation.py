#!/usr/bin/env python3
"""Validate and freeze private multilingual conversation inputs, without inference.

A lock is evidence of input consistency, never a quality or deployment approval.
Only hashes/counts are emitted; references and audio remain private.
"""

import argparse
import hashlib
import json
import math
import sys
import wave
from pathlib import Path

LANGUAGES = {"ko", "en", "ja", "zh"}
POLICY = {"der_collar": 0, "include_overlap": True, "sync_tolerance_seconds": 0.5}


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite JSON number")

    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant
    )


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Input must be a file within the private root")
    return path


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def prepare(manifest, root):
    policy = manifest.get("policy")
    if (
        type(manifest.get("schema")) is not int
        or manifest["schema"] != 1
        or policy != POLICY
        or any(type(policy[key]) is not type(value) for key, value in POLICY.items())
    ):
        raise ValueError("Unsupported schema or changed evaluation policy")
    cases = manifest["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("No conversation cases")
    seen, languages, rows, audio_digests = set(), set(), [], set()
    for case in cases:
        name, language = case["id"], case["language"]
        if not isinstance(name, str) or not name or name in seen or language not in LANGUAGES:
            raise ValueError("Invalid/duplicate case ID or language")
        if case.get("kind") != "real_conversation" or case.get("human_annotated") is not True:
            raise ValueError("Read/synthetic speech or automatic labels are not conversation truth")
        if not all(
            isinstance(case.get(k), str) and case[k].strip()
            for k in ("source", "revision", "license", "selection_rule")
        ):
            raise ValueError("Missing source, revision, license or fixed selection rule")
        audio = private_file(root, case["audio"])
        reference = private_file(root, case["reference"])
        audio_sha, reference_sha = digest(audio), digest(reference)
        if audio_sha != case["audio_sha256"] or reference_sha != case["reference_sha256"]:
            raise ValueError("Audio or reference digest changed")
        if audio_sha in audio_digests:
            raise ValueError("Duplicate audio cannot count as a fresh case")
        with wave.open(str(audio), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            if wav.getcomptype() != "NONE" or duration <= 0:
                raise ValueError("Expected nonempty PCM WAV")
        start, end = case["evaluation_start"], case["evaluation_end"]
        if not number(start) or not number(end) or not 0 <= start < end <= duration:
            raise ValueError("Invalid fixed evaluation interval")
        segments = load_json(reference)["segments"]
        if not isinstance(segments, list) or not segments:
            raise ValueError("Empty reference")
        speakers, characters = set(), 0
        for segment in segments:
            a, b, speaker, text = (segment[k] for k in ("start", "end", "speaker", "text"))
            if not number(a) or not number(b) or not start <= a < b <= end:
                raise ValueError("Reference outside evaluation interval or invalid timing")
            if not isinstance(speaker, str) or not speaker.strip():
                raise ValueError("Missing human speaker label")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Missing human transcript")
            speakers.add(speaker)
            characters += len("".join(text.split()))
        if len(speakers) < 2:
            raise ValueError("Conversation needs at least two annotated speakers")
        rows.append(
            dict(
                id=name,
                language=language,
                audio_sha256=audio_sha,
                reference_sha256=reference_sha,
                duration_seconds=duration,
                evaluation_start=start,
                evaluation_end=end,
                reference_speakers=len(speakers),
                reference_segments=len(segments),
                reference_characters=characters,
            )
        )
        seen.add(name)
        languages.add(language)
        audio_digests.add(audio_sha)
    missing = sorted(LANGUAGES - languages)
    # Hash the entire manifest too: changed provenance, selection or paths is a new cohort.
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    return dict(
        schema=1,
        manifest_sha256=hashlib.sha256(encoded).hexdigest(),
        policy=POLICY,
        ready_for_multilingual_evaluation=not missing,
        missing_languages=missing,
        deploy_allowed=False,
        cases=rows,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = prepare(load_json(args.manifest), args.root)
    if args.output.exists():
        if load_json(args.output) != result:
            raise ValueError("Existing cohort lock differs; use a new output, never overwrite it")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also protects against a concurrent writer.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False))
    raise SystemExit(0 if result["ready_for_multilingual_evaluation"] else 2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, wave.Error, EOFError):
        print(
            "Invalid conversation inputs or output; inspect private files locally.", file=sys.stderr
        )
        raise SystemExit(1) from None
