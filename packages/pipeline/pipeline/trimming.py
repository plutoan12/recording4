"""무음 자동 컷. 말이 없는 구간을 빼고 남은 토막을 이어 붙입니다.

Auto-Editor가 하는 일을 우리 구조 안에서 합니다. **찾는 쪽은 이미 있었습니다**
(`worker.analysis.speech_spans`: Silero VAD, 실패하면 FFmpeg `silencedetect`).
없던 것은 **자르는 쪽**입니다. 구간 하나만 뽑던 `EditSpec`에 "여러 토막을
남기고 나머지는 버린다"를 더합니다.

## 무엇이 어려운가

자르고 나면 **시간축이 달라집니다.** 원본 12.0초의 말이 잘린 뒤에는 8.4초일
수 있습니다. 그래서 자막·단어 시각·스티커를 모두 새 시간축으로 옮겨야 하고,
옮기지 않으면 화면의 글자가 말과 어긋납니다. 이 모듈은 그 계산만 합니다.
실제 FFmpeg 호출은 `worker.rendering`이 합니다.

## 규칙

- 말 앞뒤로 `pad`만큼은 남깁니다. 딱 붙여 자르면 첫 소리가 잘립니다.
- `min_gap`보다 짧은 침묵은 **자르지 않습니다.** 숨 쉬는 자리까지 없애면
  말이 붙어 듣기 나쁩니다.
- `min_keep`보다 짧은 토막은 버립니다. 한 프레임짜리 조각이 남지 않게.
- 토막 수에 상한을 둡니다(`MAX_SEGMENTS`). 넘으면 **가장 짧은 침묵부터**
  도로 붙입니다. FFmpeg 필터 문자열이 끝없이 길어지지 않게 하려는 것입니다.
- **말을 하나도 못 찾으면 아무것도 자르지 않습니다.** 빈 영상을 내놓느니
  원본 그대로가 낫습니다.
"""

from __future__ import annotations

from collections.abc import Sequence

from pipeline.editing import Cue, TrimSettings, Word

Span = tuple[float, float]

# 필터 문자열이 감당할 수 있는 토막 수. 넘으면 짧은 침묵부터 도로 붙입니다.
MAX_SEGMENTS = 200
# 이보다 짧게 겹치는 전환은 눈에 띄지도 않으면서 계산만 복잡해집니다.
MIN_OVERLAP = 0.05


def _merge(spans: list[Span], gap: float) -> list[Span]:
    """겹치거나 `gap`보다 가까운 토막을 하나로 붙입니다."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] < gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _cap(spans: list[Span], limit: int) -> list[Span]:
    """토막 수를 상한 아래로 줄입니다. 가장 짧은 침묵부터 도로 붙입니다."""
    while len(spans) > limit:
        gaps = [spans[at + 1][0] - spans[at][1] for at in range(len(spans) - 1)]
        at = gaps.index(min(gaps))
        spans[at : at + 2] = [(spans[at][0], spans[at + 1][1])]
    return spans


def keeps(
    speech: Sequence[Span],
    *,
    start: float,
    end: float,
    settings: TrimSettings | None = None,
) -> list[Span]:
    """남길 토막. 구간 시작을 0으로 둔 새 시간축이 아니라 **구간 상대 시간**입니다.

    돌려주는 값이 `[(0, end - start)]` 하나뿐이면 자를 것이 없다는 뜻입니다.
    """
    settings = settings or TrimSettings()
    length = end - start
    whole = [(0.0, length)]
    if length <= 0:
        return whole
    inside = [
        (max(a, start) - start, min(b, end) - start) for a, b in speech if b > start and a < end
    ]
    if not inside:
        # 말을 하나도 못 찾았습니다. 빈 영상을 내놓느니 그대로 둡니다.
        return whole
    padded = [(max(0.0, a - settings.pad), min(length, b + settings.pad)) for a, b in inside]
    kept = [
        span for span in _merge(padded, settings.min_gap) if span[1] - span[0] >= settings.min_keep
    ]
    if not kept:
        return whole
    return _cap(kept, MAX_SEGMENTS)


def overlap_seconds(kept: Sequence[Span], wanted: float) -> float:
    """실제로 쓸 전환 길이. 토막보다 길게 겹칠 수는 없습니다.

    xfade는 두 토막을 `duration`만큼 겹칩니다. 토막이 그보다 짧으면 FFmpeg가
    거부하므로 **가장 짧은 토막의 절반**까지로 줄입니다. 그래도 너무 짧으면
    0을 돌려주고, 부르는 쪽은 전환 없이 딱 붙입니다.
    """
    # 겹칠 이음매가 있어야 전환입니다. 토막이 하나면 이을 자리가 없습니다.
    if len(kept) < 2 or wanted <= 0:
        return 0.0
    shortest = min(end - start for start, end in kept)
    usable = min(wanted, shortest / 2)
    return usable if usable >= MIN_OVERLAP else 0.0


def kept_seconds(kept: Sequence[Span], overlap: float = 0.0) -> float:
    """자른 뒤 남는 길이. 전환을 넣으면 겹친 만큼 짧아집니다."""
    total = sum(end - start for start, end in kept)
    return total - max(0, len(kept) - 1) * overlap


def _offset(index: int, kept: Sequence[Span], overlap: float) -> float:
    """토막 `index`의 내용이 결과 영상에서 시작하는 시각."""
    return sum(end - start for start, end in kept[:index]) - index * overlap


def trims(kept: Sequence[Span], length: float) -> bool:
    """실제로 잘라 내는 것이 있는지.

    **토막 수로 세면 안 됩니다.** 말이 가운데 한 군데만 있으면 토막은 하나뿐인데
    앞뒤 침묵은 잘라야 합니다. 남는 길이가 원래보다 짧은지로 봅니다.
    """
    return kept_seconds(kept) < length - 1e-6


def moved(time: float, kept: Sequence[Span], overlap: float = 0.0) -> float | None:
    """원본(구간 상대) 시각을 자른 뒤의 시각으로. 잘려 나간 자리면 `None`.

    전환을 넣으면 토막끼리 겹치므로 **자기 토막 기준**으로 옮깁니다. 겹치는
    구간에서는 두 토막이 한 화면에 함께 있지만 글자는 한쪽을 따릅니다.
    """
    for index, (start, end) in enumerate(kept):
        if time < start:
            return None
        if time <= end:
            return _offset(index, kept, overlap) + (time - start)
    return None


def _pieces(start: float, end: float, kept: Sequence[Span], overlap: float = 0.0) -> list[Span]:
    """[start, end]가 남은 토막과 겹치는 부분을 새 시간축으로 옮깁니다."""
    found: list[Span] = []
    for index, (low, high) in enumerate(kept):
        lower, upper = max(start, low), min(end, high)
        if upper > lower:
            base = _offset(index, kept, overlap)
            found.append((base + lower - low, base + upper - low))
    return found


def moved_words(
    words: Sequence[Word] | None, kept: Sequence[Span], overlap: float = 0.0
) -> list[Word] | None:
    """단어 시각을 옮깁니다. 한 단어라도 잘려 나갔으면 **전부 버립니다.**

    글자와 맞지 않는 단어 시각은 노래방·단어별 등장을 어긋나게 합니다.
    `pipeline.editing._clip_words`와 같은 판단입니다.
    """
    if not words:
        return None
    output: list[Word] = []
    for word in words:
        start, end = moved(word.start, kept, overlap), moved(word.end, kept, overlap)
        if start is None or end is None or end <= start:
            return None
        output.append(Word(start=start, end=end, text=word.text))
    return output


def moved_span(start: float, end: float, kept: Sequence[Span], overlap: float = 0.0) -> Span | None:
    """구간 하나를 새 시간축으로. 통째로 잘려 나갔으면 `None`입니다."""
    found = _pieces(start, end, kept, overlap)
    if not found:
        return None
    low, high = found[0][0], found[-1][1]
    return (low, high) if high > low else None


def moved_cues(cues: Sequence[Cue], kept: Sequence[Span], overlap: float = 0.0) -> list[Cue]:
    """자막을 새 시간축으로 옮깁니다. 통째로 잘려 나간 자막은 버립니다.

    한 자막이 잘린 자리를 걸치면 남은 부분의 **처음부터 끝까지**로 둡니다.
    그 사이에 이어 붙은 다른 말이 들어가지만, 자막을 쪼개면 글자도 쪼개야
    하므로 그렇게 하지 않습니다. 말이 있는 곳만 남기므로 자막이 걸치는
    경우 자체가 드뭅니다.
    """
    output: list[Cue] = []
    for cue in sorted(cues, key=lambda c: c.start):
        found = _pieces(cue.start, cue.end, kept, overlap)
        if not found:
            continue
        start, end = found[0][0], found[-1][1]
        if end <= start:
            continue
        output.append(
            Cue(start=start, end=end, text=cue.text, words=moved_words(cue.words, kept, overlap))
        )
    return output


def select_expression(kept: Sequence[Span]) -> str:
    """FFmpeg `select`/`aselect`에 넣을 식.

    값이 0이 아니면 그 프레임을 남깁니다. `between()`이 0 또는 1이므로
    더하기가 곧 "또는"입니다.
    """
    return "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in kept)
