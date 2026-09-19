#!/usr/bin/env python3
"""Offline diagnostics using isolated references only AFTER inference.

Projection leakage is an evaluation proxy, not proof of perceptual intelligibility.
Raw ASR text and audio stay in the private audit directory.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from measure_diarization_stress import sample


def main():
    import soundfile as sf

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audits", type=Path, required=True)
    p.add_argument("--voices", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    pieces = []
    for name in ["mono-a0.wav", "mono-b0.wav", "mono-a1.wav", "mono-b1.wav"]:
        x, sr = sf.read(args.voices / name, dtype="float32")
        assert sr == 16000
        pieces.append(x * (0.08 / max(np.sqrt(np.mean(x * x)), 1e-8)))
    rows = []
    for file in sorted(args.audits.glob("*-audit/separation.json")):
        audit = json.loads(file.read_text())
        name = file.parent.name.removesuffix("-audit")
        row = dict(
            case=name,
            status=audit["status"],
            chunk_count=len(audit["chunks"]),
            rejection_counts=dict(
                Counter(reason for c in audit["cues"] for reason in c["reasons"])
            ),
            voice_scores=[c["voice_scores"][0][0] for c in audit["cues"] if "voice_scores" in c],
            voice_margins=[c["voice_margin"] for c in audit["cues"] if "voice_margin" in c],
            text_similarities=[
                c["text_similarity"] for c in audit["cues"] if "text_similarity" in c
            ],
            accepted_words=sum(c["accepted_words"] for c in audit["cues"]),
            changed_assignments=audit.get("changed_assignments", 0),
            stems=[],
        )
        if audit["status"] == "completed":
            mixture, truth, _ = sample(pieces, 0.25 if "25pct" in name else 0.5)
            reference = np.zeros((len(mixture), 2))
            for i, (entry, x) in enumerate(zip(truth, pieces, strict=True)):
                begin = round(entry["start"] * 16000)
                reference[begin : begin + len(x), i % 2] += x
            for channel in range(2):
                stem, sr = sf.read(file.parent / f"stem{channel}.wav")
                assert sr == 16000
                n = min(len(stem), len(reference))
                ref = reference[:n]
                stem = stem[:n]
                coefficients = np.linalg.lstsq(ref, stem, rcond=None)[0]
                energies = np.sum((ref * coefficients) ** 2, axis=0)
                dominant = int(np.argmax(energies))
                other = 1 - dominant
                residual = np.sum((stem - ref @ coefficients) ** 2)
                row["stems"].append(
                    dict(
                        channel=channel,
                        dominant_reference=dominant,
                        target_to_other_db=float(
                            10 * np.log10((energies[dominant] + 1e-12) / (energies[other] + 1e-12))
                        ),
                        unexplained_energy_fraction=float(residual / max(np.sum(stem**2), 1e-12)),
                    )
                )
        rows.append(row)
    args.output.write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
