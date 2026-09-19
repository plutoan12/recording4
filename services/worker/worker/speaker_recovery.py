"""Optional local retries. Never infer a speaker from the known benchmark answer.

Stage 3 requires two aligners to agree before filling an unresolved word.
Stage 4 separates two voices for analysis, then requires voice and text evidence.
Original media is never changed. Resolved assignments are preserved by default;
explicit reconsideration requires overlap and independently checked evidence.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline.alignment import WordTiming, squeeze
from pipeline.speakers import MULTIPLE_SPEAKERS, review_speakers
from worker.analysis import align_speaker_words, ffmpeg_binary


def _indexed(review):
    indexed = []
    for word in review["words"]:
        indexed.extend([word] * len(squeeze(word["text"])))
    return indexed


def merge_agreed(base, left, right, *, reconsider=False):
    """Keep the source denominator and only recover words supported by both paths."""
    result = copy.deepcopy(base)
    a, b = _indexed(left), _indexed(right)
    length = len(squeeze(base["text"]))
    if any(
        squeeze("".join(w["text"] for w in candidate["words"])) != squeeze(base["text"])
        for candidate in (left, right)
    ):
        return result
    if len(a) != length or len(b) != length:
        return result
    if not result["words"]:
        result["words"] = [
            dict(
                text=base["text"],
                start=base["start"],
                end=base["end"],
                speaker=None,
                candidates=[],
                needs_review=True,
                timing_valid=False,
            )
        ]
    output, cursor = [], 0
    for original in result["words"]:
        size = len(squeeze(original["text"]))
        can_reconsider = reconsider and any(
            min(original["end"], span["end"]) > max(original["start"], span["start"])
            for span in base["overlaps"]
        )
        if original["speaker"] not in (None, MULTIPLE_SPEAKERS) and not can_reconsider:
            output.append(original)
            cursor += size
            continue
        end = cursor + size
        while cursor < end:
            x, y = a[cursor], b[cursor]
            n = 1
            while cursor + n < end and a[cursor + n] is x and b[cursor + n] is y:
                n += 1
            accepted = (
                x["speaker"] not in (None, MULTIPLE_SPEAKERS)
                and x["speaker"] == y["speaker"]
                and x.get("timing_valid", True)
                and y.get("timing_valid", True)
                and abs(x["start"] - y["start"]) <= 0.5
                and abs(x["end"] - y["end"]) <= 0.5
            )
            word = dict(x if accepted else original)
            word["text"] = squeeze(base["text"])[cursor : cursor + n]
            if accepted:
                word["recovered"] = True
                if (
                    original["speaker"] not in (None, MULTIPLE_SPEAKERS)
                    and original["speaker"] != word["speaker"]
                ):
                    word["previous_speaker"] = original["speaker"]
                    word["needs_review"] = True
            output.append(word)
            cursor += n
    result["words"] = output
    result["alignment_available"] = any(w.get("timing_valid", False) for w in output)
    # Detection of simultaneous speech still requires human review even if recovered.
    result["needs_review"] = bool(result["overlaps"]) or any(w["needs_review"] for w in output)
    labels = {w["speaker"] for w in output}
    result["speaker"] = (
        next(iter(labels)) if len(labels) == 1 and not result["needs_review"] else base["speaker"]
    )
    return result


def whisperx_words(source, cues, language, device="cpu"):
    import whisperx

    model, metadata = whisperx.load_align_model(language_code=language, device=device)
    audio = whisperx.load_audio(str(source))
    results = []
    for cue in cues:
        result = whisperx.align(
            [dict(start=cue.start, end=cue.end, text=cue.text)],
            model,
            metadata,
            audio,
            device,
            interpolate_method="ignore",
            return_char_alignments=False,
        )
        results.append(
            [
                WordTiming(w["start"], w["end"], w["word"])
                for w in result["word_segments"]
                if "start" in w and "end" in w
            ]
        )
    return results


def recover_speaker_reviews(
    source, cues, turns, words, *, language, stage=3, device="cpu", audit_dir=None, reconsider=False
):
    base = review_speakers(cues, turns, words, stage=2)
    if not language or not any(r["needs_review"] for r in base):
        return base
    with tempfile.TemporaryDirectory(prefix="r4-speaker-recovery-") as tmp:
        if not reconsider:
            clean = Path(tmp) / "analysis.wav"
            subprocess.run(
                [
                    ffmpeg_binary(),
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-af",
                    "afftdn=nf=-25",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(clean),
                ],
                capture_output=True,
                check=True,
                timeout=600,
            )
            pending = [i for i, r in enumerate(base) if r["needs_review"]]
            selected = [cues[i] for i in pending]
            retry = align_speaker_words(clean, selected, language=language, device=device)
            phonemes = whisperx_words(source, selected, language, device)
            left = review_speakers(selected, turns, retry, stage=2)
            right = review_speakers(selected, turns, phonemes, stage=2)
            for i, first, second in zip(pending, left, right, strict=True):
                base[i] = merge_agreed(base[i], first, second)
        if stage >= 4 and any(r["overlaps"] for r in base):
            base = separated_reviews(
                source,
                cues,
                turns,
                base,
                language,
                Path(tmp),
                device,
                audit_dir=audit_dir,
                reconsider=reconsider,
            )
    return base


def separated_reviews(
    source, cues, turns, base, language, directory, device, *, audit_dir=None, reconsider=False
):
    """Experimental two-speaker recovery; no oracle stems or true labels used."""
    from difflib import SequenceMatcher

    import numpy as np
    import soundfile as sf
    import torch
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    from speechbrain.inference.separation import SepformerSeparation
    from speechbrain.inference.speaker import EncoderClassifier

    audit = {
        "schema": 1,
        "chunks": [],
        "cues": [],
        "status": "started",
        "model": "speechbrain/sepformer-whamr",
        "reconsider": reconsider,
    }

    def save_audit():
        if audit_dir is not None:
            Path(audit_dir).mkdir(parents=True, exist_ok=True)
            (Path(audit_dir) / "separation.json").write_text(
                json.dumps(audit, ensure_ascii=False, indent=2)
            )

    labels = sorted({t.speaker for t in turns})
    if len(labels) != 2:
        audit["status"] = "unsupported_speaker_count"
        save_audit()
        return base
    audio = decode_audio(str(source), sampling_rate=16000)
    encoder = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": device}
    )

    def embedding(x):
        with torch.no_grad():
            vector = encoder.encode_batch(torch.tensor(x).unsqueeze(0)).flatten().cpu().numpy()
        return vector / max(np.linalg.norm(vector), 1e-8)

    anchors = {}
    for label in labels:
        fragments = []
        for turn in turns:
            if turn.speaker != label:
                continue
            intervals = [(turn.start, turn.end)]
            for other in turns:
                if other.speaker == label:
                    continue
                next_intervals = []
                for a, b in intervals:
                    if other.end <= a or other.start >= b:
                        next_intervals.append((a, b))
                    else:
                        if a < other.start:
                            next_intervals.append((a, other.start))
                        if other.end < b:
                            next_intervals.append((other.end, b))
                intervals = next_intervals
            fragments.extend(
                audio[int(a * 16000) : int(b * 16000)] for a, b in intervals if b - a >= 0.5
            )
        if not fragments:
            audit["status"] = "missing_clean_anchor"
            save_audit()
            return base
        anchors[label] = embedding(np.concatenate(fragments))
    mixed = directory / "mixed8.wav"
    subprocess.run(
        [
            ffmpeg_binary(),
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "8000",
            str(mixed),
        ],
        check=True,
        capture_output=True,
    )
    separator = SepformerSeparation.from_hparams(
        source="speechbrain/sepformer-whamr", run_opts={"device": device}
    )
    # Bound separator attention memory and match the channel permutation in each
    # chunk to clean, non-overlapping voice anchors from this same recording.
    from scipy.signal import resample_poly

    mixture, rate = sf.read(mixed, dtype="float32")
    assert rate == 8000
    signals = np.zeros((len(mixture), 2), dtype=np.float32)
    chunk_size, padding = 4 * 8000, 4000
    for offset in range(0, len(mixture), chunk_size):
        begin, end = max(0, offset - padding), min(len(mixture), offset + chunk_size + padding)
        with torch.no_grad():
            chunk = separator.separate_batch(torch.tensor(mixture[begin:end]).unsqueeze(0))
        chunk = chunk.cpu().numpy()[0]
        vectors = [embedding(resample_poly(chunk[:, c], 2, 1).astype(np.float32)) for c in range(2)]
        direct = sum(float(np.dot(vectors[c], anchors[labels[c]])) for c in range(2))
        reverse = sum(float(np.dot(vectors[c], anchors[labels[1 - c]])) for c in range(2))
        order = [0, 1] if direct >= reverse else [1, 0]
        audit["chunks"].append(
            dict(
                start=offset / 8000,
                direct=direct,
                reverse=reverse,
                permutation_margin=abs(direct - reverse),
                order=order,
                channel_correlation=float(np.corrcoef(chunk.T)[0, 1])
                if np.all(np.std(chunk, axis=0) > 0)
                else None,
            )
        )
        save_audit()
        count = min(chunk_size, len(mixture) - offset)
        for channel, chosen in enumerate(order):
            signals[offset : offset + count, channel] = chunk[
                offset - begin : offset - begin + count, chosen
            ]
    asr = WhisperModel(
        "small", device=device, compute_type="int8" if device == "cpu" else "float16"
    )
    candidates = []
    for channel in range(2):
        path8 = directory / f"stem{channel}-8.wav"
        path = directory / f"stem{channel}.wav"
        sf.write(path8, signals[:, channel], 8000)
        subprocess.run(
            [ffmpeg_binary(), "-v", "error", "-y", "-i", str(path8), "-ar", "16000", str(path)],
            check=True,
            capture_output=True,
        )
        if audit_dir is not None:
            shutil.copy2(path, Path(audit_dir) / path.name)
        separated = decode_audio(str(path), sampling_rate=16000)
        aligned = whisperx_words(path, cues, language, device)
        reviews = review_speakers(cues, turns, aligned, stage=2)
        for cue_index, (cue, review) in enumerate(zip(cues, reviews, strict=True)):
            piece = separated[int(cue.start * 16000) : int(cue.end * 16000)]
            evidence = dict(
                channel=channel,
                cue=cue_index,
                start=cue.start,
                end=cue.end,
                reasons=[],
                accepted_words=0,
            )
            audit["cues"].append(evidence)
            if len(piece) < 8000:
                evidence["reasons"].append("too_short")
                save_audit()
                review["words"] = []
                continue
            vector = embedding(piece)
            scores = sorted(
                ((float(np.dot(vector, ref)), lab) for lab, ref in anchors.items()), reverse=True
            )
            segments, _ = asr.transcribe(piece, language=language, beam_size=5)
            actual = "".join(s.text for s in segments)
            similarity = SequenceMatcher(
                None, squeeze(actual).casefold(), squeeze(cue.text).casefold()
            ).ratio()
            evidence.update(
                voice_scores=scores,
                voice_margin=scores[0][0] - scores[1][0],
                text_similarity=similarity,
                recognized_text=actual,
            )
            if scores[0][0] < 0.6:
                evidence["reasons"].append("voice_match_below_threshold")
            if scores[0][0] - scores[1][0] < 0.15:
                evidence["reasons"].append("ambiguous_voice_identity")
            if similarity < 0.85:
                evidence["reasons"].append("transcript_mismatch")
            save_audit()
            if evidence["reasons"]:
                review["words"] = []
                continue
            # Independent stable-ts alignment on the same stem must agree in time.
            stable = align_speaker_words(path, [cue], language=language, device=device)[0]
            stable_review = review_speakers([cue], turns, [stable], stage=2)[0]
            for candidate in (review, stable_review):
                for word in candidate["words"]:
                    if word.get("timing_valid"):
                        word.update(
                            speaker=scores[0][1], needs_review=False, candidates=[scores[0][1]]
                        )
            unresolved = copy.deepcopy(review)
            unresolved["words"] = []
            accepted = merge_agreed(unresolved, review, stable_review)
            evidence["accepted_words"] = sum(
                w["speaker"] not in (None, MULTIPLE_SPEAKERS) for w in accepted["words"]
            )
            if not evidence["accepted_words"]:
                evidence["reasons"].append("alignment_disagreement_or_missing")
            save_audit()
            reviews[cue_index] = accepted
        candidates.append(reviews)
    # One stem alone is not enough when both claim the same text with different voices.
    for i, original in enumerate(base):
        a, b = candidates[0][i], candidates[1][i]
        available = [
            r
            for r in (a, b)
            if any(w["speaker"] not in (None, MULTIPLE_SPEAKERS) for w in r["words"])
        ]
        if len(available) == 1:
            base[i] = merge_agreed(
                original,
                available[0],
                available[0],
                reconsider=reconsider and bool(original["overlaps"]),
            )
        elif len(available) > 1:
            audit.setdefault("ambiguous_cues", []).append(i)
    audit["status"] = "completed"
    audit["changed_assignments"] = sum("previous_speaker" in w for r in base for w in r["words"])
    save_audit()
    return base
