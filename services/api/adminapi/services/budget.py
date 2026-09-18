"""예산 예약과 정산의 트랜잭션 처리.

잔액 확인과 예약을 한 트랜잭션에서 수행하고 예산 행을 잠급니다. 잠그지 않으면
여러 워커가 같은 잔액을 동시에 사용해 한도를 넘을 수 있습니다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adminapi.config import get_settings
from adminapi.models import Budget, BudgetReservation
from pipeline.budget import ReservationState, check_affordable, settle_amount

DEFAULT_HOLD_TTL = timedelta(hours=6)


def held_total(session: Session, budget_id: uuid.UUID) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(BudgetReservation.amount), 0)).where(
            BudgetReservation.budget_id == budget_id,
            BudgetReservation.state == ReservationState.HELD,
        )
    )
    return Decimal(total or 0)


def reserve(
    session: Session,
    *,
    budget_id: uuid.UUID,
    estimate: Decimal,
    stage_run_id: uuid.UUID | None = None,
    ttl: timedelta = DEFAULT_HOLD_TTL,
) -> BudgetReservation:
    """예약을 잡습니다. 잔액이 모자라면 BudgetShortfall을 냅니다.

    예산 행을 잠근 뒤 잔액을 계산하므로, 동시에 들어온 다른 예약은 이 트랜잭션이
    끝날 때까지 기다립니다. 호출자는 이 함수가 성공한 뒤에만 유료 호출을 합니다.
    """
    budget = session.scalars(select(Budget).where(Budget.id == budget_id).with_for_update()).one()
    settings = get_settings()
    cap = {"job": settings.max_job_budget_usd, "monthly": settings.max_monthly_budget_usd}.get(
        budget.scope
    )
    limit = min(budget.limit_amount, cap) if cap is not None else budget.limit_amount
    check_affordable(limit, budget.spent_amount, held_total(session, budget_id), estimate)
    reservation = BudgetReservation(
        budget_id=budget_id,
        stage_run_id=stage_run_id,
        amount=estimate,
        state=ReservationState.HELD,
        expires_at=datetime.now(UTC) + ttl,
    )
    session.add(reservation)
    session.flush()
    return reservation


def settle(
    session: Session, reservation_id: uuid.UUID, actual_cost: Decimal | None
) -> BudgetReservation:
    """실제 비용으로 정산하고 누적 사용액을 같은 트랜잭션에서 갱신합니다."""
    reservation = session.scalars(
        select(BudgetReservation).where(BudgetReservation.id == reservation_id).with_for_update()
    ).one()
    if reservation.state is not ReservationState.HELD:
        return reservation
    budget = session.scalars(
        select(Budget).where(Budget.id == reservation.budget_id).with_for_update()
    ).one()
    amount = settle_amount(reservation.amount, actual_cost)
    budget.spent_amount = budget.spent_amount + amount
    reservation.state = ReservationState.SETTLED
    reservation.settled_amount = amount
    session.flush()
    return reservation


def release(session: Session, reservation_id: uuid.UUID) -> BudgetReservation:
    """호출하지 않았거나 실패·취소된 예약을 되돌립니다."""
    reservation = session.scalars(
        select(BudgetReservation).where(BudgetReservation.id == reservation_id).with_for_update()
    ).one()
    if reservation.state is ReservationState.HELD:
        reservation.state = ReservationState.RELEASED
        session.flush()
    return reservation


def expire_stale(session: Session, *, now: datetime | None = None) -> list[BudgetReservation]:
    """만료된 예약을 회수 대상으로 돌려줍니다.

    실제 회수 처리는 호출자가 공급자 작업 ID로 실행 여부를 확인한 뒤에 합니다.
    실행된 호출은 정산하고, 실행되지 않은 것만 만료 처리합니다.
    """
    moment = now or datetime.now(UTC)
    stmt = select(BudgetReservation).where(
        BudgetReservation.state == ReservationState.HELD,
        BudgetReservation.expires_at < moment,
    )
    return list(session.scalars(stmt))


def mark_expired(session: Session, reservation_id: uuid.UUID) -> BudgetReservation:
    reservation = session.scalars(
        select(BudgetReservation).where(BudgetReservation.id == reservation_id).with_for_update()
    ).one()
    if reservation.state is ReservationState.HELD:
        reservation.state = ReservationState.EXPIRED
        session.flush()
    return reservation
