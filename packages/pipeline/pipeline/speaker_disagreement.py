"""Compare anonymous diarizers without reference labels or changing assignments."""

import copy
import itertools
import math
from collections import Counter, defaultdict


def compare_turns(baseline, candidate, duration):
    if isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid duration")
    events = defaultdict(list)
    labels = []
    for side, turns in enumerate((baseline, candidate)):
        found = set()
        for turn in turns:
            a, b, label = turn["start"], turn["end"], turn["speaker"]
            if any(isinstance(x, bool) or not math.isfinite(x) for x in (a, b)):
                raise ValueError("Invalid time")
            if not 0 <= a < b <= duration or not isinstance(label, str) or not label:
                raise ValueError("Invalid turn")
            found.add(label)
            events[a].append((side, label, 1))
            events[b].append((side, label, -1))
        if len(found) > 8:
            raise ValueError("Comparison supports at most eight speakers per model")
        labels.append(sorted(found))
    events[0.0]
    events[duration]
    active = [Counter(), Counter()]
    timeline = []
    weights = defaultdict(float)
    times = sorted(events)
    for a, b in zip(times, times[1:], strict=False):
        for side, label, delta in events[a]:
            active[side][label] += delta
        left, right = ({lab for lab, count in x.items() if count > 0} for x in active)
        timeline.append((a, b, left, right))
        for x in left:
            for y in right:
                weights[x, y] += b - a
    # Maximum temporal agreement is only an anonymous ID correspondence, not
    # independent acoustic evidence. Tied/zero-weight pairs remain uncertain.
    n = max(map(len, labels))
    left = labels[0] + [None] * (n - len(labels[0]))
    right = labels[1] + [None] * (n - len(labels[1]))
    best = -1.0
    certain = set()
    for order in itertools.permutations(right):
        pairs = {
            (x, y) for x, y in zip(left, order, strict=False) if x is not None and y is not None
        }
        value = sum(weights[pair] for pair in pairs)
        if value > best + 1e-9:
            best, certain = value, pairs
        elif math.isclose(value, best, rel_tol=0, abs_tol=1e-9):
            certain &= pairs
    mapping = {y: x for x, y in certain if weights[x, y] > 0}
    intervals = []
    for a, b, left, right in timeline:
        reasons = []
        if left and not right:
            reasons.append("baseline_only_speech")
        elif right and not left:
            reasons.append("candidate_only_speech")
        elif left and right:
            if len(left) != len(right):
                reasons.append("speaker_count_disagreement")
            if any(y not in mapping for y in right):
                reasons.append("uncertain_speaker_correspondence")
            elif left != {mapping[y] for y in right}:
                reasons.append("speaker_assignment_disagreement")
        if not reasons:
            continue
        row = dict(
            start=a, end=b, reasons=reasons, overlap_suspected=max(len(left), len(right)) > 1
        )
        if (
            intervals
            and intervals[-1]["end"] == a
            and all(intervals[-1][key] == row[key] for key in ("reasons", "overlap_suspected"))
        ):
            intervals[-1]["end"] = b
        else:
            intervals.append(row)
    return dict(intervals=intervals, comparison_only=True, automatic_reassignment=False)


def mark_reviews(reviews, comparison):
    """Add review flags while preserving every word/speaker/timestamp and old flag."""
    result = copy.deepcopy(reviews)
    for cue in result:
        for row in [cue, *cue.get("words", [])]:
            row.pop("model_disagreement_reasons", None)
            hits = [
                span
                for span in comparison["intervals"]
                if max(row["start"], span["start"]) < min(row["end"], span["end"])
            ]
            if hits:
                row["needs_review"] = True
                row["model_disagreement_reasons"] = sorted(
                    {r for hit in hits for r in hit["reasons"]}
                )
    return result


def overlap_retry_windows(comparison, duration, context=0.5, max_seconds=30):
    """Only suspected overlap disagreements; context isn't counted as detected overlap."""
    if not 0 <= context < max_seconds / 2 or max_seconds <= 0:
        raise ValueError("Invalid retry window policy")
    merged = []
    for span in comparison["intervals"]:
        if not span["overlap_suspected"]:
            continue
        a, b = max(0, span["start"] - context), min(duration, span["end"] + context)
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    result = []
    for a, b in merged:
        while a < b:
            end = min(a + max_seconds, b)
            result.append(dict(start=a, end=end, needs_review=True, automatic_reassignment=False))
            a = end
    return result
