"""Recompute comparisons from immutable recorded scores; no new inference."""

import hashlib
import json
import math
from pathlib import Path

root = Path(__file__).resolve().parent
source = root.parent / "multilingual-pilot-2026-09-20/results.json"
payload = source.read_bytes()
rows = []
for case in json.loads(payload)["cases"]:
    for baseline, candidate in [
        ("community_original", "sortformer_original"),
        ("community_original", "community_gain"),
        ("sortformer_original", "sortformer_gain"),
    ]:
        before = case["prediction_results"][baseline]
        after = case["prediction_results"][candidate]
        assert before["status"] == after["status"] == "succeeded"
        # Floating representation only; never alter the saved denominator.
        assert math.isclose(before["total"], after["total"], rel_tol=0, abs_tol=1e-9)
        metrics = ["diarization error rate", "missed detection", "false alarm", "confusion"]
        rows.append(
            dict(
                language=case["language"],
                baseline=baseline,
                candidate=candidate,
                baseline_der_percent=100 * before[metrics[0]],
                candidate_der_percent=100 * after[metrics[0]],
                delta={key: after[key] - before[key] for key in metrics},
                regressed=[key for key in metrics if after[key] > before[key] + 1e-9],
                reference_sha256=case["reference_sha256"],
                baseline_prediction_sha256=before["prediction_sha256"],
                candidate_prediction_sha256=after["prediction_sha256"],
            )
        )
result = dict(
    claim="Four-language real-conversation accuracy improvement",
    status="not_demonstrated",
    languages_required=["ko", "ja", "zh", "en"],
    measured_der_languages=["ja", "zh", "en"],
    source_sha256=hashlib.sha256(payload).hexdigest(),
    comparisons=rows,
    missing=[
        "complete Korean human speaker/overlap/transcript reference",
        "four-language end-to-end CER and character speaker metrics",
        "independent multi-conversation held-out cohort",
        "same selected candidate regression on original 11 conditions",
    ],
    deployment_allowed=False,
)
(root / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
for row in rows:
    print(row["language"], row["baseline"], "->", row["candidate"], row["regressed"])
