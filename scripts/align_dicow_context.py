"""Extract unchanged retry cores only when two aligners agree; never approve a voice ID."""

import argparse
from pathlib import Path

from prepare_conversation_evaluation import load_json, number
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def select_core_words(text, left, right, core_start, core_end, start, end):
    expected = normalize(text)
    if not number(start) or not number(end) or not start <= core_start < core_end <= end:
        raise ValueError("Invalid alignment interval")
    for words in [left, right]:
        if "".join(normalize(w["text"]) for w in words) != expected:
            return None, "incomplete_text_alignment"
        if any(
            not number(w["start"])
            or not number(w["end"])
            or not start <= w["start"] < w["end"] <= end
            for w in words
        ):
            return None, "invalid_alignment_time"
    chars = [w for w in right for _ in normalize(w["text"])]
    result = []
    disagreement = None
    cursor = 0
    for w in left:
        token = normalize(w["text"])
        if not token:
            continue
        matched = chars[cursor : cursor + len(token)]
        cursor += len(token)
        a = min(x["start"] for x in matched)
        b = max(x["end"] for x in matched)
        overlap_left = max(core_start, w["start"]) < min(core_end, w["end"])
        overlap_right = max(core_start, a) < min(core_end, b)
        if overlap_left or overlap_right:
            if not (overlap_left and overlap_right):
                disagreement = disagreement or "core_membership_disagreement"
                continue
            if abs(a - w["start"]) > 0.5 or abs(b - w["end"]) > 0.5:
                disagreement = disagreement or "alignment_disagreement"
                continue
            result.append(dict(w))
    if result:
        status = "partial_timing_consensus" if disagreement else "timing_consensus_only"
        return result, status
    if disagreement:
        return None, disagreement
    return [], "timing_consensus_only"


def select_core(text, left, right, core_start, core_end, start, end):
    words, status = select_core_words(text, left, right, core_start, core_end, start, end)
    return (" ".join(word["text"] for word in words) if words is not None else None), status


def main():
    import soundfile as sf
    import stable_whisper
    import whisperx

    from worker.analysis import word_timings

    p = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "manifest", "rows", "baseline", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    fingerprints = {k: sha256(getattr(args, k)) for k in ["audio", "manifest", "rows", "baseline"]}
    items = load_json(args.manifest)
    rows = load_json(args.rows)
    baseline = load_json(args.baseline)
    id_sets = [{r["id"] for r in group} for group in [items, rows, baseline]]
    if not id_sets[0] == id_sets[1] == id_sets[2] or any(
        len(group) != len(ids) for group, ids in zip([items, rows, baseline], id_sets, strict=True)
    ):
        raise ValueError("Missing or duplicate input rows")
    if any(r["sha256"] != fingerprints["audio"] for r in rows + baseline):
        raise ValueError("Audio differs")
    audio, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or audio.ndim != 1:
        raise ValueError("Require 16k mono audio")
    stable = stable_whisper.load_faster_whisper("small", device="cpu", compute_type="int8")
    model, metadata = whisperx.load_align_model(language_code="en", device="cpu")
    long_rows = {r["id"]: r for r in rows}
    old = {r["id"]: r for r in baseline}
    output = []
    audit = []
    for item in items:
        row = long_rows[item["id"]]
        start, end = item["start"], item["end"]
        text = row["hypothesis"]
        left = []
        right = []
        selected_words = None
        selected = None
        status = "generation_truncated"
        if not row["generation_possibly_truncated"]:
            if not normalize(text):
                selected = ""
                status = "empty_decoding"
            else:
                clip = audio[int(start * rate) : int(end * rate)]
                try:
                    aligned = stable.align(
                        clip, text, language="en", failure_threshold=0.1, verbose=None
                    )
                    left = (
                        [
                            dict(
                                start=float(w.start) + start, end=float(w.end) + start, text=w.text
                            )
                            for w in word_timings(aligned)
                        ]
                        if aligned is not None
                        else []
                    )
                    aligned = whisperx.align(
                        [dict(start=0, end=len(clip) / rate, text=text)],
                        model,
                        metadata,
                        clip,
                        "cpu",
                        interpolate_method="ignore",
                        return_char_alignments=False,
                    )
                    right = [
                        dict(
                            start=float(w["start"]) + start,
                            end=float(w["end"]) + start,
                            text=w["word"],
                        )
                        for w in aligned["word_segments"]
                        if "start" in w and "end" in w
                    ]
                    selected_words, status = select_core_words(
                        text, left, right, item["core_start"], item["core_end"], start, end
                    )
                    selected = (
                        " ".join(word["text"] for word in selected_words)
                        if selected_words is not None
                        else None
                    )
                except (ValueError, RuntimeError):
                    status = "alignment_failed"
        result = dict(row if selected is not None else old[item["id"]])
        result["hypothesis"] = selected if selected is not None else old[item["id"]]["hypothesis"]
        result["context_alignment_status"] = status
        # Raw DiCoW error counts refer to the full context; downstream must recompute.
        for key in ["errors", "cer", "reference_characters"]:
            result.pop(key, None)
        output.append(result)
        audit.append(
            dict(
                id=item["id"],
                status=status,
                fallback=selected is None,
                selected=selected_words if selected is not None and normalize(text) else [],
                left=left,
                right=right,
            )
        )
        print(item["id"], status, flush=True)
    if any(sha256(getattr(args, k)) != v for k, v in fingerprints.items()):
        raise ValueError("Inputs changed")
    write_private_json(
        args.output,
        dict(
            rows=output,
            audit=audit,
            sha256=fingerprints,
            deploy_allowed=False,
            voice_identity_verified=False,
        ),
    )


if __name__ == "__main__":
    main()
