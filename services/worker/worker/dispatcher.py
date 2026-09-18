"""outbox 디스패처.

DB에 쌓인 실행 요청을 큐로 보냅니다. 전송에 실패하면 published_at을 비워 두어
다음 주기에 다시 시도합니다. 큐에는 식별자만 넣습니다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from adminapi.models import utcnow
from adminapi.outbox import unpublished

logger = logging.getLogger(__name__)

TOPIC_TASKS: dict[str, str] = {
    "source_asset.verify": "worker.tasks.verify_source_asset",
    "media.run": "worker.media_tasks.run_media",
    "job.start": "worker.workflow_tasks.run_job",
    "job.step": "worker.workflow_tasks.run_job",
    "publication.run": "worker.publication_tasks.run_publication",
}


def dispatch_pending(
    session: Session,
    send: Callable[[str, dict], None],
    *,
    limit: int = 100,
) -> int:
    """보내지 않은 메시지를 큐로 보냅니다. 보낸 건수를 돌려줍니다."""
    sent = 0
    for message in unpublished(session, limit=limit):
        task_name = TOPIC_TASKS.get(message.topic)
        if task_name is None:
            logger.debug("연결된 태스크가 없는 주제입니다: %s", message.topic)
            continue
        message.attempts += 1
        try:
            send(task_name, message.payload)
        except Exception as exc:  # noqa: BLE001 - 어떤 전송 실패든 다음 주기에 재시도합니다.
            message.last_error = str(exc)[:1000]
            logger.warning("큐 전송 실패 outbox=%s topic=%s", message.id, message.topic)
            continue
        message.published_at = utcnow()
        message.last_error = None
        sent += 1
    session.commit()
    return sent


def celery_sender(task_name: str, payload: dict) -> None:
    from worker.celery_app import celery_app

    celery_app.send_task(task_name, kwargs=payload)


def run_once(session_factory: Callable[[], Session]) -> int:
    with session_factory() as session:
        return dispatch_pending(session, celery_sender)
