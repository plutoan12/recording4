"""Add review-only target-ASR evidence without changing text, timings or speakers.

Target ASR is conditioned on diarization, so it is not independent voice evidence.
Phrase agreement must never be treated as permission to reassign automatically.
"""

import copy
import math
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

VOICE_MATCH_MINIMUM = 0.6
VOICE_MARGIN_MINIMUM = 0.15
VISUAL_ACTIVE_SPEAKER_MINIMUM = 0.7
VISUAL_SCORE_KIND = "calibrated_probability"
TIMING_TOLERANCE_SECONDS = 0.02
VOICE_METHODS = {"speaker_embedding", "human_voice_reference"}
VISUAL_METHODS = {"active_speaker_detection", "human_visual_review"}


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFC", text).casefold() if c.isalnum())


def propose_target_reviews(reviews, predictions, *, minimum_phrase=12):
    if minimum_phrase < 12:
        raise ValueError("Minimum phrase length cannot be weakened below 12")
    result = copy.deepcopy(reviews)
    for cue in result:
        if not cue["overlaps"]:
            continue
        # Character offsets must correspond to the actual aligned source words.
        source = "".join(normalized(w["text"]) for w in cue["words"])
        if source != normalized(cue["text"]):
            continue
        supports = [set() for _ in source]
        for prediction in predictions:
            hypothesis = normalized(prediction["hypothesis"])
            for block in SequenceMatcher(
                None, source, hypothesis, autojunk=False
            ).get_matching_blocks():
                phrase = source[block.a : block.a + block.size]
                if (
                    block.size < minimum_phrase
                    or source.find(phrase) != source.rfind(phrase)
                    or hypothesis.find(phrase) != hypothesis.rfind(phrase)
                ):
                    continue
                for i in range(block.a, block.a + block.size):
                    supports[i].add(prediction["target"])
        cursor = 0
        for word in cue["words"]:
            length = len(normalized(word["text"]))
            end = cursor + length
            labels = set.intersection(*supports[cursor:end]) if length else set()
            cursor = end
            if not word.get("timing_valid", False) or not any(
                min(word["end"], span["end"]) > max(word["start"], span["start"])
                for span in cue["overlaps"]
            ):
                continue
            if labels:
                word["target_asr_review"] = dict(
                    candidates=sorted(labels),
                    reason="ambiguous_target_text" if len(labels) > 1 else "target_text_match",
                    independent_voice_verified=False,
                    applied=False,
                )
                word["needs_review"] = True
                cue["needs_review"] = True
    return result


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"Invalid {name}")
    return float(value)


def _bounded_number(value, name, minimum, maximum):
    number = _finite_number(value, name)
    if not minimum <= number <= maximum:
        raise ValueError(f"Invalid {name}")
    return number


def _evidence_provenance(value, name):
    method = value.get("method")
    if method.startswith("human_"):
        reviewer = value.get("reviewer_id")
        reviewed_at = value.get("reviewed_at")
        if (
            not isinstance(reviewer, str)
            or not reviewer.strip()
            or not isinstance(reviewed_at, str)
        ):
            raise ValueError(f"Invalid {name} provenance")
        try:
            timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid {name} provenance") from exc
        if timestamp.tzinfo is None:
            raise ValueError(f"Invalid {name} provenance")
        return dict(method=method, reviewer_id=reviewer.strip(), reviewed_at=reviewed_at)
    revision = value.get("model_revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError(f"Invalid {name} provenance")
    provenance = dict(method=method, model_revision=revision.strip())
    if method == "active_speaker_detection":
        calibration_revision = value.get("calibration_revision")
        score_kind = value.get("score_kind")
        if isinstance(score_kind, str) and score_kind.strip():
            provenance["score_kind"] = score_kind.strip()
        if isinstance(calibration_revision, str) and calibration_revision.strip():
            provenance["calibration_revision"] = calibration_revision.strip()
    return provenance


def qualify_target_reviews(reviews, evidence, *, trusted_visual_calibrations=()):
    """Attach independent voice and visual support without changing assignments.

    Target-ASR text is conditioned on diarization.  A singleton text candidate is
    therefore only eligible for a later reassignment experiment when an acoustic
    identity check and an active-speaker check independently name the same target.
    This function records that eligibility; it never applies the candidate.
    """
    result = copy.deepcopy(reviews)
    try:
        trusted_visual_calibrations = list(trusted_visual_calibrations)
    except TypeError as exc:
        raise ValueError("Invalid trusted visual calibration") from exc
    if any(
        not isinstance(item, tuple)
        or len(item) != 2
        or not all(isinstance(value, str) and value for value in item)
        for item in trusted_visual_calibrations
    ):
        raise ValueError("Invalid trusted visual calibration")
    trusted_visual_calibrations = set(trusted_visual_calibrations)
    indexed = {}
    for row in evidence:
        if not isinstance(row, dict):
            raise ValueError("Invalid independent evidence")
        cue_index = row.get("cue_index")
        word_index = row.get("word_index")
        target = row.get("target")
        if (
            isinstance(cue_index, bool)
            or not isinstance(cue_index, int)
            or cue_index < 0
            or isinstance(word_index, bool)
            or not isinstance(word_index, int)
            or word_index < 0
            or not isinstance(target, str)
            or not target
        ):
            raise ValueError("Invalid independent evidence location")
        if cue_index >= len(result) or word_index >= len(result[cue_index].get("words", [])):
            raise ValueError("Independent evidence location is outside the review")
        word = result[cue_index]["words"][word_index]
        start = _finite_number(row.get("start"), "evidence start")
        end = _finite_number(row.get("end"), "evidence end")
        if (
            end <= start
            or abs(start - _finite_number(word.get("start"), "word start"))
            > TIMING_TOLERANCE_SECONDS
            or abs(end - _finite_number(word.get("end"), "word end")) > TIMING_TOLERANCE_SECONDS
            or normalized(row.get("text", "")) != normalized(word.get("text", ""))
        ):
            raise ValueError("Independent evidence does not match the reviewed word")
        key = (cue_index, word_index, target)
        if key in indexed:
            raise ValueError("Duplicate independent evidence")
        indexed[key] = row

    consumed = set()
    for cue_index, cue in enumerate(result):
        for word_index, word in enumerate(cue.get("words", [])):
            review = word.get("target_asr_review")
            if not review:
                continue
            if review.get("applied") is True:
                raise ValueError("Applied target review cannot be requalified")
            consumed.update(key for key in indexed if key[:2] == (cue_index, word_index))
            candidates = review.get("candidates", [])
            review.pop("voice_provenance", None)
            review.pop("visual_provenance", None)
            review.update(
                independent_voice_verified=False,
                independent_visual_verified=False,
                qualified_for_reassignment=False,
                applied=False,
            )
            reasons = []
            if len(candidates) != 1:
                reasons.append("ambiguous_target_text")
            else:
                target = candidates[0]
                row = indexed.get((cue_index, word_index, target))
                conflicting = [
                    key[2]
                    for key in indexed
                    if key[:2] == (cue_index, word_index) and key[2] != target
                ]
                if conflicting:
                    reasons.append("independent_target_conflict")
                if row is None:
                    reasons.append("missing_independent_evidence")
                else:
                    voice = row.get("voice")
                    visual = row.get("visual")
                    if not isinstance(voice, dict) or voice.get("method") not in VOICE_METHODS:
                        reasons.append("invalid_voice_provenance")
                    else:
                        review["voice_provenance"] = _evidence_provenance(voice, "voice")
                        match = _bounded_number(voice.get("match"), "voice match", -1, 1)
                        margin = _bounded_number(voice.get("margin"), "voice margin", 0, 2)
                        if match < VOICE_MATCH_MINIMUM:
                            reasons.append("voice_match_below_threshold")
                        if margin < VOICE_MARGIN_MINIMUM:
                            reasons.append("ambiguous_voice_identity")
                        if match >= VOICE_MATCH_MINIMUM and margin >= VOICE_MARGIN_MINIMUM:
                            review["independent_voice_verified"] = True
                    if not isinstance(visual, dict) or visual.get("method") not in VISUAL_METHODS:
                        reasons.append("invalid_visual_provenance")
                    else:
                        review["visual_provenance"] = _evidence_provenance(visual, "visual")
                        active = _finite_number(
                            visual.get("active_speaker_score"), "active speaker score"
                        )
                        if visual.get("method") == "active_speaker_detection":
                            visual_provenance = review["visual_provenance"]
                            score_kind = visual_provenance.get("score_kind")
                            if score_kind == VISUAL_SCORE_KIND:
                                active = _bounded_number(active, "active speaker score", 0, 1)
                            calibration = (
                                visual_provenance.get("model_revision"),
                                visual_provenance.get("calibration_revision"),
                            )
                            calibration_trusted = (
                                score_kind == VISUAL_SCORE_KIND
                                and calibration in trusted_visual_calibrations
                            )
                            if not calibration_trusted:
                                reasons.append("untrusted_visual_calibration")
                            if (
                                score_kind == VISUAL_SCORE_KIND
                                and active < VISUAL_ACTIVE_SPEAKER_MINIMUM
                            ):
                                reasons.append("visual_speaker_below_threshold")
                            elif calibration_trusted:
                                review["independent_visual_verified"] = True
                        else:
                            active = _bounded_number(active, "active speaker score", 0, 1)
                            if active < VISUAL_ACTIVE_SPEAKER_MINIMUM:
                                reasons.append("visual_speaker_below_threshold")
                            else:
                                review["independent_visual_verified"] = True
                    voice_provenance = review.get("voice_provenance", {})
                    visual_provenance = review.get("visual_provenance", {})
                    if (
                        voice_provenance.get("method", "").startswith("human_")
                        and visual_provenance.get("method", "").startswith("human_")
                        and voice_provenance.get("reviewer_id")
                        == visual_provenance.get("reviewer_id")
                    ):
                        reasons.append("human_evidence_not_independent")
            review["qualification_reasons"] = reasons
            review["qualified_for_reassignment"] = not reasons
            word["needs_review"] = True
            cue["needs_review"] = True
    if set(indexed) != consumed:
        raise ValueError("Independent evidence has no target-ASR proposal")
    return result
