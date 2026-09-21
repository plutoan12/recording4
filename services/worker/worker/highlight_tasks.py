"""하이라이트 추천. **이 저장소에서 유일하게 워크플로 밖에서 도는 유료 호출입니다.**

`media_tasks`는 공짜·로컬 처리만 합니다. 유료 호출은 `workflow_tasks`가 하는데,
그쪽은 더빙 파이프라인의 단계들입니다. 하이라이트 추천은 파이프라인의 단계가
아니라 사람이 편집하다 누르는 버튼이라 어느 쪽에도 맞지 않아 따로 둡니다.

따로 두더라도 **유료 호출의 규칙은 같습니다**: 예산을 먼저 잡고, 부르고,
정산합니다. 예약 없이 부르면 한도를 넘겨도 아무도 모릅니다.

돌려주는 것은 `suggest_clips`와 같은 모양의 후보 목록입니다. 버린 후보도 이유와
함께 같이 넣습니다. 목록이 짧은 이유가 모델인지 우리인지 알아야 합니다.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_UP, Decimal

from sqlalchemy import func, select, update

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Budget, MediaTask, SourceAsset, TranscriptSegment, utcnow
from adminapi.services.budget import reserve, settle
from pipeline.editing import Cue
from pipeline.highlights import TooMuchTranscript, accept, numbered
from worker.celery_app import celery_app
from worker.providers import ClaudeHighlights, ProviderError


class Blocked(RuntimeError):
    """사람이 설정을 고쳐야 넘어갑니다. 다시 시도해도 같습니다."""


def latest_transcript(session, asset_id) -> list[TranscriptSegment]:
    """가장 최신 대본 판. 옛 판으로 후보를 뽑으면 사람이 고친 글이 무시됩니다."""
    version = session.scalar(
        select(func.max(TranscriptSegment.transcript_version)).where(
            TranscriptSegment.source_asset_id == asset_id
        )
    )
    return list(
        session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.source_asset_id == asset_id,
                TranscriptSegment.transcript_version == version,
            )
            .order_by(TranscriptSegment.start_seconds)
        )
    )


def cost(transcript: str, settings) -> Decimal:
    """보수적인 상한으로 비용을 잡습니다. 글자 수로 셉니다.

    실제 청구는 토큰 단위이고 생각·출력도 함께 붙습니다. 운영자가 적어 두는
    단가는 **상한**이어야 합니다. 번역·더빙 단가와 같은 방식입니다.
    """
    rate = settings.highlight_usd_per_1k_chars
    if not settings.paid_processing_enabled:
        raise Blocked("서버의 유료 처리 설정이 꺼져 있습니다.")
    if rate is None or rate <= 0:
        raise Blocked(
            "하이라이트 추천의 보수적인 단가 상한(R4_HIGHLIGHT_USD_PER_1K_CHARS)을 설정하세요."
        )
    return (Decimal(len(transcript)) / 1000 * rate).quantize(Decimal("0.0001"), rounding=ROUND_UP)


def monthly_budget(session) -> Budget:
    budget = session.scalar(select(Budget).where(Budget.scope == "monthly").limit(1))
    if budget is None:
        raise Blocked("월 예산이 없습니다. 예산을 먼저 만드세요.")
    return budget


@celery_app.task(name="worker.highlight_tasks.run_highlights", soft_time_limit=600, time_limit=660)
def run_highlights(task_id: str) -> dict:
    factory = get_session_factory()
    task_uuid = uuid.UUID(task_id)
    with factory() as session:
        claim = session.execute(
            update(MediaTask)
            .where(MediaTask.id == task_uuid, MediaTask.state == "pending")
            .values(state="running", started_at=utcnow())
        )
        session.commit()
        if not claim.rowcount:
            return {"status": "already_claimed"}
        task = session.get(MediaTask, task_uuid)
        asset = session.get(SourceAsset, task.source_asset_id)
        duration, attempt = float(asset.duration_seconds), task.attempt
        cues = [
            Cue(start=float(row.start_seconds), end=float(row.end_seconds), text=row.text)
            for row in latest_transcript(session, task.source_asset_id)
        ]

    reservation_id = None
    try:
        if not cues:
            raise Blocked("대본이 없습니다.")
        settings = get_settings()
        transcript = numbered(cues)
        estimate = cost(transcript, settings)
        # 예약이 성공한 뒤에만 부릅니다. 순서를 바꾸면 한도를 넘겨 부르게 됩니다.
        with factory() as session:
            held = reserve(session, budget_id=monthly_budget(session).id, estimate=estimate)
            reservation_id = held.id
            session.commit()
        picks = ClaudeHighlights(allow_paid=True).pick(transcript)
        taken, thrown = accept(cues, picks, duration=duration)
        result = {
            "clips": taken,
            "rejected": [
                {"first": r.pick.first, "last": r.pick.last, "why": r.why} for r in thrown
            ],
        }
    except (Blocked, TooMuchTranscript, ProviderError, ValueError) as exc:
        if reservation_id is not None:
            with factory() as session:
                # 부르다 실패했을 수 있습니다. 잡아 둔 금액은 풀어 줍니다.
                settle(session, reservation_id, Decimal("0"))
                session.commit()
        with factory() as session:
            session.execute(
                update(MediaTask)
                .where(MediaTask.id == task_uuid, MediaTask.attempt == attempt)
                .values(state="failed", error=str(exc)[:1000], finished_at=utcnow())
            )
            session.commit()
        return {"status": "failed", "error": str(exc)}

    with factory() as session:
        # 실제 청구액을 우리가 알 수 없으므로 예약한 상한으로 정산합니다.
        settle(session, reservation_id, None)
        task = session.scalar(select(MediaTask).where(MediaTask.id == task_uuid).with_for_update())
        if task.attempt != attempt or task.state != "running":
            session.commit()
            return {"status": "superseded_attempt"}
        task.state, task.result, task.error = "succeeded", result, None
        task.finished_at = utcnow()
        session.commit()
    return {"status": "succeeded", "clips": len(result["clips"])}
