"""하이라이트 추천 작업. **유료 호출은 대역이 대신합니다.**

여기서 보는 것은 추천의 품질이 아니라 **돈이 새지 않는지**입니다. 예약 없이
부르면 한도를 넘겨도 아무도 모르고, 실패한 호출이 예약을 물고 있으면 예산이
말라붙습니다.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from adminapi.models import Budget, BudgetReservation, MediaTask, SourceAsset, TranscriptSegment
from pipeline.budget import ReservationState
from pipeline.highlights import Pick


@pytest.fixture
def asset(session, user):
    row = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="test.mp4",
        created_by_id=user.id,
        duration_seconds=Decimal("120"),
        width=1920,
        height=1080,
        upload_state="verified",
    )
    session.add(row)
    session.flush()
    for i in range(8):
        session.add(
            TranscriptSegment(
                source_asset_id=row.id,
                transcript_version=1,
                start_seconds=Decimal(i * 6),
                end_seconds=Decimal(i * 6 + 6),
                text=f"{i}번째 문장입니다",
            )
        )
    session.commit()
    return row


@pytest.fixture
def budget(session):
    row = Budget(
        id=uuid.uuid4(),
        scope="monthly",
        scope_ref=f"highlights-{uuid.uuid4().hex[:8]}",
        limit_amount=Decimal("10"),
        spent_amount=Decimal("0"),
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def task(session, asset):
    row = MediaTask(source_asset_id=asset.id, kind="highlights", settings={})
    session.add(row)
    session.commit()
    return row


def priced(monkeypatch, enabled: bool = True, rate: str | None = "0.02"):
    from adminapi.config import get_settings

    monkeypatch.setenv("R4_PAID_PROCESSING_ENABLED", "true" if enabled else "false")
    if rate is None:
        monkeypatch.delenv("R4_HIGHLIGHT_USD_PER_1K_CHARS", raising=False)
    else:
        monkeypatch.setenv("R4_HIGHLIGHT_USD_PER_1K_CHARS", rate)
    get_settings.cache_clear()


def stand(monkeypatch, picks=None, raises=None):
    """유료 공급자 자리에 세우는 대역. 실제로 불렸는지 적어 둡니다."""
    seen = []

    class Stand:
        def __init__(self, **kwargs):
            pass

        def pick(self, transcript, **kwargs):
            seen.append(transcript)
            if raises is not None:
                raise raises
            return picks or []

    monkeypatch.setattr("worker.highlight_tasks.ClaudeHighlights", Stand)
    return seen


def run(task_id) -> dict:
    from worker.highlight_tasks import run_highlights

    return run_highlights(str(task_id))


def test_picks_become_clips_and_the_budget_is_settled(session, task, budget, monkeypatch):
    priced(monkeypatch)
    called = stand(monkeypatch, picks=[Pick(1, 4, "제목", "이유")])
    try:
        assert run(task.id)["status"] == "succeeded"
    finally:
        from adminapi.config import get_settings

        get_settings.cache_clear()

    assert called, "유료 공급자가 불리지 않았습니다."
    session.expire_all()
    done = session.get(MediaTask, task.id)
    assert done.state == "succeeded"
    [clip] = done.result["clips"]
    assert (clip["start"], clip["end"]) == (6.0, 30.0)
    assert done.result["rejected"] == []

    held = session.scalars(
        select(BudgetReservation).where(BudgetReservation.budget_id == budget.id)
    ).all()
    assert [row.state for row in held] == [ReservationState.SETTLED]
    assert session.get(Budget, budget.id).spent_amount > 0


def test_a_paid_call_never_happens_without_a_configured_ceiling(session, task, budget, monkeypatch):
    """단가를 안 적어 두면 얼마가 나갈지 모른 채 부르게 됩니다."""
    priced(monkeypatch, rate=None)
    called = stand(monkeypatch, picks=[Pick(0, 3, "", "")])
    try:
        assert run(task.id)["status"] == "failed"
    finally:
        from adminapi.config import get_settings

        get_settings.cache_clear()
    assert not called
    session.expire_all()
    assert "단가" in session.get(MediaTask, task.id).error


def test_paid_processing_off_blocks_the_call(session, task, budget, monkeypatch):
    priced(monkeypatch, enabled=False)
    called = stand(monkeypatch, picks=[Pick(0, 3, "", "")])
    try:
        assert run(task.id)["status"] == "failed"
    finally:
        from adminapi.config import get_settings

        get_settings.cache_clear()
    assert not called


def test_a_failed_call_releases_the_money_it_was_holding(session, task, budget, monkeypatch):
    """예약이 HELD로 남으면 그만큼 예산이 영영 줄어듭니다."""
    from worker.providers import ProviderError

    priced(monkeypatch)
    stand(monkeypatch, raises=ProviderError("모델이 답을 거절했습니다."))
    try:
        assert run(task.id)["status"] == "failed"
    finally:
        from adminapi.config import get_settings

        get_settings.cache_clear()

    session.expire_all()
    held = session.scalars(
        select(BudgetReservation).where(BudgetReservation.budget_id == budget.id)
    ).all()
    assert [row.state for row in held] == [ReservationState.SETTLED]
    assert session.get(Budget, budget.id).spent_amount == Decimal("0")
    assert "거절" in session.get(MediaTask, task.id).error


def test_a_hallucinated_number_is_recorded_not_hidden(session, task, budget, monkeypatch):
    """버린 이유가 남아야 목록이 짧은 까닭을 사람이 압니다."""
    priced(monkeypatch)
    stand(monkeypatch, picks=[Pick(1, 4, "제목", "이유"), Pick(90, 99, "", "")])
    try:
        run(task.id)
    finally:
        from adminapi.config import get_settings

        get_settings.cache_clear()
    session.expire_all()
    done = session.get(MediaTask, task.id)
    assert len(done.result["clips"]) == 1
    assert "대본에 없는 번호" in done.result["rejected"][0]["why"]
