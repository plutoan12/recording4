"""Add review-only target-ASR evidence without changing text, timings or speakers.

Target ASR is conditioned on diarization, so it is not independent voice evidence.
Phrase agreement must never be treated as permission to reassign automatically.
"""

import copy
import unicodedata
from difflib import SequenceMatcher


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
