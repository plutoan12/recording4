"""Durable free/local media processing. Paid providers are not called here."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import func, select, update

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Artifact, MediaTask, SourceAsset, TranscriptSegment, utcnow
from adminapi.storage import get_storage
from pipeline.editing import Cue, EditSpec
from pipeline.speakers import SpeakerTurn, assign_speakers, speaker_totals
from worker.analysis import MissingDependency, align_text, detect_scenes, diarize, transcribe
from worker.celery_app import celery_app
from worker.rendering import render_clip
from worker.subtitle_rules import rules_from_settings


@celery_app.task(name="worker.media_tasks.run_media", soft_time_limit=3500, time_limit=3600)
def run_media(task_id: str) -> dict:
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
        source_key, spec, kind, attempt = asset.storage_key, task.settings, task.kind, task.attempt

    try:
        storage = get_storage()
        with tempfile.TemporaryDirectory(prefix="r4-media-") as temp:
            directory = Path(temp)
            source = directory / "source.media"
            storage.download_file(source_key, source)
            result = {}
            checksum = None
            settings = get_settings()
            cues: list[Cue] = []
            turns: list[SpeakerTurn] = []
            if kind == "render":
                output = directory / "clip.mp4"
                render_clip(
                    source,
                    output,
                    EditSpec.model_validate(spec),
                    rules=rules_from_settings(settings),
                )
                with output.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                output_key = f"renders/{task_id}/{attempt}.mp4"
                storage.upload_file(output_key, output, "video/mp4")
                result = {"storage_key": output_key}
            elif kind == "scenes":
                result = {"scenes": detect_scenes(source)}
            elif kind == "diarize":
                # 누가 말했는지만 찾습니다. 대본 글자는 건드리지 않습니다.
                turns = diarize(
                    source,
                    token=settings.hf_token,
                    device=settings.whisper_device,
                    min_speakers=spec.get("min_speakers"),
                    max_speakers=spec.get("max_speakers"),
                )
                result = {"speakers": speaker_totals(turns)}
            elif kind == "align":
                # 전사가 아니라 정렬입니다. 대본 글자는 그대로 두고 시각만 찾습니다.
                cues = align_text(
                    source,
                    spec["text"],
                    model=settings.whisper_model,
                    language=spec.get("language"),
                    device=settings.whisper_device,
                )
                result = {"cues": [c.model_dump() for c in cues]}
            else:
                cues = transcribe(
                    source,
                    model=settings.whisper_model,
                    language=spec.get("language"),
                    device=settings.whisper_device,
                )
                result = {"cues": [c.model_dump() for c in cues]}

            with factory() as session:
                task = session.scalar(
                    select(MediaTask).where(MediaTask.id == task_uuid).with_for_update()
                )
                if task.attempt != attempt or task.state != "running":
                    return {"status": "superseded_attempt"}
                if kind == "render":
                    artifact = Artifact(
                        clip_edit_id=task.clip_edit_id,
                        kind="short_video",
                        storage_key=result["storage_key"],
                        checksum=checksum,
                        render_settings=spec,
                    )
                    session.add(artifact)
                    session.flush()
                    result["artifact_id"] = str(artifact.id)
                elif kind == "diarize":
                    # 기존 대본을 그대로 두고 화자만 붙인 새 버전을 만듭니다.
                    session.scalar(
                        select(SourceAsset)
                        .where(SourceAsset.id == task.source_asset_id)
                        .with_for_update()
                    )
                    version = session.scalar(
                        select(func.max(TranscriptSegment.transcript_version)).where(
                            TranscriptSegment.source_asset_id == task.source_asset_id
                        )
                    )
                    rows = (
                        list(
                            session.scalars(
                                select(TranscriptSegment)
                                .where(
                                    TranscriptSegment.source_asset_id == task.source_asset_id,
                                    TranscriptSegment.transcript_version == version,
                                )
                                .order_by(TranscriptSegment.start_seconds)
                            )
                        )
                        if version
                        else []
                    )
                    result = {"speakers": speaker_totals(turns), "count": len(rows)}
                    if rows:
                        labels = assign_speakers(
                            [
                                Cue(
                                    start=float(r.start_seconds),
                                    end=float(r.end_seconds),
                                    text=r.text,
                                )
                                for r in rows
                            ],
                            turns,
                        )
                        for row, label in zip(rows, labels, strict=True):
                            session.add(
                                TranscriptSegment(
                                    source_asset_id=task.source_asset_id,
                                    transcript_version=version + 1,
                                    start_seconds=row.start_seconds,
                                    end_seconds=row.end_seconds,
                                    text=row.text,
                                    speaker=label,
                                )
                            )
                        result["transcript_version"] = version + 1
                        result["labeled"] = sum(1 for label in labels if label)
                elif kind in ("transcribe", "align"):
                    # Serialize transcript imports and STT completion on the source row.
                    session.scalar(
                        select(SourceAsset)
                        .where(SourceAsset.id == task.source_asset_id)
                        .with_for_update()
                    )
                    version = (
                        session.scalar(
                            select(func.max(TranscriptSegment.transcript_version)).where(
                                TranscriptSegment.source_asset_id == task.source_asset_id
                            )
                        )
                        or 0
                    ) + 1
                    for cue in cues:
                        session.add(
                            TranscriptSegment(
                                source_asset_id=task.source_asset_id,
                                transcript_version=version,
                                start_seconds=cue.start,
                                end_seconds=cue.end,
                                text=cue.text,
                            )
                        )
                    result = {"transcript_version": version, "count": len(cues)}
                task.state, task.result, task.finished_at = "succeeded", result, utcnow()
                session.commit()
                return {"status": "succeeded", **result}
    except Exception as exc:
        with factory() as session:
            task = session.get(MediaTask, task_uuid)
            if task and task.attempt == attempt and task.state == "running":
                task.state = "failed"
                # Exceptions from SDKs can contain credentials/URLs. Expose type only.
                # 설치 안내는 저희가 쓴 고정 문구라 그대로 보여 줍니다.
                task.error = (
                    str(exc)
                    if isinstance(exc, MissingDependency)
                    else f"{type(exc).__name__}: 처리 실패. 워커 설정과 입력을 확인하세요."
                )
                task.finished_at = utcnow()
                session.commit()
        return {"status": "failed"}
