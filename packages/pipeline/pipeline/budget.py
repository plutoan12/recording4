"""예산 예약과 정산 규칙.

docs/ARCHITECTURE.md "비용 한도"를 구현합니다. 누적 사용액만 확인하면 여러
워커가 같은 잔액을 동시에 쓸 수 있으므로, 호출 전에 예상 비용을 예약하고
완료 후 실제 비용으로 정산합니다.

여기에는 순수 계산만 둡니다. 잔액 확인과 예약을 한 트랜잭션에서 수행하고 예산
행을 잠그는 부분은 adminapi.services.budget에 있습니다.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum


class ReservationState(StrEnum):
    """예약 상태."""

    HELD = "held"
    """호출 전 예약이 잡혀 있고 아직 정산되지 않은 상태."""
    SETTLED = "settled"
    """실제 비용으로 정산되어 누적 사용액에 반영된 상태."""
    RELEASED = "released"
    """호출하지 않았거나 실패·취소되어 되돌린 상태."""
    EXPIRED = "expired"
    """워커 중단으로 만료 회수된 상태. 회수 전 실제 실행 여부를 확인합니다."""


OPEN_STATES = frozenset({ReservationState.HELD})
"""잔액에서 빼야 하는 예약 상태."""


class BudgetShortfall(RuntimeError):
    """남은 예산이 예상 비용보다 적을 때 발생합니다."""

    def __init__(self, requested: Decimal, available: Decimal) -> None:
        super().__init__(f"예산이 부족합니다. 요청 {requested}, 잔액 {available}")
        self.requested = requested
        self.available = available


def available_amount(limit: Decimal, spent: Decimal, held: Decimal) -> Decimal:
    """잔액 = 한도 - 누적 사용액 - 예약 합계.

    음수가 되면 0으로 보정합니다. 정산 차액이나 한도 하향으로 초과가 생길 수
    있으나, 잔액이 음수라는 것은 "더 쓸 수 없다"와 같은 뜻입니다.
    """
    remaining = limit - spent - held
    return remaining if remaining > 0 else Decimal("0")


def check_affordable(limit: Decimal, spent: Decimal, held: Decimal, estimate: Decimal) -> Decimal:
    """예약 가능하면 잔액을 돌려주고, 부족하면 BudgetShortfall을 냅니다."""
    if estimate < 0:
        raise ValueError("예상 비용은 0 이상이어야 합니다.")
    remaining = available_amount(limit, spent, held)
    if estimate > remaining:
        raise BudgetShortfall(estimate, remaining)
    return remaining


def settle_amount(reserved: Decimal, actual: Decimal | None) -> Decimal:
    """정산에 반영할 실제 비용.

    실제 비용을 알 수 없으면(None) 예약 금액을 그대로 사용합니다. 과소 청구보다
    과다 계상이 안전합니다. 예상 비용을 모르는 호출은 상한값으로 예약하고
    정산에서 차액을 되돌립니다.
    """
    if actual is None:
        return reserved
    if actual < 0:
        raise ValueError("실제 비용은 0 이상이어야 합니다.")
    return actual
