"""문맥 배치. 한 문장이 여러 자막으로 잘려 있으면 **합쳐서** 번역합니다.

## 무엇을 고치는가

자막은 말하는 속도에 맞춰 잘립니다. 특히 숏폼 끊기를 쓰면 한 문장이 서너
조각으로 나뉩니다. 지금까지는 그 조각을 **따로따로** 번역했습니다.

    "그래서 저는"        → "So I am"
    "어제 그 자료를"     → "that material yesterday"
    "다시 만들었습니다"  → "I made it again"

조각만 보면 번역기가 주어도 시제도 알 수 없습니다. 합쳐서 한 문장으로
번역하면 "So I rebuilt that material yesterday."가 나옵니다.

## 어떻게 하는가

1. 이어지는 조각을 **한 문장**으로 묶습니다(앞 조각이 문장부호로 끝나지
   않았으면 같은 문장으로 봅니다).
2. 묶은 문장을 **한 번에** 번역합니다.
3. 번역문을 원래 조각 수만큼 **다시 나눕니다.** 각 조각이 차지하던 시간에
   비례해 폭을 나누고 낱말 경계에서 자릅니다.

**글자 수가 늘지 않으므로 번역 요금도 늘지 않습니다.** 구분 표시를 끼워
넣는 방법(조각마다 태그 7자 이상)을 택하지 않은 이유입니다.

## 아는 한계

- 다시 나눈 자리는 **말한 자리와 정확히 맞지 않습니다.** 한국어와 영어는
  어순이 달라 "지금 말하는 낱말"이 같은 조각에 오지 않습니다. 다만 이것은
  조각을 따로 번역할 때도 마찬가지였고, 그때는 문장 자체가 틀렸습니다.
- 그래서 **더빙에는 쓰지 않습니다.** 더빙은 조각별 글이 곧 그 구간의
  발화라 문장을 다시 나누면 말이 어긋납니다. 자막 경로에만 씁니다.
- 낱말 수가 조각 수보다 적으면 나눌 수 없습니다. 그때는 묶지 않고
  지금까지처럼 조각별로 번역합니다(조용히 되돌아갑니다).
- 문장 끝을 문장부호로만 판단합니다. 전사에 문장부호가 없으면 한 문장으로
  묶이지 않고 지금과 같아집니다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import accumulate

from pipeline.subtitles import text_width

# 한 문장이 끝났다고 볼 문장부호. 닫는 따옴표·괄호는 뒤에 붙을 수 있습니다.
SENTENCE_END = tuple(".!?…。！？")
CLOSERS = "\"'”’)]》」』"
# 한 묶음의 상한. 넘치면 잘라서 다음 묶음으로 넘깁니다. 묶음이 크면 다시
# 나눌 때 어긋나는 폭도 커지고, 한 번 실패했을 때 잃는 것도 많아집니다.
MAX_CUES = 6
MAX_CHARS = 400
# 띄어쓰기가 없는 언어. 조각을 이을 때 공백을 넣지 않습니다.
NO_SPACES = ("ja", "zh", "th", "lo", "my")
# 문장 경계를 믿으려면 이만큼은 문장부호로 끝나야 합니다. 전사에 문장부호가
# 거의 없으면 어디서 문장이 끝나는지 알 수 없고, 그때 묶으면 **서로 다른
# 문장을 붙여** 번역하게 됩니다. 조각별 번역보다 나쁩니다. 그래서 그런
# 대본은 묶지 않고 지금까지처럼 조각별로 번역합니다.
# 이 값은 잰 것이 아니라 정한 것입니다.
MIN_SENTENCE_RATE = 0.15


def ends_sentence(text: str) -> bool:
    """이 조각에서 문장이 끝났는지."""
    return text.rstrip().rstrip(CLOSERS).endswith(SENTENCE_END)


def punctuated(texts: Sequence[str]) -> bool:
    """문장 경계를 믿을 만큼 문장부호가 있는지.

    전사가 문장부호를 거의 내지 않는 대본에서 묶으면 서로 다른 문장을 붙여
    번역하게 됩니다. 그런 대본은 묶지 않습니다.
    """
    if not texts:
        return False
    return sum(map(ends_sentence, texts)) / len(texts) >= MIN_SENTENCE_RATE


def groups(texts: Sequence[str]) -> list[list[int]]:
    """이어지는 조각을 문장 단위로 묶습니다. 값은 자리 번호입니다.

    혼자 남은 조각도 크기 1인 묶음으로 나옵니다(그대로 번역됩니다). 문장부호가
    거의 없는 대본은 아예 묶지 않고 조각마다 한 묶음으로 돌려줍니다.
    """
    if not punctuated(texts):
        return [[index] for index in range(len(texts))]
    found: list[list[int]] = []
    current: list[int] = []
    size = 0
    for index, text in enumerate(texts):
        too_big = len(current) >= MAX_CUES or size + len(text) > MAX_CHARS
        if current and too_big:
            found.append(current)
            current, size = [], 0
        current.append(index)
        size += len(text)
        if ends_sentence(text):
            found.append(current)
            current, size = [], 0
    if current:
        found.append(current)
    return found


def join(texts: Sequence[str], language: str | None) -> str:
    """묶은 조각을 한 문장으로 잇습니다."""
    separator = "" if (language or "").split("-")[0] in NO_SPACES else " "
    return separator.join(text.strip() for text in texts if text.strip())


def _units(text: str, count: int, language: str | None) -> list[str] | None:
    """나눌 최소 단위.

    낱말(뒤 공백 포함)로 나눕니다. 띄어쓰기가 없는 언어만 글자로 나눕니다.
    낱말이 모자란데 글자로 쪼개면 단어가 두 자막에 걸쳐 잘리므로, 그때는
    나누기를 포기하고(`None`) 부르는 쪽이 조각별 번역으로 돌아갑니다.
    """
    words = re.findall(r"\S+\s*", text)
    if len(words) >= count:
        return words
    if (language or "").split("-")[0] not in NO_SPACES:
        return None
    letters = list(text)
    return letters if len(letters) >= count else None


def split_across(text: str, weights: Sequence[float], language: str | None) -> list[str] | None:
    """번역문을 조각 수만큼 나눕니다. 각 조각이 쓰던 시간에 비례합니다.

    나눌 수 없으면(낱말이 모자라거나 빈 조각이 생기면) `None`입니다. 부르는
    쪽은 그때 묶지 말고 조각별로 번역해야 합니다.
    """
    count = len(weights)
    if count < 1 or not text.strip():
        return None
    if count == 1:
        return [text.strip()]
    units = _units(text, count, language)
    if units is None:
        return None
    widths = [text_width(unit) for unit in units]
    total, scale = sum(widths), sum(weights)
    if total <= 0 or scale <= 0:
        return None
    reached = list(accumulate(widths))
    shares = list(accumulate(weight / scale for weight in weights[:-1]))

    cuts: list[int] = []
    previous = 0
    for index, share in enumerate(shares):
        bound = share * total
        lowest = previous + 1  # 이 조각에 적어도 하나
        highest = len(units) - (count - index - 1)  # 뒤 조각들 몫을 남깁니다
        cut = next((at + 1 for at, seen in enumerate(reached) if seen >= bound), highest)
        previous = min(max(cut, lowest), highest)
        cuts.append(previous)
    edges = [0, *cuts, len(units)]
    spans = zip(edges, edges[1:], strict=False)
    pieces = ["".join(units[start:end]).strip() for start, end in spans]
    return pieces if all(pieces) else None
