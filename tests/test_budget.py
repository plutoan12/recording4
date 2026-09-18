"""예산 예약과 정산 테스트."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from adminapi.models import Budget, BudgetReservation, utcnow
from adminapi.services import budget as budget_service
from pipeline.budget import (
    BudgetShortfall,
    ReservationState,
    available_amount,
    check_affordable,
    settle_amount,
)


def make_budget(session: Session, limit: str = "100.0000", spent: str = "0") -> Budget:
    record = Budget(
        id=uuid.uuid4(),
        scope="monthly",
        scope_ref="2026-09",
        limit_amount=Decimal(limit),
        spent_amount=Decimal(spent),
    )
    session.add(record)
    session.commit()
    return record


def test_available_amount_subtracts_spent_and_held() -> None:
    assert available_amount(Decimal("100"), Decimal("30"), Decimal("50")) == Decimal("20")


def test_available_amount_never_returns_negative() -> None:
    assert available_amount(Decimal("100"), Decimal("80"), Decimal("40")) == Decimal("0")


def test_check_affordable_rejects_over_limit() -> None:
    with pytest.raises(BudgetShortfall):
        check_affordable(Decimal("100"), Decimal("90"), Decimal("0"), Decimal("20"))


def test_settle_uses_reserved_amount_when_actual_unknown() -> None:
    """실제 비용을 모르면 예약 금액을 그대로 씁니다. 과소 청구보다 안전합니다."""
    assert settle_amount(Decimal("5"), None) == Decimal("5")
    assert settle_amount(Decimal("5"), Decimal("3")) == Decimal("3")


def test_reservation_reduces_available_balance(session: Session) -> None:
    record = make_budget(session, limit="100")
    budget_service.reserve(session, budget_id=record.id, estimate=Decimal("60"))
    session.commit()
    assert budget_service.held_total(session, record.id) == Decimal("60")
    with pytest.raises(BudgetShortfall):
        budget_service.reserve(session, budget_id=record.id, estimate=Decimal("50"))


def test_sequential_reservations_cannot_exceed_limit(session: Session) -> None:
    """누적 사용액이 0이어도 예약 합계가 한도를 넘을 수 없습니다."""
    record = make_budget(session, limit="10")
    for _ in range(10):
        budget_service.reserve(session, budget_id=record.id, estimate=Decimal("1"))
    session.commit()
    with pytest.raises(BudgetShortfall):
        budget_service.reserve(session, budget_id=record.id, estimate=Decimal("0.01"))


def test_settle_moves_amount_into_spent(session: Session) -> None:
    record = make_budget(session, limit="100")
    reservation = budget_service.reserve(session, budget_id=record.id, estimate=Decimal("30"))
    session.commit()
    budget_service.settle(session, reservation.id, Decimal("21.5"))
    session.commit()
    session.refresh(record)
    assert record.spent_amount == Decimal("21.5000")
    assert budget_service.held_total(session, record.id) == Decimal("0")


def test_settle_is_idempotent(session: Session) -> None:
    """재전달로 정산이 두 번 와도 누적 사용액은 한 번만 늘어납니다."""
    record = make_budget(session, limit="100")
    reservation = budget_service.reserve(session, budget_id=record.id, estimate=Decimal("30"))
    session.commit()
    budget_service.settle(session, reservation.id, Decimal("30"))
    budget_service.settle(session, reservation.id, Decimal("30"))
    session.commit()
    session.refresh(record)
    assert record.spent_amount == Decimal("30.0000")


def test_release_returns_budget(session: Session) -> None:
    record = make_budget(session, limit="100")
    reservation = budget_service.reserve(session, budget_id=record.id, estimate=Decimal("90"))
    session.commit()
    budget_service.release(session, reservation.id)
    session.commit()
    assert budget_service.held_total(session, record.id) == Decimal("0")
    budget_service.reserve(session, budget_id=record.id, estimate=Decimal("90"))


def test_expired_reservations_are_listed_but_not_auto_settled(session: Session) -> None:
    """만료 회수 전에 실제 실행 여부를 확인해야 하므로 목록만 돌려줍니다."""
    record = make_budget(session, limit="100")
    reservation = budget_service.reserve(
        session, budget_id=record.id, estimate=Decimal("10"), ttl=timedelta(seconds=-1)
    )
    session.commit()
    stale = budget_service.expire_stale(session)
    assert [item.id for item in stale] == [reservation.id]
    assert reservation.state is ReservationState.HELD

    budget_service.mark_expired(session, reservation.id)
    session.commit()
    session.refresh(reservation)
    assert reservation.state is ReservationState.EXPIRED
    assert budget_service.held_total(session, record.id) == Decimal("0")


def test_negative_estimate_is_rejected(session: Session) -> None:
    record = make_budget(session)
    with pytest.raises(ValueError):
        budget_service.reserve(session, budget_id=record.id, estimate=Decimal("-1"))


def test_reservation_row_records_expiry(session: Session) -> None:
    record = make_budget(session)
    reservation = budget_service.reserve(session, budget_id=record.id, estimate=Decimal("1"))
    session.commit()
    stored = session.get(BudgetReservation, reservation.id)
    assert stored is not None
    assert stored.expires_at > utcnow()


@pytest.mark.parametrize("scope,cap", [("job", "1"), ("monthly", "10")])
def test_deployment_ceiling_overrides_larger_saved_budget(session, monkeypatch, scope, cap):
    from adminapi.config import get_settings

    settings = get_settings().model_copy(update={f"max_{scope}_budget_usd": Decimal(cap)})
    monkeypatch.setattr(budget_service, "get_settings", lambda: settings)
    record = make_budget(session, limit="100", spent=str(Decimal(cap) - Decimal("0.5")))
    record.scope = scope
    session.commit()
    budget_service.reserve(session, budget_id=record.id, estimate=Decimal("0.4"))
    with pytest.raises(BudgetShortfall):
        budget_service.reserve(session, budget_id=record.id, estimate=Decimal("0.2"))
