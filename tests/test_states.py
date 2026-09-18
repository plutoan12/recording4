"""상태 전이표 테스트. 표에 없는 전이는 거부되어야 합니다."""

from __future__ import annotations

import pytest

from pipeline.states import (
    JOB_TRANSITIONS,
    PUBLICATION_TRANSITIONS,
    STAGE_RUN_TRANSITIONS,
    JobState,
    PublicationState,
    StageRunState,
    TransitionError,
    assert_transition,
    can_transition,
    next_state,
)


@pytest.mark.parametrize(
    ("state", "event", "expected"), [(k[0], k[1], v) for k, v in JOB_TRANSITIONS.items()]
)
def test_job_table_entries_are_allowed(state, event, expected) -> None:  # noqa: ANN001
    assert assert_transition(state, event) is expected


@pytest.mark.parametrize(
    ("state", "event", "expected"), [(k[0], k[1], v) for k, v in PUBLICATION_TRANSITIONS.items()]
)
def test_publication_table_entries_are_allowed(state, event, expected) -> None:  # noqa: ANN001
    assert assert_transition(state, event) is expected


@pytest.mark.parametrize(
    ("state", "event", "expected"), [(k[0], k[1], v) for k, v in STAGE_RUN_TRANSITIONS.items()]
)
def test_stage_run_table_entries_are_allowed(state, event, expected) -> None:  # noqa: ANN001
    assert assert_transition(state, event) is expected


def test_transitions_outside_the_table_are_rejected() -> None:
    events = {event for _state, event in JOB_TRANSITIONS}
    rejected = 0
    for state in JobState:
        for event in events:
            if (state, event) in JOB_TRANSITIONS:
                continue
            rejected += 1
            assert not can_transition(state, event)
            with pytest.raises(TransitionError):
                assert_transition(state, event)
    assert rejected > 0


def test_approved_job_returns_to_review_on_new_version() -> None:
    """승인 이후 수정은 새 버전을 만들고 다시 검수 대상이 됩니다."""
    assert assert_transition(JobState.APPROVED, "new_version") is JobState.REVIEW_REQUIRED


def test_approved_job_cannot_be_published_state() -> None:
    assert next_state(JobState.APPROVED, "approve") is None
    assert next_state(JobState.CANCELLED, "start") is None


def test_budget_block_and_release_round_trip() -> None:
    blocked = assert_transition(JobState.PROCESSING, "budget_exceeded")
    assert blocked is JobState.BLOCKED
    assert assert_transition(blocked, "budget_released") is JobState.PROCESSING


def test_publication_supersede_requires_scheduled_or_published() -> None:
    """교체는 예약되었거나 공개된 게시에서만 일어납니다."""
    assert (
        assert_transition(PublicationState.PUBLISHED, "superseded") is PublicationState.SUPERSEDED
    )
    assert (
        assert_transition(PublicationState.SCHEDULED, "superseded") is PublicationState.SUPERSEDED
    )
    assert next_state(PublicationState.PENDING, "superseded") is None
    assert next_state(PublicationState.UPLOADING, "superseded") is None


def test_stage_run_retry_returns_to_pending() -> None:
    assert assert_transition(StageRunState.FAILED, "retry") is StageRunState.PENDING
    assert next_state(StageRunState.SUCCEEDED, "retry") is None
