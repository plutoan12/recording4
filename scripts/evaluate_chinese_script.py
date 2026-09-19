#!/usr/bin/env python3
"""Report raw CER and separately measured simplified-output CER. No source rewriting.

Experiment dependency: opencc==1.4.2; use a separate environment/target directory.
The original reference remains unchanged; only the hypothesis is converted.
"""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

from verify_transcribe import distance, squeeze


def main():
    import opencc

    p = argparse.ArgumentParser(description=__doc__)
    for name in ["predictions", "manifest", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    reference = {x["id"]: x for x in json.loads(a.manifest.read_text())}
    predictions = json.loads(a.predictions.read_text())
    if isinstance(predictions, dict):
        predictions = predictions["read_speech"]
    converter = opencc.OpenCC("t2s.json")
    rows = []
    for prediction in predictions:
        if prediction["language"] != "zh":
            continue
        expected = reference[prediction["id"]]
        ref = squeeze(expected["reference"]).casefold()
        raw = squeeze(prediction["hypothesis"]).casefold()
        converted = squeeze(converter.convert(prediction["hypothesis"])).casefold()
        rows.append(
            dict(
                id=prediction["id"],
                reference_characters=len(ref),
                raw_errors=distance(ref, raw),
                simplified_output_errors=distance(ref, converted),
            )
        )
    if not rows:
        raise ValueError("No Chinese samples")
    totals = {
        key: sum(row[key] for row in rows)
        for key in ["reference_characters", "raw_errors", "simplified_output_errors"]
    }
    result = dict(
        schema=1,
        opencc_version=version("opencc"),
        config="t2s.json",
        reference_changed=False,
        exploratory=True,
        rows=rows,
        totals=totals,
    )
    a.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(totals))


if __name__ == "__main__":
    main()
