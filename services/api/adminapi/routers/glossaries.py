"""용어집. 번역이 꼭 써야 할 표기를 방향(원문 언어 → 목표 언어)마다 둡니다.

바꾼 용어는 **다음 번역 단계부터** 적용됩니다. 이미 번역이 끝난 작업의 결과를
바꾸지 않습니다. 방식과 한계는 `pipeline.glossary`에 적어 두었습니다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import Glossary as GlossaryRow
from adminapi.models import utcnow
from adminapi.services.glossary import SCOPE, find_row
from pipeline.glossary import MAX_TERMS, Glossary

router = APIRouter(prefix="/glossaries", tags=["glossaries"])

SourceLanguage = Path(pattern=r"^[a-z]{2,3}$", description="원문 언어")
TargetLanguage = Path(pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,8})?$", description="목표 언어")


class GlossarySummary(BaseModel):
    source_language: str
    target_language: str
    version: int
    term_count: int


class GlossaryDetail(GlossarySummary):
    entries: dict[str, str]


class GlossaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: dict[str, str] = Field(description="{원문 표기: 번역문에 넣을 표기}")

    @field_validator("entries")
    @classmethod
    def small_enough(cls, entries: dict[str, str]) -> dict[str, str]:
        if len(entries) > MAX_TERMS:
            raise ValueError(f"용어는 {MAX_TERMS}개까지 넣을 수 있습니다.")
        return entries


def _detail(row: GlossaryRow) -> GlossaryDetail:
    return GlossaryDetail(
        source_language=row.source_language,
        target_language=row.target_language,
        version=row.version,
        term_count=len(row.entries or {}),
        entries=row.entries or {},
    )


@router.get("", response_model=list[GlossarySummary])
def list_glossaries(user: CurrentUser, session: SessionDep) -> list[GlossarySummary]:
    rows = session.scalars(
        select(GlossaryRow)
        .where(GlossaryRow.scope == SCOPE)
        .order_by(GlossaryRow.source_language, GlossaryRow.target_language)
    )
    return [GlossarySummary(**_detail(row).model_dump(exclude={"entries"})) for row in rows]


@router.get("/{source_language}/{target_language}", response_model=GlossaryDetail)
def read_glossary(
    user: CurrentUser,
    session: SessionDep,
    source_language: str = SourceLanguage,
    target_language: str = TargetLanguage,
) -> GlossaryDetail:
    row = find_row(session, source_language, target_language)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "그 방향의 용어집이 없습니다.")
    return _detail(row)


@router.put("/{source_language}/{target_language}", response_model=GlossaryDetail)
def save_glossary(
    payload: GlossaryRequest,
    user: CurrentUser,
    session: SessionDep,
    source_language: str = SourceLanguage,
    target_language: str = TargetLanguage,
) -> GlossaryDetail:
    """용어집을 통째로 바꿉니다. 바꿀 때마다 판(version)이 올라갑니다."""
    try:
        checked = Glossary(
            source_language=source_language,
            target_language=target_language,
            entries=payload.entries,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    row = find_row(session, source_language, target_language)
    if row is None:
        row = GlossaryRow(
            scope=SCOPE,
            source_language=source_language,
            target_language=target_language,
            version=1,
            entries=checked.entries,
            effective_from=utcnow(),
        )
        session.add(row)
    else:
        row.version += 1
        row.entries = checked.entries
        row.effective_from = utcnow()
    session.flush()
    return _detail(row)


@router.delete("/{source_language}/{target_language}", status_code=status.HTTP_204_NO_CONTENT)
def remove_glossary(
    user: CurrentUser,
    session: SessionDep,
    source_language: str = SourceLanguage,
    target_language: str = TargetLanguage,
) -> Response:
    row = find_row(session, source_language, target_language)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "그 방향의 용어집이 없습니다.")
    session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
