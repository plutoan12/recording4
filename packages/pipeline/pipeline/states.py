"""상태와 전이.

docs/ARCHITECTURE.md의 "상태와 복구" 전이표를 그대로 옮긴 것입니다. 표에 없는
전이는 허용하지 않습니다. 전이표를 바꿀 때는 문서를 함께 고칩니다.
"""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    """영상 제작 상태."""

    QUEUED = "queued"
    PROCESSING = "processing"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublicationState(StrEnum):
    """게시 상태."""

    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING_ON_YOUTUBE = "processing_on_youtube"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageRunState(StrEnum):
    """단계 실행 상태."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransitionError(RuntimeError):
    """전이표에 없는 상태 전이를 시도했을 때 발생합니다."""

    def __init__(self, state: StrEnum, event: str) -> None:
        super().__init__(f"허용되지 않은 전이입니다: {state.value} + {event}")
        self.state = state
        self.event = event


# (현재 상태, 이벤트) -> 다음 상태.
JOB_TRANSITIONS: dict[tuple[JobState, str], JobState] = {
    (JobState.BLOCKED, "resume"): JobState.QUEUED,
    (JobState.FAILED, "resume"): JobState.QUEUED,
    (JobState.PROCESSING, "resume"): JobState.QUEUED,
    (JobState.QUEUED, "start"): JobState.PROCESSING,
    (JobState.PROCESSING, "complete"): JobState.REVIEW_REQUIRED,
    (JobState.PROCESSING, "fail"): JobState.FAILED,
    (JobState.PROCESSING, "cancel"): JobState.CANCELLED,
    (JobState.PROCESSING, "budget_exceeded"): JobState.BLOCKED,
    (JobState.BLOCKED, "budget_released"): JobState.PROCESSING,
    (JobState.BLOCKED, "cancel"): JobState.CANCELLED,
    (JobState.REVIEW_REQUIRED, "approve"): JobState.APPROVED,
    (JobState.REVIEW_REQUIRED, "reject"): JobState.REJECTED,
    (JobState.REJECTED, "resubmit"): JobState.QUEUED,
    (JobState.FAILED, "retry"): JobState.PROCESSING,
    # 승인 이후 수정은 새 결과물 버전을 만들고 다시 검수 대상이 됩니다.
    (JobState.APPROVED, "new_version"): JobState.REVIEW_REQUIRED,
}

PUBLICATION_TRANSITIONS: dict[tuple[PublicationState, str], PublicationState] = {
    (PublicationState.PENDING, "upload_start"): PublicationState.UPLOADING,
    (PublicationState.UPLOADING, "upload_complete"): PublicationState.PROCESSING_ON_YOUTUBE,
    (PublicationState.PROCESSING_ON_YOUTUBE, "schedule_confirmed"): PublicationState.SCHEDULED,
    (PublicationState.SCHEDULED, "publish_confirmed"): PublicationState.PUBLISHED,
    (PublicationState.PENDING, "fail"): PublicationState.FAILED,
    (PublicationState.UPLOADING, "fail"): PublicationState.FAILED,
    (PublicationState.PROCESSING_ON_YOUTUBE, "fail"): PublicationState.FAILED,
    (PublicationState.SCHEDULED, "fail"): PublicationState.FAILED,
    (PublicationState.FAILED, "retry"): PublicationState.PENDING,
    (PublicationState.PENDING, "cancel"): PublicationState.CANCELLED,
    (PublicationState.UPLOADING, "cancel"): PublicationState.CANCELLED,
    (PublicationState.PROCESSING_ON_YOUTUBE, "cancel"): PublicationState.CANCELLED,
    (PublicationState.SCHEDULED, "cancel"): PublicationState.CANCELLED,
    # 교체는 새 게시가 확인된 뒤에만 일어납니다. 확인 주체는 게시 워커입니다.
    (PublicationState.SCHEDULED, "superseded"): PublicationState.SUPERSEDED,
    (PublicationState.PUBLISHED, "superseded"): PublicationState.SUPERSEDED,
}

STAGE_RUN_TRANSITIONS: dict[tuple[StageRunState, str], StageRunState] = {
    (StageRunState.PENDING, "start"): StageRunState.RUNNING,
    (StageRunState.RUNNING, "succeed"): StageRunState.SUCCEEDED,
    (StageRunState.RUNNING, "fail"): StageRunState.FAILED,
    (StageRunState.RUNNING, "cancel"): StageRunState.CANCELLED,
    (StageRunState.PENDING, "cancel"): StageRunState.CANCELLED,
    (StageRunState.FAILED, "retry"): StageRunState.PENDING,
}

_TABLES: dict[type[StrEnum], dict[tuple[StrEnum, str], StrEnum]] = {
    JobState: JOB_TRANSITIONS,  # type: ignore[dict-item]
    PublicationState: PUBLICATION_TRANSITIONS,  # type: ignore[dict-item]
    StageRunState: STAGE_RUN_TRANSITIONS,  # type: ignore[dict-item]
}


def _table_for(state: StrEnum) -> dict[tuple[StrEnum, str], StrEnum]:
    try:
        return _TABLES[type(state)]
    except KeyError:
        raise TypeError(f"전이표가 없는 상태 종류입니다: {type(state).__name__}") from None


def next_state(state: StrEnum, event: str) -> StrEnum | None:
    """전이 결과를 돌려줍니다. 허용되지 않으면 None입니다."""
    return _table_for(state).get((state, event))


def can_transition(state: StrEnum, event: str) -> bool:
    return next_state(state, event) is not None


def assert_transition(state: StrEnum, event: str) -> StrEnum:
    """전이 결과를 돌려주고, 허용되지 않으면 TransitionError를 냅니다."""
    result = next_state(state, event)
    if result is None:
        raise TransitionError(state, event)
    return result


def terminal_states(state_type: type[StrEnum]) -> set[StrEnum]:
    """더 나갈 전이가 없는 상태들."""
    table = _TABLES[state_type]
    return {s for s in state_type if not any(key[0] == s for key in table)}
