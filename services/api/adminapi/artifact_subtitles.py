"""결과물의 자막을 파일 글자로 만듭니다. 내려받기와 게시가 함께 씁니다.

자막 데이터는 만든 경로마다 다른 곳에 있습니다. 숏폼 편집본은 렌더 요청의 설정
사본(`MediaTask.settings`)에, 번역·더빙 작업은 `Job.workflow_data`에 있습니다.
어느 쪽이든 렌더가 그때 쓴 표시 규칙(`subtitle_rules` 기록)으로 계산하므로 파일
자막과 화면 자막의 줄이 같습니다.

자막이 없거나 아직 만들 단계가 아니면 이유를 담은 `Missing`을 돌려줍니다. 부르는
쪽이 HTTP 응답으로 바꾸거나 기록에 남깁니다. 여기서는 예외를 던지지 않습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select

from adminapi.models import Artifact, ClipEdit, Job, MediaTask
from adminapi.subtitle_rules import rules_from_record
from pipeline.editing import Cue, EditSpec
from pipeline.subtitle_files import SubtitleFormat, clip_subtitle_file, subtitle_file
from pipeline.workflow import WorkflowOptions, rendered_cues, rendered_language

# 언어를 모를 때 쓰는 표시입니다. 자막 트랙의 언어로는 쓸 수 없습니다.
UNKNOWN_LANGUAGE = "und"


@dataclass(frozen=True, slots=True)
class Subtitles:
    """자막 파일 글자와, 그것을 무엇으로 만들었는지."""

    text: str
    language: str | None
    rules_source: str  # rendered=렌더 때 쓴 규칙, settings=지금 설정


@dataclass(frozen=True, slots=True)
class Missing:
    """자막을 만들 수 없는 이유. 사람이 읽는 말입니다."""

    reason: str


def clip_subtitles(session, clip_edit_id, subtitle_format: SubtitleFormat) -> Subtitles | Missing:  # noqa: ANN001
    """숏폼 편집본 자막. 출력 구간은 편집본의 시작·끝입니다."""
    # 편집본의 자막은 렌더 요청의 설정 사본에만 있습니다. 대본은 그 뒤로 바뀔 수
    # 있으므로 최신 대본이 아니라 이 사본을 씁니다.
    task = session.scalar(
        select(MediaTask)
        .where(MediaTask.clip_edit_id == clip_edit_id, MediaTask.kind == "render")
        .order_by(MediaTask.created_at.desc())
        .limit(1)
    )
    if task is None:
        return Missing("편집본의 렌더 요청을 찾을 수 없습니다.")
    rules, source = rules_from_record((task.result or {}).get("subtitle_rules"))
    try:
        spec = EditSpec.model_validate(task.settings)
    except ValidationError:
        return Missing("저장된 편집 설정을 읽을 수 없습니다. 렌더 기록을 확인하세요.")
    text = clip_subtitle_file(spec, subtitle_format, rules)
    if not text.strip():
        return Missing("이 편집본에는 내보낼 자막이 없습니다.")
    clip = session.get(ClipEdit, clip_edit_id)
    language = clip.output_language if clip else None
    return Subtitles(text, None if language == UNKNOWN_LANGUAGE else language, source)


def job_subtitles(job: Job, subtitle_format: SubtitleFormat) -> Subtitles | Missing:
    """번역·더빙 작업 자막. 출력 구간은 0초부터 출력 길이까지입니다."""
    data = job.workflow_data or {}
    rows, duration = rendered_cues(data), data.get("duration")
    if not rows or not duration:
        return Missing("아직 자막이 없습니다. 대본 단계를 먼저 끝내세요.")
    try:
        cues = [Cue.model_validate(row) for row in rows]
    except ValidationError:
        return Missing("저장된 자막을 읽을 수 없습니다. 작업 기록을 확인하세요.")
    # 렌더가 그때 쓴 규칙으로 계산합니다. 기록이 없으면(아직 렌더하지 않은 작업)
    # 지금 설정을 쓰되 렌더와 같은 언어 규칙으로 만듭니다.
    language = rendered_language(data, WorkflowOptions.model_validate(job.workflow_config))
    rules, source = rules_from_record(data.get("subtitle_rules"), language)
    text = subtitle_file(cues, 0, float(duration), subtitle_format, rules)
    if not text.strip():
        return Missing("내보낼 자막이 없습니다.")
    return Subtitles(text, None if language == UNKNOWN_LANGUAGE else language, source)


def artifact_subtitles(
    session, artifact: Artifact, subtitle_format: SubtitleFormat
) -> Subtitles | Missing:  # noqa: ANN001
    """결과물에 구워진 자막. 편집본과 작업 중 그 결과물을 만든 쪽에서 찾습니다."""
    if artifact.clip_edit_id:
        return clip_subtitles(session, artifact.clip_edit_id, subtitle_format)
    if artifact.job_id:
        job = session.get(Job, artifact.job_id)
        if job is None:
            return Missing("결과물의 작업을 찾을 수 없습니다.")
        return job_subtitles(job, subtitle_format)
    return Missing("결과물에 연결된 편집본이나 작업이 없습니다.")


def artifact_burns_subtitles(session, artifact: Artifact) -> bool:
    """Use the immutable render request; legacy artifacts have burned captions."""
    if artifact.clip_edit_id:
        task = session.scalar(
            select(MediaTask)
            .where(MediaTask.clip_edit_id == artifact.clip_edit_id, MediaTask.kind == "render")
            .order_by(MediaTask.created_at.desc())
            .limit(1)
        )
        return (task.settings or {}).get("burn_subtitles", True) if task else True
    if artifact.job_id:
        job = session.get(Job, artifact.job_id)
        return (job.workflow_config or {}).get("burn_subtitles", True) if job else True
    return True
