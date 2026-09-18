"""트랜잭션 outbox.

큐에는 작업 식별자만 넣습니다. 실행 요청을 기록하는 트랜잭션과 같은 트랜잭션에서
outbox 행을 만들고, 별도 디스패처가 큐로 보냅니다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from adminapi.models import OutboxMessage


def enqueue(session: Session, *, topic: str, payload: dict, dedupe_key: str) -> OutboxMessage:
    """outbox에 메시지를 넣습니다. 같은 dedupe_key는 한 번만 들어갑니다.

    commit은 호출자가 합니다. 실행 요청과 같은 트랜잭션에 묶어야 하기 때문입니다.
    """
    existing = session.scalar(select(OutboxMessage).where(OutboxMessage.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    message = OutboxMessage(topic=topic, payload=payload, dedupe_key=dedupe_key)
    session.add(message)
    session.flush()
    return message


def unpublished(session: Session, *, limit: int = 100) -> list[OutboxMessage]:
    stmt = (
        select(OutboxMessage)
        .where(OutboxMessage.published_at.is_(None))
        .order_by(OutboxMessage.created_at)
        .limit(limit)
    )
    return list(session.scalars(stmt))
