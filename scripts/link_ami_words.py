#!/usr/bin/env python3
"""Link AMI manual words only after the complete saved row matches official RTTM."""

import argparse
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from prepare_conversation_evaluation import load_json, number
from run_sortformer_evaluation import sha256, write_private_json


def row_turns(payload):
    if len(payload["rows"]) != 1:
        raise ValueError("Exactly one source row required")
    row = payload["rows"][0]["row"]
    result = []
    for a, b, speaker in zip(
        row["timestamps_start"], row["timestamps_end"], row["speakers"], strict=True
    ):
        if not number(a) or not number(b) or not 0 <= a < b:
            raise ValueError("Invalid source row time")
        if not isinstance(speaker, str) or not speaker:
            raise ValueError("Invalid source row speaker")
        result.append((round(a, 6), round(b, 6), speaker))
    return result


def match_rttm(payload, text, meeting):
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        w = line.split()
        if len(w) != 10 or w[0] != "SPEAKER" or w[1] != meeting:
            raise ValueError("Unexpected RTTM meeting or schema")
        a, d = float(w[3]), float(w[4])
        if not math.isfinite(a) or not math.isfinite(d) or a < 0 or d <= 0:
            raise ValueError("Invalid RTTM interval")
        rows.append((round(a, 6), round(a + d, 6), w[7]))
    if not rows or sorted(rows) != sorted(row_turns(payload)):
        raise ValueError("Complete source row does not match official RTTM")
    return rows


def merged(turns):
    result = []
    for label in sorted({s for a, b, s in turns}):
        spans = []
        for a, b, s in sorted(turns):
            if s != label:
                continue
            if spans and a <= spans[-1][1]:
                spans[-1][1] = max(b, spans[-1][1])
            else:
                spans.append([a, b])
        result.extend((round(a, 6), round(b, 6), label) for a, b in spans)
    return sorted(result)


def link_words(archive, payload, rttm_text, meeting, end=120):
    if not re.fullmatch(r"[A-Z]{2}\d{4}[a-z]?", meeting) or not number(end) or end <= 0:
        raise ValueError("Invalid meeting or interval")
    row = match_rttm(payload, rttm_text, meeting)
    with zipfile.ZipFile(archive) as z:
        meetings = ET.fromstring(z.read("corpusResources/meetings.xml"))
        found = [m for m in meetings.iter() if m.get("observation") == meeting]
        if len(found) != 1:
            raise ValueError("Missing/ambiguous meeting metadata")
        speakers = {c.attrib["nxt_agent"]: c.attrib["global_name"] for c in found[0]}
        if set(speakers.values()) != {s for a, b, s in row}:
            raise ValueError("Speaker metadata differs")
        words = []
        punctuation = 0
        for agent, label in speakers.items():
            if not re.fullmatch("[A-Z]", agent):
                raise ValueError("Invalid agent")
            doc = ET.fromstring(z.read(f"words/{meeting}.{agent}.words.xml"))
            for w in doc:
                if w.tag != "w":
                    continue
                if "starttime" not in w.attrib or "endtime" not in w.attrib:
                    if w.get("punc") == "true":
                        continue  # Untimed punctuation cannot be assigned to this window.
                    raise ValueError("Unaligned lexical word")
                a, b = float(w.attrib["starttime"]), float(w.attrib["endtime"])
                if not math.isfinite(a) or not math.isfinite(b) or a < 0 or b < a:
                    raise ValueError("Invalid manual word time")
                if a >= end:
                    continue
                text = (w.text or "").strip()
                if w.get("punc") == "true":
                    punctuation += 1
                    continue
                if not text or b <= a:
                    raise ValueError("Unaligned lexical word")
                words.append(
                    dict(
                        start=a,
                        end=min(end, b),
                        speaker=label,
                        text=text,
                        original_end=b,
                        boundary_clipped=b > end,
                    )
                )
    words.sort(key=lambda w: (w["start"], w["end"], w["speaker"]))
    reference = merged([(a, min(b, end), s) for a, b, s in row if a < end])
    if merged([(w["start"], w["end"], w["speaker"]) for w in words]) != reference:
        raise ValueError("Manual words and existing speech coverage differ")
    return dict(
        evaluation_start=0,
        evaluation_end=end,
        segments=words,
        matched_full_turns=len(row),
        punctuation_tokens=punctuation,
        boundary_clipped_words=sum(w["boundary_clipped"] for w in words),
        word_timing_source="human_manual_AMI",
        asr_evaluated=False,
        deploy_allowed=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "row", "rttm", "output", "pilot-lock"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--meeting", required=True)
    args = parser.parse_args()
    fingerprints = {k: sha256(getattr(args, k)) for k in ("archive", "row", "rttm")}
    lock_sha = sha256(args.pilot_lock)
    lock = load_json(args.pilot_lock)
    if (lock["evaluation_start"], lock["evaluation_end"]) != (0, 120):
        raise ValueError("Pilot interval changed")
    result = link_words(
        args.archive,
        load_json(args.row),
        args.rttm.read_text(encoding="utf-8"),
        args.meeting,
        end=lock["evaluation_end"],
    )
    if any(sha256(getattr(args, k)) != v for k, v in fingerprints.items()):
        raise ValueError("Reference inputs changed")
    if sha256(args.pilot_lock) != lock_sha:
        raise ValueError("Pilot lock changed")
    if lock["language"] != "en" or lock["provider_sha256"]["reference"] != fingerprints["row"]:
        raise ValueError("Pilot lock does not match source row")
    if (lock["evaluation_start"], lock["evaluation_end"]) != (0, 120):
        raise ValueError("Pilot interval changed")
    result["audio_sha256"] = lock["audio_sha256"]
    result["pilot_lock_sha256"] = lock_sha
    result["input_sha256"] = fingerprints
    write_private_json(args.output, result)
    print({k: result[k] for k in ("matched_full_turns", "boundary_clipped_words", "asr_evaluated")})


if __name__ == "__main__":
    main()
