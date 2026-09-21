"""세로 화면으로 자를 때 어디를 남길지 정하는 계산.

가로 영상을 9:16으로 자르면 가로의 대부분이 잘려 나갑니다. 지금은 사람이
`focus_x` 손잡이를 눈으로 맞춥니다. 여기서는 찾아낸 얼굴 위치로 **제안값**을
만듭니다. 정하는 것은 여전히 사람입니다.

순수 계산만 둡니다. 얼굴을 찾는 일은 `worker.faces`가 합니다. 나누는 이유는
검출기 없이도 이 규칙을 시험할 수 있어야 하기 때문입니다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 제안을 내놓으려면 이 비율 이상의 표본에서 얼굴이 보여야 합니다. 몇 장에서만
# 보인 얼굴로 화면을 옮기면 대부분의 시간에 엉뚱한 곳을 비춥니다.
MIN_COVERAGE = 0.30


@dataclass(frozen=True, slots=True)
class Box:
    """찾아낸 얼굴 하나. 픽셀 좌표입니다."""

    x: float
    y: float
    width: float
    height: float

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


@dataclass(frozen=True, slots=True)
class Suggestion:
    """제안값과 그 근거. 근거 없이 숫자만 주면 믿을지 말지 알 수 없습니다."""

    focus_x: float
    samples: int
    found: int
    spread: float
    reason: str

    @property
    def coverage(self) -> float:
        return self.found / self.samples if self.samples else 0.0


def biggest(boxes: list[Box]) -> Box | None:
    """한 장에서 가장 큰 얼굴. 말하는 사람이 보통 가장 크게 잡힙니다."""
    return max(boxes, key=lambda b: b.area) if boxes else None


def middle(values: list[float]) -> float:
    """가운뎃값. 평균은 한 장의 오검출에 끌려갑니다."""
    ordered = sorted(values)
    count = len(ordered)
    if not count:
        raise ValueError("값이 없습니다.")
    half = count // 2
    return ordered[half] if count % 2 else (ordered[half - 1] + ordered[half]) / 2


def suggest_focus(frames: list[list[Box]], width: int) -> Suggestion:
    """표본 프레임들의 얼굴 위치로 `focus_x` 제안을 만듭니다.

    규칙은 세 가지입니다.

    1. 한 장에서 **가장 큰 얼굴** 하나만 씁니다. 뒤에 지나가는 사람까지 세면
       가운데로 끌려갑니다.
    2. 여러 장의 **가운뎃값**을 씁니다. 평균은 한 장의 오검출에 끌려갑니다.
    3. 얼굴이 보인 장이 너무 적거나(`MIN_COVERAGE` 미만) 위치가 너무
       흔들리면 **제안하지 않고 가운데(0.5)를 돌려줍니다.** 근거 없는 제안은
       사람이 맞춘 값을 망칩니다.
    """
    if width <= 0:
        raise ValueError("영상 가로 크기가 있어야 합니다.")
    centers = [b.center_x for b in (biggest(f) for f in frames) if b is not None]
    samples, found = len(frames), len(centers)
    coverage = found / samples if samples else 0.0
    if not centers or coverage < MIN_COVERAGE:
        return Suggestion(
            focus_x=0.5,
            samples=samples,
            found=found,
            spread=0.0,
            reason=f"얼굴이 보인 표본이 {coverage:.0%}뿐이라 가운데로 둡니다.",
        )
    ratios = [max(0.0, min(1.0, c / width)) for c in centers]
    center = middle(ratios)
    # 흔들림은 가운뎃값에서 떨어진 거리의 가운뎃값입니다. 한쪽으로 튄 한 장에
    # 끌리지 않습니다.
    spread = middle([abs(r - center) for r in ratios])
    if spread > 0.25:
        return Suggestion(
            focus_x=0.5,
            samples=samples,
            found=found,
            spread=spread,
            reason=f"얼굴 위치가 화면 폭의 ±{spread:.0%}로 흔들려 한 점으로 정할 수 없습니다.",
        )
    return Suggestion(
        focus_x=round(center, 3),
        samples=samples,
        found=found,
        spread=spread,
        reason=f"표본 {found}/{samples}장에서 얼굴 가운뎃값 {center:.0%} 지점입니다.",
    )
