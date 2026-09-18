"""여러 워커가 동시에 예약해도 한도를 넘지 않는지 확인합니다.

행 잠금이 실제로 필요한 검증이라 PostgreSQL에서만 의미가 있습니다. SQLite에는
FOR UPDATE가 없으므로 건너뜁니다. CI는 PostgreSQL 서비스로 실행합니다.
"""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from adminapi.db import get_session_factory
from adminapi.models import Budget
from adminapi.services import budget as budget_service
from pipeline.budget import BudgetShortfall

pytestmark = pytest.mark.postgres

WORKERS = 8
LIMIT = Decimal("10")
ESTIMATE = Decimal("2")


@pytest.fixture(autouse=True)
def _skip_without_postgres(is_postgres: bool) -> None:
    if not is_postgres:
        pytest.skip("PostgreSQL이 아니면 행 잠금을 검증할 수 없습니다.")


def test_concurrent_reservations_never_exceed_limit(session: Session) -> None:
    """한도 10에 2씩 8개가 동시에 들어오면 5개만 성공해야 합니다."""
    budget = Budget(
        id=uuid.uuid4(),
        scope="monthly",
        scope_ref=f"concurrency-{uuid.uuid4().hex[:8]}",
        limit_amount=LIMIT,
        spent_amount=Decimal("0"),
    )
    session.add(budget)
    session.commit()

    factory = get_session_factory()
    start = threading.Barrier(WORKERS)
    granted: list[uuid.UUID] = []
    refused = 0
    lock = threading.Lock()

    def attempt() -> None:
        nonlocal refused
        start.wait(timeout=10)
        with factory() as worker_session:
            try:
                reservation = budget_service.reserve(
                    worker_session, budget_id=budget.id, estimate=ESTIMATE
                )
                worker_session.commit()
            except BudgetShortfall:
                worker_session.rollback()
                with lock:
                    refused += 1
                return
            with lock:
                granted.append(reservation.id)

    threads = [threading.Thread(target=attempt) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(granted) == int(LIMIT / ESTIMATE)
    assert refused == WORKERS - len(granted)
    assert budget_service.held_total(session, budget.id) == LIMIT
