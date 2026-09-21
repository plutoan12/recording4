"""GitHub 저장소 검수 작업. 자막·용어집을 브랜치에 올려 PR을 열고, 고친 것을 가져옵니다.

**병합하지 않습니다. 기본 브랜치에 쓰지 않습니다. 가져온 번역을 작업에 자동으로 넣지도
않습니다.** 가져온 것은 검수 행에만 두고, 사람이 관리화면에서 문제를 보고 새 버전을
만듭니다. 새 버전 경로는 기존 `translated_cues`와 같습니다.
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import update

from adminapi.artifact_subtitles import Missing, job_subtitles
from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Job, SubtitleReview, utcnow
from pipeline.editing import Cue
from pipeline.review import (
    MAX_CUES,
    compare,
    glossary_path,
    glossary_tsv,
    parse_glossary_tsv,
    pull_request_body,
)
from pipeline.subtitle_files import parse_subtitles
from pipeline.workflow import WorkflowOptions, rendered_cues
from worker.celery_app import celery_app
from worker.github import GitHubError, GitHubRepository


class Blocked(RuntimeError):
    pass


def repository(settings, client):  # noqa: ANN001
    if not settings.github_token or not settings.github_repository:
        raise Blocked("GitHub 토큰과 저장소(owner/repo)를 설정하세요.")
    return GitHubRepository(
        settings.github_token,
        settings.github_repository,
        client=client,
        allow_write=settings.github_review_enabled,
        api_url=settings.github_api_url,
    )


def original_cues(job) -> list[Cue]:  # noqa: ANN001
    return [Cue.model_validate(row) for row in rendered_cues(job.workflow_data or {})]


def export_review(session, review, job, settings, repo) -> dict:  # noqa: ANN001
    """자막과 용어집을 검수 브랜치에 올리고 PR을 엽니다. 이미 있으면 그 PR을 씁니다."""
    subtitles = job_subtitles(job, "srt")
    if isinstance(subtitles, Missing):
        raise Blocked(subtitles.reason)
    # 늦게 들입니다. workflow_tasks는 무겁고 여기서는 용어집 조회만 씁니다.
    from worker.workflow_tasks import glossary_for

    options = WorkflowOptions.model_validate(job.workflow_config)
    entries, _ = glossary_for(session, options.source_language, job.target_language)
    terms = glossary_path(options.source_language, job.target_language)

    base = repo.branch_sha(settings.github_base_branch)
    if base is None:
        raise Blocked(f"기본 브랜치 {settings.github_base_branch}를 찾을 수 없습니다.")
    if repo.branch_sha(review.branch) is None:
        repo.create_branch(review.branch, base)
    commit = repo.put_file(
        review.path,
        review.branch,
        subtitles.text,
        f"자막 검수: 작업 {job.id} ({review.language})",
    )
    repo.put_file(terms, review.branch, glossary_tsv(entries), f"용어집: {terms}")
    number, url = repo.open_pull_request(
        review.branch,
        settings.github_base_branch,
        f"자막 검수: 작업 {str(job.id)[:8]} → {review.language}",
        pull_request_body(review.path, terms, review.language),
    )
    return {
        "pull_number": number,
        "pull_url": url,
        "commit_sha": commit,
        "result": {
            "glossary_path": terms,
            "cue_count": len(original_cues(job)),
            # 내용이 그대로면 커밋하지 않습니다. 쓸데없는 커밋을 만들지 않기 위해서입니다.
            "committed": commit is not None,
        },
    }


def import_review(session, review, job, settings, repo) -> dict:  # noqa: ANN001
    """검수 브랜치의 자막을 읽어 우리가 보낸 것과 견줍니다. 작업에는 넣지 않습니다."""
    found = repo.file(review.path, review.branch)
    if found is None:
        raise Blocked(f"{review.branch} 브랜치에 {review.path}가 없습니다. 먼저 내보내세요.")
    cues, dropped = parse_subtitles(found[0])
    if not cues:
        raise Blocked("가져온 파일에서 자막을 읽지 못했습니다.")
    if len(cues) > MAX_CUES:
        raise Blocked(f"자막이 {len(cues)}개입니다. {MAX_CUES}개까지만 가져옵니다.")
    problems = compare(original_cues(job), cues)

    options = WorkflowOptions.model_validate(job.workflow_config)
    terms = (review.result or {}).get("glossary_path") or glossary_path(
        options.source_language, job.target_language
    )
    glossary, changed = None, False
    edited = repo.file(terms, review.branch)
    if edited is not None:
        glossary = parse_glossary_tsv(edited[0])
        if len(glossary) > MAX_CUES:
            raise Blocked(f"용어집 항목이 {len(glossary)}개입니다. 너무 많습니다.")
        from worker.workflow_tasks import glossary_for

        current, _ = glossary_for(session, options.source_language, job.target_language)
        changed = glossary != current
    state = repo.pull_request(review.pull_number) if review.pull_number else None
    return {
        "result": {
            "cues": [c.model_dump() for c in cues],
            "problems": problems,
            # 읽으며 벗긴 꾸밈 표기 같은 알림입니다. 적용을 막지는 않습니다.
            "notes": list(dropped),
            "applicable": not problems,
            "cue_count": len(cues),
            "glossary_path": terms,
            "glossary": glossary,
            # 용어집을 되돌려 저장할 방향. 출발 언어를 모르면 모든 언어(*)입니다.
            "source_language": options.source_language or "*",
            "glossary_changed": changed,
            "pull_state": state,
        },
    }


@celery_app.task(name="worker.review_tasks.run_review", soft_time_limit=300, time_limit=360)
def run_review(review_id: str) -> dict:
    factory = get_session_factory()
    review_uuid = uuid.UUID(review_id)
    with factory() as session:
        claimed = session.execute(
            update(SubtitleReview)
            .where(SubtitleReview.id == review_uuid, SubtitleReview.state == "pending")
            .values(state="running", started_at=utcnow())
        )
        session.commit()
        if not claimed.rowcount:
            return {"status": "already_claimed"}
    try:
        with factory() as session:
            review = session.get(SubtitleReview, review_uuid)
            job = session.get(Job, review.job_id)
            if job is None:
                raise Blocked("검수 요청의 작업을 찾을 수 없습니다.")
            settings = get_settings()
            with httpx.Client(follow_redirects=False) as client:
                repo = repository(settings, client)
                if review.kind == "export":
                    outcome = export_review(session, review, job, settings, repo)
                elif review.kind == "import":
                    outcome = import_review(session, review, job, settings, repo)
                else:
                    raise Blocked(f"알 수 없는 검수 종류: {review.kind}")
            review.pull_number = outcome.get("pull_number") or review.pull_number
            review.pull_url = outcome.get("pull_url") or review.pull_url
            review.commit_sha = outcome.get("commit_sha") or review.commit_sha
            review.result = {**(review.result or {}), **outcome["result"]}
            review.state = "succeeded"
            review.error = None
            review.finished_at = utcnow()
            session.commit()
        return {"status": "succeeded"}
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 행에 남기고 사람이 보게 합니다.
        known = isinstance(exc, Blocked | GitHubError | ValueError)
        with factory() as session:
            review = session.get(SubtitleReview, review_uuid)
            review.state = "failed"
            review.error = (
                str(exc)
                if known
                else f"{type(exc).__name__}: 검수 요청 실패. 설정과 저장소 권한을 확인하세요."
            )
            review.finished_at = utcnow()
            session.commit()
        return {"status": "failed"}
