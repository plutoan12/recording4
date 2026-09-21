"""용어집 조회. 번역 단계와 관리 API가 같은 규칙으로 고르도록 한곳에 둡니다."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from adminapi.models import Glossary as GlossaryRow
from adminapi.models import utcnow
from pipeline.glossary import Glossary
from pipeline.time import as_utc

SCOPE = "project"


def find_row(session: Session, source_language: str, target_language: str) -> GlossaryRow | None:
    """그 방향의 용어집 행. 여러 개면 나중에 발효한 것, 그다음 높은 판입니다."""
    return session.scalars(
        select(GlossaryRow)
        .where(
            GlossaryRow.scope == SCOPE,
            GlossaryRow.source_language == source_language,
            GlossaryRow.target_language == target_language,
        )
        .order_by(GlossaryRow.effective_from.desc(), GlossaryRow.version.desc())
        .limit(1)
    ).first()


def active_glossary(
    session: Session, source_language: str | None, target_language: str | None
) -> Glossary | None:
    """지금 번역에 쓸 용어집.

    **원문 언어를 지정하지 않은 작업에는 쓰지 않습니다.** 용어집은 방향마다
    다른데, 자동 감지에 맡기면 어느 쪽 용어집인지 알 수 없습니다. 엉뚱한
    용어집을 들이대느니 쓰지 않는 쪽이 낫습니다.
    """
    if not source_language or not target_language:
        return None
    row = find_row(session, source_language, target_language)
    if row is None or not row.entries or as_utc(row.effective_from) > utcnow():
        return None
    return Glossary(
        source_language=row.source_language,
        target_language=row.target_language,
        version=row.version,
        entries=row.entries,
    )
