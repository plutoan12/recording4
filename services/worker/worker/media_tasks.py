"""Durable free/local media processing. Paid providers are not called here."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import func, select, update

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Artifact, MediaTask, SourceAsset, TranscriptSegment, utcnow
from adminapi.storage import get_storage
from pipeline.cuts import keep_spans, kept_seconds, within
from pipeline.editing import Cue, EditSpec
from pipeline.overlap import flag_overlaps, overlap_regions
from pipeline.speakers import SpeakerTurn, assign_speakers, speaker_totals
from worker.analysis import (
    MissingDependency,
    SyncOptions,
    align_text,
    detect_scenes,
    diarize,
    silence_spans,
    sync_subtitles,
    transcribe,
    vad_spans,
)
from worker.celery_app import celery_app
from worker.faces import MissingDependency as FacesMissing
from worker.faces import suggest as suggest_focus_point
from worker.media import ProbeError, probe
from worker.rendering import render_clip, render_preview
from worker.subtitle_rules import rules_from_settings


def source_audio(source: Path) -> bool | None:
    """원본에 소리가 있는지. 알 수 없으면 None이고, 그때는 있다고 보고 갑니다."""
    try:
        return probe(str(source)).has_audio
    except (ProbeError, OSError):
        return None


def background_music(edit: EditSpec, directory: Path, storage) -> Path | None:  # noqa: ANN001
    """배경음악으로 쓸 원본을 내려받습니다. 고르지 않았으면 None입니다."""
    if edit.music_asset_id is None:
        return None
    with get_session_factory()() as session:
        asset = session.get(SourceAsset, edit.music_asset_id)
        if asset is None or asset.upload_state != "verified":
            raise ValueError("배경음악으로 쓸 검사 통과한 원본을 찾을 수 없습니다.")
        key = asset.storage_key
    path = directory / "music.media"
    storage.download_file(key, path)
    return path


def latest_transcript(session, task_uuid) -> list[Cue]:  # noqa: ANN001
    """그 원본의 최신 대본 자막. 없으면 빈 목록입니다."""
    task = session.get(MediaTask, task_uuid)
    version = session.scalar(
        select(func.max(TranscriptSegment.transcript_version)).where(
            TranscriptSegment.source_asset_id == task.source_asset_id
        )
    )
    if not version:
        return []
    rows = session.scalars(
        select(TranscriptSegment)
        .where(
            TranscriptSegment.source_asset_id == task.source_asset_id,
            TranscriptSegment.transcript_version == version,
        )
        .order_by(TranscriptSegment.start_seconds)
    )
    return [Cue(start=float(r.start_seconds), end=float(r.end_seconds), text=r.text) for r in rows]


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
                # 이 규칙을 결과에 남깁니다. 설정을 렌더 뒤에 바꾸면 자막 파일이
                # 영상에 구워진 자막과 달라지는데, 사람은 같은 자막이라고 믿고
                # 올립니다. 남겨 두면 내보내기가 그때 쓴 규칙으로 만듭니다.
                rules = rules_from_settings(settings)
                edit = EditSpec.model_validate(spec)
                render_clip(
                    source,
                    output,
                    edit,
                    rules=rules,
                    music=background_music(edit, directory, storage),
                    has_audio=source_audio(source),
                )
                with output.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                output_key = f"renders/{task_id}/{attempt}.mp4"
                storage.upload_file(output_key, output, "video/mp4")
                result = {"storage_key": output_key, "subtitle_rules": asdict(rules)}
            elif kind == "silence":
                # 남길 구간을 **제안**만 합니다. 여기서 영상을 자르지 않습니다.
                speech = vad_spans(source) or silence_spans(source)
                seconds = float(probe(str(source)).duration_seconds)
                kept = keep_spans(
                    speech,
                    seconds,
                    margin=float(spec.get("margin", 0.2)),
                    min_cut=float(spec.get("min_cut", 0.5)),
                    min_clip=float(spec.get("min_clip", 0.4)),
                )
                if spec.get("start") is not None or spec.get("end") is not None:
                    kept = within(
                        kept, float(spec.get("start") or 0), float(spec.get("end") or seconds)
                    )
                result = {
                    "segments": [{"start": start, "end": end} for start, end in kept],
                    "kept_seconds": kept_seconds(kept),
                    "source_seconds": round(seconds, 3),
                    "removed_seconds": round(seconds - kept_seconds(kept), 3),
                    "speech_spans": len(speech),
                }
            elif kind == "preview":
                output = directory / "preview.png"
                render_preview(
                    source,
                    output,
                    EditSpec.model_validate(spec["spec"]),
                    float(spec["at"]),
                    rules=rules_from_settings(settings),
                )
                output_key = f"previews/{task_id}/{attempt}.png"
                storage.upload_file(output_key, output, "image/png")
                result = {"storage_key": output_key, "at": float(spec["at"])}
            elif kind == "scenes":
                result = {"scenes": detect_scenes(source)}
            elif kind == "faces":
                # 제안만 만듭니다. focus_x를 여기서 바꾸지 않습니다. 검출기가
                # 틀리면 사람이 맞춘 값을 망칩니다.
                result = {"focus": asdict(suggest_focus_point(source))}
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
            elif kind == "sync":
                # 글자는 그대로 두고 시각만 통째로 옮깁니다. 얼마나 옮겼는지 남깁니다.
                with get_session_factory()() as session:
                    rows = latest_transcript(session, task_uuid)
                if not rows:
                    raise ValueError("보정할 대본이 없습니다.")
                cues, report = sync_subtitles(
                    source,
                    rows,
                    SyncOptions(
                        fix_framerate=settings.sync_fix_framerate,
                        max_offset_seconds=settings.sync_max_offset_seconds,
                        vad=settings.sync_vad,
                    ),
                )
                result = {"sync": report}
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
                    # 겹말 구간은 화자 구간에서 바로 나옵니다. 여기서 같이 찍어 두면
                    # 사람이 "이 자막은 겹쳐 말해 못 믿는다"를 편집 화면에서 봅니다.
                    regions = overlap_regions(turns)
                    result = {
                        "speakers": speaker_totals(turns),
                        "count": len(rows),
                        "overlap_regions": len(regions),
                        "overlap_seconds": round(sum(e - s for s, e in regions), 3),
                    }
                    if rows:
                        cues = [
                            Cue(
                                start=float(r.start_seconds),
                                end=float(r.end_seconds),
                                text=r.text,
                            )
                            for r in rows
                        ]
                        labels = assign_speakers(cues, turns)
                        flags = flag_overlaps(cues, regions)
                        for row, label, flag in zip(rows, labels, flags, strict=True):
                            session.add(
                                TranscriptSegment(
                                    source_asset_id=task.source_asset_id,
                                    transcript_version=version + 1,
                                    start_seconds=row.start_seconds,
                                    end_seconds=row.end_seconds,
                                    text=row.text,
                                    speaker=label,
                                    overlap=flag,
                                )
                            )
                        result["transcript_version"] = version + 1
                        result["labeled"] = sum(1 for label in labels if label)
                        result["overlapped"] = sum(1 for flag in flags if flag)
                elif kind in ("transcribe", "align", "sync"):
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
                    result = {**result, "transcript_version": version, "count": len(cues)}
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
                # 설치·설정이 빠졌다는 안내는 모듈마다 자기 예외를 씁니다.
                # 하나만 적어 두면 나머지는 "처리 실패"로 뭉개져서 무엇을
                # 설치해야 하는지 알 수 없습니다.
                task.error = (
                    str(exc)
                    if isinstance(exc, MissingDependency | FacesMissing)
                    else f"{type(exc).__name__}: 처리 실패. 워커 설정과 입력을 확인하세요."
                )
                task.finished_at = utcnow()
                session.commit()
        return {"status": "failed"}
