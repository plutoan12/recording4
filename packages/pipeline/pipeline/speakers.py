"""화자 구간을 자막에 붙이는 순수 계산.

화자 분리 자체는 워커의 WhisperX가 합니다. 여기서는 그 결과(화자 구간)와
대본(자막 구간)을 맞추는 규칙만 둡니다. 외부 의존성이 없어 테스트가 쉽습니다.
"""

from __future__ import annotations

import math
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass

from pipeline.editing import Cue


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """화자 한 명이 말한 구간. 화자 표시는 공급자가 준 이름 그대로입니다."""

    start: float
    end: float
    speaker: str

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("화자 구간 종료는 시작보다 뒤여야 합니다.")
        if not self.speaker:
            raise ValueError("화자 표시가 비어 있습니다.")


def _overlap(start: float, end: float, turn: SpeakerTurn) -> float:
    return max(0.0, min(end, turn.end) - max(start, turn.start))


def assign_speakers(cues: list[Cue], turns: list[SpeakerTurn]) -> list[str | None]:
    """자막마다 겹친 시간이 가장 긴 화자를 고릅니다.

    겹치는 화자가 없으면 `None`입니다. 추측해서 가까운 화자를 붙이지 않습니다.
    같은 시간이 겹치면 먼저 시작한 화자를 씁니다.
    """
    result: list[str | None] = []
    for cue in cues:
        best: tuple[float, float, str] | None = None
        for turn in turns:
            shared = _overlap(cue.start, cue.end, turn)
            if shared <= 0:
                continue
            candidate = (shared, -turn.start, turn.speaker)
            if best is None or candidate > best:
                best = candidate
        result.append(best[2] if best else None)
    return result


def speaker_totals(turns: list[SpeakerTurn]) -> dict[str, float]:
    """화자별 발화 시간 합. 어느 화자가 주 화자인지 화면에서 보여 줄 때 씁니다."""
    totals: dict[str, float] = {}
    for turn in turns:
        totals[turn.speaker] = totals.get(turn.speaker, 0.0) + (turn.end - turn.start)
    return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0])))


def windows(
    spans: list[tuple[float, float]], *, length: float = 1.5, hop: float = 0.75
) -> list[tuple[float, float]]:
    """발화 구간을 일정한 길이의 창으로 자릅니다.

    한 구간 안에서 화자가 바뀔 수 있습니다. 구간을 통째로 한 목소리로 보면
    그 경계를 영영 찾지 못합니다. 창은 겹치게 잡습니다. 경계가 창 한가운데
    걸리면 그 창은 두 목소리가 섞여 어느 쪽으로도 잘 안 묶이는데, 겹쳐 두면
    이웃 창이 온전한 목소리를 담습니다.

    구간이 창보다 짧으면 그 구간을 그대로 하나로 씁니다. 버리지 않습니다.
    """
    if length <= 0 or hop <= 0:
        raise ValueError("창 길이와 간격은 0보다 커야 합니다.")
    cut: list[tuple[float, float]] = []
    for begin, finish in spans:
        if finish - begin <= length:
            cut.append((begin, finish))
            continue
        start = begin
        while start < finish:
            end = min(start + length, finish)
            # 마지막 조각이 너무 짧으면 앞 창에 흡수시킵니다.
            if finish - end < hop and cut and cut[-1][1] > start:
                cut[-1] = (cut[-1][0], finish)
                break
            cut.append((start, end))
            if end >= finish:
                break
            start += hop
    return cut


def _unit(vector: list[float]) -> list[float]:
    size = sum(value * value for value in vector) ** 0.5
    return [value / size for value in vector] if size else list(vector)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def cluster(vectors: list[list[float]], count: int, *, rounds: int = 25) -> list[int]:
    """목소리 특징 벡터를 `count`개 묶음으로 나눕니다. 결과는 묶음 번호입니다.

    코사인 거리 k-평균입니다. 시작점은 무작위로 고르지 않고 서로 가장 먼
    벡터부터 차례로 고릅니다. 같은 음성을 두 번 재면 같은 답이 나와야
    검증에 쓸 수 있습니다.
    """
    if count < 1:
        raise ValueError("묶음 수는 1 이상이어야 합니다.")
    if not vectors:
        return []
    points = [_unit(v) for v in vectors]
    if count == 1 or len(points) <= count:
        return list(range(len(points))) if len(points) <= count else [0] * len(points)

    # 시작점은 이미 고른 것에서 가장 먼 점으로 차례로 잡습니다. 무작위로
    # 고르면 같은 음성을 두 번 재도 답이 달라집니다.
    centers = [points[0]]
    while len(centers) < count:
        centers.append(max(points, key=lambda p: min(1.0 - _cosine(p, c) for c in centers)))

    labels = [0] * len(points)
    for _ in range(rounds):
        moved = False
        for index, point in enumerate(points):
            best = max(range(count), key=lambda c: _cosine(point, centers[c]))
            if best != labels[index]:
                labels[index] = best
                moved = True
        for group in range(count):
            members = [p for p, label in zip(points, labels, strict=True) if label == group]
            if members:
                centers[group] = _unit([sum(values) for values in zip(*members, strict=True)])
        if not moved:
            break
    return labels


def turns_from_labels(
    spans: list[tuple[float, float]], labels: list[int], *, gap: float = 0.5
) -> list[SpeakerTurn]:
    """창과 묶음 번호를 화자 구간으로 합칩니다.

    같은 화자의 이웃 창은 하나로 잇습니다. 창을 겹쳐 잘랐으므로 이어 붙일 때
    겹친 부분은 자연히 사라집니다. `gap`보다 멀리 떨어지면 다른 구간입니다.
    """
    turns: list[SpeakerTurn] = []
    for (begin, finish), label in sorted(zip(spans, labels, strict=True), key=lambda item: item[0]):
        name = f"SPEAKER_{label:02d}"
        if turns and turns[-1].speaker == name and begin - turns[-1].end <= gap:
            turns[-1] = SpeakerTurn(
                start=turns[-1].start, end=max(turns[-1].end, finish), speaker=name
            )
            continue
        if finish > begin:
            turns.append(SpeakerTurn(start=begin, end=finish, speaker=name))
    return turns


MULTIPLE_SPEAKERS = "복수 화자"
_MAX_MATCHING_CELLS = 40_000


def _is_cjk_character(character: str) -> bool:
    name = unicodedata.name(character, "")
    return name.startswith(("CJK ", "HANGUL ")) or "HIRAGANA" in name or "KATAKANA" in name


def _is_text_boundary(text: str, index: int, whitespace_boundaries: set[int]) -> bool:
    """Keep Latin words whole while allowing timed CJK subwords.

    Aligners commonly return individual Han, kana, or Hangul pieces even when a
    caption author inserted spaces at phrase boundaries. Inside one Latin/digit
    word, including punctuation such as a hyphen or decimal point, only an
    original whitespace edge is accepted.
    """
    if index in whitespace_boundaries or index <= 0 or index >= len(text):
        return True
    left, right = text[index - 1], text[index]
    return _is_cjk_character(left) or _is_cjk_character(right)


def _matching_starts(
    text: str, tokens: list[str], whitespace_boundaries: set[int], enforce_boundaries: bool
) -> list[int | None]:
    """Find positions fixed across every maximum-character monotonic alignment."""

    # Imported captions can contain an unsegmented paragraph. The dynamic
    # matcher is deliberately conservative, so a pathological cue remains for
    # review instead of spending unbounded time or falling back to a guess.
    if len(text) * len(tokens) > _MAX_MATCHING_CELLS:
        return [None] * len(tokens)

    positions_by_token: dict[str, list[int]] = {}
    for token in set(tokens):
        positions = []
        if not token:
            positions_by_token[token] = positions
            continue
        begin = text.find(token)
        while begin >= 0:
            end = begin + len(token)
            if not enforce_boundaries or (
                _is_text_boundary(text, begin, whitespace_boundaries)
                and _is_text_boundary(text, end, whitespace_boundaries)
            ):
                positions.append(begin)
            begin = text.find(token, begin + 1)
        positions_by_token[token] = positions

    def occurrences(token: str, cursor: int):
        positions = positions_by_token[token]
        return positions[bisect_left(positions, cursor) :]

    # Keep the best prefix score for every reachable text cursor. Skipping a
    # token preserves the denominator while a match earns its character count.
    forward: list[dict[int, int]] = [{0: 0}]
    for token in tokens:
        next_scores: dict[int, int] = {}
        for cursor, score in forward[-1].items():
            next_scores[cursor] = max(next_scores.get(cursor, -1), score)
            for begin in occurrences(token, cursor):
                end = begin + len(token)
                next_scores[end] = max(next_scores.get(end, -1), score + len(token))
        forward.append(next_scores)

    suffix: list[dict[int, int]] = [{} for _ in range(len(tokens) + 1)]
    suffix[-1] = {cursor: 0 for cursor in forward[-1]}
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        for cursor in forward[index]:
            choices = [suffix[index + 1][cursor]]
            for begin in occurrences(token, cursor):
                end = begin + len(token)
                if end in suffix[index + 1]:
                    choices.append(len(token) + suffix[index + 1][end])
            suffix[index][cursor] = max(choices)

    optimum = suffix[0][0]
    starts: list[int | None] = []
    for index, token in enumerate(tokens):
        possible: set[int | None] = set()
        for cursor, prefix_score in forward[index].items():
            if prefix_score + suffix[index][cursor] != optimum:
                continue
            if prefix_score + suffix[index + 1][cursor] == optimum:
                possible.add(None)
            for begin in occurrences(token, cursor):
                end = begin + len(token)
                if (
                    end in suffix[index + 1]
                    and prefix_score + len(token) + suffix[index + 1][end] == optimum
                ):
                    possible.add(begin)
        starts.append(next(iter(possible)) if len(possible) == 1 and None not in possible else None)
    return starts


def review_speakers(cues, turns, words_by_cue, *, stage=2, minimum_word_coverage=0.0):
    """단어마다 근거가 있는 단일 화자만 배정합니다. 불확실하면 검수합니다."""
    from pipeline.alignment import squeeze

    if (
        isinstance(minimum_word_coverage, bool)
        or not isinstance(minimum_word_coverage, int | float)
        or not math.isfinite(minimum_word_coverage)
        or not 0 <= minimum_word_coverage <= 1
    ):
        raise ValueError("Invalid minimum word coverage")
    if len(cues) != len(words_by_cue):
        raise ValueError("대본과 단어 정렬 개수가 다릅니다.")
    reviewed = []
    for cue, words in zip(cues, words_by_cue, strict=True):
        candidates = sorted({t.speaker for t in turns if _overlap(cue.start, cue.end, t) > 0})
        overlaps = []
        relevant = [t for t in turns if _overlap(cue.start, cue.end, t) > 0]
        for index, left in enumerate(relevant):
            for right in relevant[index + 1 :]:
                begin, finish = (
                    max(cue.start, left.start, right.start),
                    min(cue.end, left.end, right.end),
                )
                if left.speaker != right.speaker and finish > begin:
                    overlaps.append({"start": begin, "end": finish})
        # Map only unambiguous exact text spans. Missing/invalid words stay in the
        # output so callers cannot accidentally count a smaller denominator.
        text = squeeze(cue.text)
        cursor = 0
        # Keep Latin words whole while allowing CJK aligners to return smaller
        # pieces than the spaces chosen by the caption author.
        boundaries = {0}
        edge = 0
        for token_text in cue.text.split():
            edge += len(squeeze(token_text))
            boundaries.add(edge)
        enforce_boundaries = len(cue.text.split()) > 1 or any(
            _is_cjk_character(character) for character in text
        )
        tokens = [squeeze(word.text) for word in words]
        starts = _matching_starts(text, tokens, boundaries, enforce_boundaries)
        assignments = []
        previous_end = cue.start
        for word, token, begin in zip(words, tokens, starts, strict=True):
            if not token or begin is None:
                continue
            if begin > cursor:
                assignments.append(
                    dict(
                        start=cue.start,
                        end=cue.end,
                        text=text[cursor:begin],
                        speaker=None,
                        candidates=[],
                        needs_review=True,
                        timing_valid=False,
                    )
                )
            valid_word = (
                cue.start <= word.start < word.end <= cue.end and word.start >= previous_end - 0.001
            )
            if valid_word:
                previous_end = word.end
            labels = sorted(
                {t.speaker for t in turns if valid_word and _overlap(word.start, word.end, t) > 0}
            )
            label = labels[0] if len(labels) == 1 else MULTIPLE_SPEAKERS if labels else None
            if stage >= 2 and len(labels) > 1:
                simultaneous = any(
                    min(word.end, o["end"]) > max(word.start, o["start"]) for o in overlaps
                )
                # A sequential boundary is not simultaneous speech. Require a
                # strong duration majority; ties and true overlaps remain unresolved.
                if not simultaneous:
                    spans = {lab: [] for lab in labels}
                    for turn in relevant:
                        if turn.speaker in spans and _overlap(word.start, word.end, turn) > 0:
                            spans[turn.speaker].append(
                                (max(word.start, turn.start), min(word.end, turn.end))
                            )
                    durations = {}
                    for lab, intervals in spans.items():
                        edge, duration = word.start, 0.0
                        for left, right in sorted(intervals):
                            duration += max(0.0, right - max(edge, left))
                            edge = max(edge, right)
                        durations[lab] = duration
                    best = max(durations, key=durations.get)
                    if durations[best] / (word.end - word.start) >= 0.8:
                        label = best
            # Opt-in experiment: a tiny intersection is insufficient for a whole word.
            # Do not relabel from neighbouring text or count duplicate tracks twice.
            if minimum_word_coverage and label not in (None, MULTIPLE_SPEAKERS):
                edge, covered = word.start, 0.0
                for left, right in sorted(
                    (max(word.start, t.start), min(word.end, t.end))
                    for t in relevant
                    if t.speaker == label and _overlap(word.start, word.end, t) > 0
                ):
                    covered += max(0.0, right - max(edge, left))
                    edge = max(edge, right)
                if covered / (word.end - word.start) < minimum_word_coverage:
                    label = None
            assignments.append(
                dict(
                    start=word.start if valid_word else cue.start,
                    end=word.end if valid_word else cue.end,
                    text=word.text,
                    speaker=label,
                    candidates=labels,
                    needs_review=label in (None, MULTIPLE_SPEAKERS),
                    timing_valid=valid_word,
                )
            )
            cursor = begin + len(token)
        if cursor < len(text):
            assignments.append(
                dict(
                    start=cue.start,
                    end=cue.end,
                    text=text[cursor:],
                    speaker=None,
                    candidates=[],
                    needs_review=True,
                    timing_valid=False,
                )
            )
        valid = any(w["timing_valid"] for w in assignments)
        resolved = {
            w["speaker"] for w in assignments if w["speaker"] not in (None, MULTIPLE_SPEAKERS)
        }
        needs_review = bool(overlaps) or not valid or any(w["needs_review"] for w in assignments)
        if valid and len(resolved) == 1 and not needs_review:
            label = next(iter(resolved))
        elif len(candidates) > 1 or len(resolved) > 1:
            label = MULTIPLE_SPEAKERS
        else:
            label = None
        reviewed.append(
            {
                "start": cue.start,
                "end": cue.end,
                "text": cue.text,
                "speaker": label,
                "candidates": candidates,
                "needs_review": needs_review or label == MULTIPLE_SPEAKERS,
                "alignment_available": bool(valid),
                "overlaps": overlaps,
                "words": assignments if valid else [],
            }
        )
    return reviewed
