"""숏폼으로 쓸 만한 구간 추천. 장면 경계와 발화 구간만 보고 점수를 매깁니다.

**`pipeline.highlights`와 다른 것입니다.** 그쪽은 대본을 LLM에게 보여 주고
고르게 합니다(유료, 무엇이 재미있는지를 봅니다). 이쪽은 망을 타지 않고
장면 경계와 말이 찬 정도만 봅니다(무료, 모양만 봅니다). 둘은 같은 모양의
후보를 내놓으므로 나란히 놓고 비교할 수 있습니다.

PySceneDetect는 이미 붙어 있었지만 **장면 경계를 내놓는 데서 끝났습니다.**
사람이 그 목록을 보고 직접 구간을 골라야 했습니다. 이 모듈은 그 경계와
발화 구간(`worker.analysis.speech_spans`)을 합쳐 "여기를 잘라 보세요"까지
갑니다.

## 무엇을 보는가

| 신호 | 왜 | 비중 |
|---|---|---|
| 말이 차 있는 비율 | 숏폼은 말이 끊기면 바로 넘깁니다. 빈 화면이 적어야 합니다. | 0.60 |
| 장면 전환 빈도 | 화면이 바뀌면 덜 지루합니다. 다만 너무 잦으면 정신없습니다. | 0.25 |
| 영상에서의 자리 | 맨 앞(인사)과 맨 뒤(마무리)는 대체로 알맹이가 아닙니다. | 0.15 |

**비중은 잰 값이 아니라 정한 값입니다.** 조회수로 검증한 적이 없습니다.
순위를 매기는 데 쓰는 것이지 "이 구간이 좋다"는 근거가 아닙니다.

## 규칙

- 후보는 **장면 경계에서 시작하고 장면 경계에서 끝납니다.** 말 중간이나
  화면 중간에서 시작하면 잘린 느낌이 납니다.
- 길이가 `minimum`~`maximum` 밖이면 버리고, `target`에 가까울수록 좋습니다.
- 겹치는 후보는 점수가 높은 쪽만 남깁니다.
- 장면 경계가 없으면(전환이 없는 영상) `target` 간격으로 잘라 후보를 만듭니다.
- **말이 거의 없는 구간은 후보로 보지 않습니다.** 이 추천은 말하는 영상
  기준이라 음악·풍경 영상에서는 아무것도 내놓지 않습니다.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

Span = tuple[float, float]

# 비중. 셋을 더하면 1입니다.
SPEECH_WEIGHT = 0.60
VARIETY_WEIGHT = 0.25
PLACE_WEIGHT = 0.15
# 1분에 이만큼 전환하면 충분히 활기차다고 봅니다. 그 위로는 더 쳐주지 않습니다.
LIVELY_CUTS_PER_MINUTE = 6.0
# 앞뒤 이만큼은 인사·마무리로 보고 점수를 깎습니다.
EDGE_RATIO = 0.1
# 이 점수 아래는 추천하지 않습니다.
FLOOR = 0.25
# 말이 이만큼도 차 있지 않으면 후보로 보지 않습니다. 이 추천은 **말하는
# 영상** 기준입니다. 음악·풍경 영상에서는 아무것도 추천하지 않습니다.
MIN_SPEECH = 0.35


class Highlight(BaseModel):
    """추천 구간 하나. 왜 골랐는지 숫자와 함께 돌려줍니다."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    score: float = Field(ge=0, le=1)
    speech_ratio: float = Field(ge=0, le=1)
    scene_cuts: int = Field(ge=0)

    @property
    def seconds(self) -> float:
        return self.end - self.start


def covered(window: Span, spans: Sequence[Span]) -> float:
    """구간 안에서 `spans`가 차지하는 시간."""
    start, end = window
    return sum(max(0.0, min(end, high) - max(start, low)) for low, high in spans)


def _boundaries(scenes: Sequence[dict], duration: float, target: float) -> list[float]:
    """후보가 시작·끝날 수 있는 시각. 장면이 없으면 일정 간격으로 만듭니다."""
    found = {0.0, duration}
    for scene in scenes:
        for key in ("start", "end"):
            value = float(scene[key])
            if 0.0 <= value <= duration:
                found.add(value)
    if len(found) <= 2 and target > 0:
        step = target / 2
        found.update(step * at for at in range(1, int(duration / step) + 1))
    return sorted(found)


def _place(window: Span, duration: float) -> float:
    """영상에서의 자리 점수. 맨 앞·맨 뒤일수록 깎습니다."""
    if duration <= 0:
        return 1.0
    edge = duration * EDGE_RATIO
    start, end = window
    if start >= edge and end <= duration - edge:
        return 1.0
    outside = max(0.0, edge - start) + max(0.0, end - (duration - edge))
    return max(0.0, 1.0 - outside / max(edge, 1e-6))


def _fit(seconds: float, target: float) -> float:
    """길이가 목표에 얼마나 가까운지. 1에 가까울수록 좋습니다."""
    if target <= 0:
        return 1.0
    return max(0.0, 1.0 - abs(seconds - target) / target)


def suggest(
    scenes: Sequence[dict],
    speech: Sequence[Span],
    *,
    duration: float,
    target: float = 45.0,
    minimum: float = 15.0,
    maximum: float = 90.0,
    count: int = 5,
    floor: float = FLOOR,
) -> list[Highlight]:
    """점수가 높은 순으로 겹치지 않는 후보 구간을 돌려줍니다."""
    if duration <= 0 or count <= 0:
        return []
    edges = _boundaries(scenes, duration, target)
    cuts = sorted(
        {float(scene["start"]) for scene in scenes if 0.0 < float(scene["start"]) < duration}
    )
    found: list[Highlight] = []
    for at, start in enumerate(edges):
        for end in edges[at + 1 :]:
            seconds = end - start
            if seconds < minimum:
                continue
            if seconds > maximum:
                break
            ratio = covered((start, end), speech) / seconds
            if ratio < MIN_SPEECH:
                continue
            inside = sum(1 for cut in cuts if start < cut < end)
            variety = min(inside / (seconds / 60 * LIVELY_CUTS_PER_MINUTE), 1.0) if seconds else 0.0
            score = (
                SPEECH_WEIGHT * ratio
                + VARIETY_WEIGHT * variety
                + PLACE_WEIGHT * _place((start, end), duration)
            ) * _fit(seconds, target)
            found.append(
                Highlight(
                    start=start,
                    end=end,
                    score=round(min(1.0, score), 4),
                    speech_ratio=round(min(1.0, ratio), 4),
                    scene_cuts=inside,
                )
            )
    chosen: list[Highlight] = []
    for item in sorted(found, key=lambda h: (-h.score, h.start)):
        if item.score < floor:
            break
        if any(item.start < other.end and other.start < item.end for other in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda h: h.start)
