"""설계 문서(docs/ARCHITECTURE.md)의 규칙을 코드로 옮긴 공유 도메인 패키지."""

from pipeline.budget import (
    BudgetShortfall,
    ReservationState,
    available_amount,
    settle_amount,
)
from pipeline.hashing import StageInputs, compute_input_hash
from pipeline.states import (
    JobState,
    PublicationState,
    StageRunState,
    TransitionError,
    assert_transition,
    can_transition,
    next_state,
)

__all__ = [
    "BudgetShortfall",
    "JobState",
    "PublicationState",
    "ReservationState",
    "StageInputs",
    "StageRunState",
    "TransitionError",
    "assert_transition",
    "available_amount",
    "can_transition",
    "compute_input_hash",
    "next_state",
    "settle_amount",
]
