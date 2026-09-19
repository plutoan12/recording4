"""One durable step per queue delivery; checkpoints precede all paid calls."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import uuid
from dataclasses import asdict
from datetime import timedelta
from decimal import ROUND_UP, Decimal
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import or_, select, update

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import (
    Artifact,
    Budget,
    BudgetReservation,
    Job,
    SourceAsset,
    StageRun,
    TranscriptSegment,
    utcnow,
)
from adminapi.outbox import enqueue
from adminapi.services.budget import reserve, settle
from adminapi.storage import get_storage
from pipeline.budget import BudgetShortfall
from pipeline.editing import Cue, clip_cues
from pipeline.hashing import StageInputs
from pipeline.states import JobState, StageRunState
from pipeline.workflow import WorkflowOptions, rendered_cues, rendered_language
from worker.analysis import transcribe
from worker.celery_app import celery_app
from worker.composition import TimingError, compose_dub, mix_speech, render_final
from worker.providers import ElevenLabsSpeech, GoogleTranslator, SyncLipsync
from worker.separation import MissingDependency as SeparationMissing
from worker.separation import separate_background
from worker.subtitle_rules import rules_from_settings


class Blocked(RuntimeError):
    pass


def separated_background(source: Path, directory: Path, settings) -> Path | None:  # noqa: ANN001
    """원본에서 목소리를 뺀 소리. 분리를 못 하면 None이고, 더빙은 그대로 갑니다.

    분리가 안 된다고 더빙 전체를 멈추지 않습니다. 배경음이 없는 결과가 나올
    뿐이고, 그건 이 설정을 켜기 전과 같습니다. 대신 **왜 없는지 기록에
    남깁니다.** 조용히 넘어가면 설정을 켜 놓고도 배경음이 없는 이유를 알 수
    없습니다.
    """
    output = directory / "background.wav"
    try:
        return separate_background(source, output, device=settings.whisper_device).background
    except SeparationMissing as exc:
        logging.getLogger(__name__).warning("배경음 분리를 건너뜁니다: %s", exc)
        return None


class RemoteTerminalFailure(Blocked):
    pass


def continuation(session, job_id, delay=0):
    enqueue(
        session,
        topic="job.step",
        payload={"job_id": str(job_id)},
        dedupe_key=f"job.step:{job_id}:{uuid.uuid4()}",
        delay_seconds=delay,
    )


def next_step(data: dict, options: WorkflowOptions) -> str | None:
    if "cues" not in data:
        return "transcribe"
    if options.audio_mode == "original":
        return None if "artifact_id" in data else "render"
    if len(data.get("translated", [])) < len(data["cues"]):
        return f"translate:{len(data.get('translated', []))}"
    if len(data.get("voices", [])) < len(data["cues"]):
        return f"dub:{len(data.get('voices', []))}"
    if "audio_key" not in data:
        return "mix"
    if "base_key" not in data:
        return "compose"
    if options.lipsync and "lipsync_key" not in data:
        return "lipsync"
    return None if "artifact_id" in data else "render"


def tts_inputs(data, options, settings):
    cue = data["translated"][len(data.get("voices", []))]
    return StageInputs(
        stage="tts",
        provider="elevenlabs",
        model_id=settings.tts_model,
        model_version=settings.tts_model_version,
        voice_id=options.voice_id,
        language=data["target"],
        parameters={
            "text": cue["text"],
            "voice_version": settings.tts_voice_version,
            "format": "mp3_44100_128",
        },
        contract_version=2,
    )


def cached_voice(session, job, inputs, options, settings):
    automatic = inputs.reusable and bool(settings.tts_voice_version)
    if not automatic and not options.reuse_from_job_id:
        return None
    query = (
        select(StageRun)
        .join(Job, Job.id == StageRun.job_id)
        .where(
            StageRun.state == StageRunState.SUCCEEDED,
            StageRun.input_hash == inputs.digest(),
            StageRun.provider == "elevenlabs",
            Job.created_by_id == job.created_by_id,
            Job.id != job.id,
        )
    )
    if not automatic:
        query = query.where(
            Job.id == options.reuse_from_job_id, Job.source_asset_id == job.source_asset_id
        )
    else:
        query = query.where(StageRun.reusable.is_(True))
    for candidate in session.scalars(query.order_by(StageRun.finished_at.desc()).limit(20)):
        key = candidate.outputs.get("voice_key")
        if key and candidate.outputs.get("voice_checksum") and get_storage().head(key):
            return candidate
    return None


def voice_output(data, key, checksum):
    return {
        "voice_key": key,
        "voice_checksum": checksum,
        "voices": data.get("voices", []) + [key],
        "voice_checksums": data.get("voice_checksums", [None] * len(data.get("voices", [])))
        + [checksum],
    }


def paid_estimate(name, data, options, settings):
    if name.startswith("translate:"):
        if options.translated_cues is not None or options.source_language == data.get("target"):
            return None
        rate = settings.translate_usd_per_1k_chars
        if not settings.google_cloud_project:
            raise Blocked("Google Cloud 프로젝트와 인증을 설정하세요.")
        count = sum(len(c["text"]) for c in translation_batch(data))
        units = Decimal(count) / 1000
    elif name.startswith("dub:"):
        rate = settings.tts_usd_per_1k_chars
        if not settings.elevenlabs_api_key or not options.voice_id:
            raise Blocked("ElevenLabs API 키와 작업의 음성을 설정하세요.")
        count = len(data["translated"][len(data.get("voices", []))]["text"])
        if count > 5000:
            raise Blocked("더빙 문장을 5,000자 이하로 나누세요.")
        units = Decimal(count) / 1000
    elif name == "lipsync":
        rate = settings.lipsync_usd_per_second
        if not settings.sync_api_key:
            raise Blocked("Sync API 키를 설정하세요.")
        units = Decimal(str(data["duration"]))
    else:
        return None
    if not settings.paid_processing_enabled:
        raise Blocked("서버의 유료 처리 설정이 꺼져 있습니다.")
    if rate is None or rate <= 0:
        raise Blocked("해당 공급자의 보수적인 단가 상한을 서버에 설정하세요.")
    return (units * rate).quantize(Decimal("0.0001"), rounding=ROUND_UP)


def translation_batch(data):
    batch, size = [], 0
    for cue in data["cues"][len(data.get("translated", [])) :]:
        if batch and (size + len(cue["text"]) > 25000 or len(batch) >= 100):
            break
        batch.append(cue)
        size += len(cue["text"])
    return batch


def hold_budgets(session, job, stage, estimate):
    now = utcnow()
    job_budget = session.scalar(
        select(Budget).where(Budget.scope == "job", Budget.scope_ref == str(job.id))
    )
    monthly = session.scalar(
        select(Budget).where(
            Budget.scope == "monthly",
            Budget.scope_ref == "global",
            Budget.period_start <= now,
            Budget.period_end > now,
            Budget.currency == "USD",
        )
    )
    if job_budget is None or monthly is None:
        raise Blocked("작업 예산과 이번 달 공통 예산을 등록하세요.")
    for budget in sorted([job_budget, monthly], key=lambda b: str(b.id)):
        reserve(session, budget_id=budget.id, estimate=estimate, stage_run_id=stage.id)


def finish_holds(session, stage):
    for hold in session.scalars(
        select(BudgetReservation).where(BudgetReservation.stage_run_id == stage.id)
    ):
        # No final bill is returned. Account for the configured upper bound.
        settle(session, hold.id, None)


def upload(storage, key, path, content_type):
    storage.upload_file(key, path, content_type)
    return key


def execute_step(name, options, data, asset, directory, stage_id, remote_id, save_remote):
    storage, settings = get_storage(), get_settings()
    prefix = f"workflow/{stage_id}"
    source = directory / "source.media"
    if name in ("transcribe", "compose", "render"):
        key = (
            (data.get("lipsync_key") or data.get("base_key") or asset.storage_key)
            if name == "render"
            else asset.storage_key
        )
        storage.download_file(key, source)
    if name == "transcribe":
        if options.transcript is not None:
            cues = options.transcript
        else:
            with get_session_factory()() as session:
                rows = list(
                    session.scalars(
                        select(TranscriptSegment)
                        .where(TranscriptSegment.source_asset_id == asset.id)
                        .order_by(
                            TranscriptSegment.transcript_version.desc(),
                            TranscriptSegment.start_seconds,
                        )
                    )
                )
                latest = rows[0].transcript_version if rows else None
                cues = [
                    Cue(start=float(r.start_seconds), end=float(r.end_seconds), text=r.text)
                    for r in rows
                    if r.transcript_version == latest
                ]
            if not cues:
                cues = transcribe(
                    source,
                    model=settings.whisper_model,
                    language=options.source_language,
                    device=settings.whisper_device,
                )
        if options.clip:
            cues = clip_cues(cues, options.clip.start, options.clip.end)
        cues = sorted(cues, key=lambda c: c.start)
        if any(c.end > data["duration"] for c in cues):
            raise Blocked("대본 구간이 출력 길이를 넘습니다. 대본을 수정하세요.")
        if not cues and options.audio_mode == "dub":
            raise Blocked("음성이 감지되지 않았습니다. 대본을 입력하세요.")
        return {"cues": [c.model_dump() for c in cues]}
    if name.startswith("translate:"):
        batch = translation_batch(data)
        offset = len(data.get("translated", []))
        if options.translated_cues is not None:
            supplied = options.translated_cues
            if len(supplied) != len(data["cues"]):
                raise Blocked("수정 번역과 대본의 문장 개수가 다릅니다.")
            texts = [c.text for c in supplied[offset : offset + len(batch)]]
        elif options.source_language == data["target"]:
            texts = [c["text"] for c in batch]
        else:
            texts = GoogleTranslator(settings.google_cloud_project, allow_paid=True).translate(
                [c["text"] for c in batch], data["target"], options.source_language
            )
        return {
            "translated": data.get("translated", [])
            + [{**cue, "text": text} for cue, text in zip(batch, texts, strict=True)]
        }
    if name.startswith("dub:"):
        cue = data["translated"][len(data.get("voices", []))]
        voice = directory / "voice.mp3"
        with httpx.Client() as client:
            ElevenLabsSpeech(
                settings.elevenlabs_api_key, client=client, allow_paid=True
            ).synthesize(cue["text"], options.voice_id, voice, model=settings.tts_model)
        key = upload(storage, f"{prefix}/voice.mp3", voice, "audio/mpeg")
        return voice_output(data, key, hashlib.sha256(voice.read_bytes()).hexdigest())
    if name == "mix":
        paths = []
        for i, key in enumerate(data["voices"]):
            path = directory / f"voice-{i}.mp3"
            storage.download_file(key, path)
            expected = data.get("voice_checksums", [None] * len(data["voices"]))[i]
            if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise Blocked("저장된 더빙 음성이 변경되었습니다. 파일을 확인하세요.")
            paths.append(path)
        output = directory / "speech.wav"
        aligned = mix_speech(
            paths, [Cue.model_validate(c) for c in data["translated"]], data["duration"], output
        )
        return {
            "audio_key": upload(storage, f"{prefix}/speech.wav", output, "audio/wav"),
            "aligned": [c.model_dump() for c in aligned],
        }
    if name == "compose":
        audio = directory / "speech.wav"
        storage.download_file(data["audio_key"], audio)
        output = directory / "dubbed.mp4"
        # 배경음을 켜지 않으면 원본 오디오가 통째로 사라집니다. 음악 위에서
        # 말하는 영상이면 더빙본은 말만 남습니다.
        background = (
            separated_background(source, directory, settings)
            if settings.background_audio_enabled
            else None
        )
        compose_dub(
            source,
            audio,
            output,
            data["start"],
            data["duration"],
            background=background,
            background_gain_db=settings.background_gain_db,
        )
        return {
            "base_key": upload(storage, f"{prefix}/dubbed.mp4", output, "video/mp4"),
            "background": bool(background),
        }
    if name == "lipsync":
        with httpx.Client(follow_redirects=False) as client:
            adapter = SyncLipsync(settings.sync_api_key, client=client, allow_paid=True)
            if not remote_id:
                video_url = storage.presigned_get_url(data["base_key"], 3600)
                audio_url = storage.presigned_get_url(data["audio_key"], 3600)
                if any(urlparse(url).scheme != "https" for url in (video_url, audio_url)):
                    raise Blocked("립싱크에는 외부에서 접근 가능한 HTTPS 저장소가 필요합니다.")
                remote_id = adapter.submit(video_url, audio_url)
                save_remote(remote_id)
            result = adapter.status(remote_id)
            if result["status"] in ("FAILED", "REJECTED"):
                raise RemoteTerminalFailure(
                    "립싱크가 종료 실패했습니다. 공급자 청구를 확인·정산한 후 재개하세요."
                )
            if result["status"] != "COMPLETED":
                return {"waiting": True}
            url = result.get("outputUrl")
            if not url or urlparse(url).scheme != "https":
                raise Blocked("립싱크 결과 URL이 유효하지 않습니다.")
            output = directory / "synced.mp4"
            # URL originates from the authenticated provider, never from a client request.
            with client.stream("GET", url, timeout=120) as response:
                response.raise_for_status()
                total = 0
                with output.open("wb") as f:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > settings.max_source_bytes:
                            raise Blocked("립싱크 결과가 파일 크기 제한을 넘습니다.")
                        f.write(chunk)
            return {"lipsync_key": upload(storage, f"{prefix}/synced.mp4", output, "video/mp4")}
    if name == "render":
        output = directory / "final.mp4"
        dubbed = options.audio_mode == "dub"
        # 자막이 어느 언어인지에 따라 표시 규칙이 다릅니다. 번역한 자막이면
        # 목표 언어, 원본 대본 그대로면 원본 언어입니다.
        language = rendered_language(data, options)
        # 이 규칙을 결과에 남깁니다. 설정을 렌더 뒤에 바꾸면 자막 파일이 영상에
        # 구워진 자막과 달라지는데, 사람은 같은 자막이라고 믿고 올립니다.
        # 남겨 두면 내보내기가 그때 쓴 규칙으로 만듭니다(편집본 경로와 같습니다).
        rules = rules_from_settings(settings, language)
        render_final(
            source,
            output,
            cues=[Cue.model_validate(c) for c in rendered_cues(data)],
            duration=data["duration"],
            start=0 if dubbed else data["start"],
            clip=options.clip,
            width=asset.width or 1920,
            height=asset.height or 1080,
            rules=rules,
        )
        with output.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        return {
            "final_key": upload(storage, f"{prefix}/final.mp4", output, "video/mp4"),
            "checksum": checksum,
            "subtitle_rules": asdict(rules),
        }
    raise ValueError(f"알 수 없는 단계: {name}")


@celery_app.task(name="worker.workflow_tasks.run_job", soft_time_limit=3500, time_limit=3600)
def run_job(job_id: str):
    factory, token = get_session_factory(), str(uuid.uuid4())
    job_uuid = uuid.UUID(job_id)
    with factory() as session:
        claimed = session.execute(
            update(Job)
            .where(
                Job.id == job_uuid,
                Job.state.in_([JobState.QUEUED, JobState.PROCESSING]),
                or_(Job.lease_until.is_(None), Job.lease_until < utcnow()),
            )
            .values(
                lease_token=token,
                lease_until=utcnow() + timedelta(hours=2),
                state=JobState.PROCESSING,
            )
        )
        session.commit()
        if not claimed.rowcount:
            return {"status": "not_runnable"}
    stage_id = None
    try:
        with factory() as session:
            job = session.get(Job, job_uuid)
            asset = session.get(SourceAsset, job.source_asset_id)
            options = WorkflowOptions.model_validate(job.workflow_config)
            duration = float(asset.duration_seconds or 0)
            if duration <= 0:
                raise Blocked("원본 길이를 먼저 검사하세요.")
            data = dict(job.workflow_data) or {
                "start": options.clip.start if options.clip else 0,
                "duration": options.clip.end - options.clip.start if options.clip else duration,
                "target": job.target_language,
            }
            name = next_step(data, options)
            if name is None:
                job.state = JobState.REVIEW_REQUIRED
                job.state_reason = None
                job.lease_token = job.lease_until = None
                session.commit()
                return {"status": "review_required"}
            job.current_stage = name
            job.workflow_data = data
            session.commit()
            stage = session.scalar(
                select(StageRun)
                .where(StageRun.job_id == job.id, StageRun.stage == name)
                .order_by(StageRun.attempt.desc())
            )
            if (
                stage
                and stage.state == StageRunState.RUNNING
                and stage.outputs.get("invoked")
                and not stage.provider_job_id
            ):
                raise Blocked(
                    "유료 요청 결과가 불명확합니다. 공급자 내역 확인 후 단계 정산이 필요합니다."
                )
            if stage and stage.state == StageRunState.FAILED and stage.outputs.get("invoked"):
                raise Blocked("유료 요청 결과를 확인하고 단계 정산을 완료하세요.")
            remote = (
                stage.provider_job_id if stage and stage.state != StageRunState.FAILED else None
            )
            settings = get_settings()
            inputs = tts_inputs(data, options, settings) if name.startswith("dub:") else None
            if stage is None or stage.state == StageRunState.FAILED:
                attempt = stage.attempt + 1 if stage else 1
                stage = StageRun(
                    job_id=job.id,
                    source_asset_id=asset.id,
                    stage=name,
                    input_hash=inputs.digest()
                    if inputs
                    else hashlib.sha256(
                        json.dumps([job.workflow_config, name], sort_keys=True).encode()
                    ).hexdigest(),
                    reusable=bool(inputs and inputs.reusable and settings.tts_voice_version),
                    provider="elevenlabs" if inputs else None,
                    attempt=attempt,
                    state=StageRunState.PENDING,
                )
                session.add(stage)
                session.flush()
            stage_id = stage.id
            if stage.state == StageRunState.SUCCEEDED:
                job.workflow_data = {**data, **stage.outputs}
                continuation(session, job.id)
                job.lease_token = job.lease_until = None
                session.commit()
                return {"status": "reused"}
            cached = cached_voice(session, job, inputs, options, settings) if inputs else None
            if cached:
                result = voice_output(
                    data, cached.outputs["voice_key"], cached.outputs["voice_checksum"]
                )
                result["reused_from_stage_id"] = str(cached.id)
                stage.outputs = result
                stage.state = StageRunState.SUCCEEDED
                stage.finished_at = utcnow()
                stage.estimated_cost = stage.actual_cost = Decimal("0")
                job.workflow_data = {**data, **result}
                continuation(session, job.id)
                job.lease_token = job.lease_until = None
                session.commit()
                return {"status": "reused", "stage": name}
            estimate = None if remote else paid_estimate(name, data, options, settings)
            if estimate is not None and not stage.outputs.get("invoked"):
                hold_budgets(session, job, stage, estimate)
                stage.estimated_cost = estimate
                stage.outputs = {"invoked": True}
            stage.state = StageRunState.RUNNING
            stage.started_at = stage.started_at or utcnow()
            session.commit()

        def save_remote(remote_id):
            with factory() as session:
                stage = session.get(StageRun, stage_id)
                stage.provider_job_id = remote_id
                session.commit()

        with tempfile.TemporaryDirectory(prefix="r4-step-") as directory:
            result = execute_step(
                name, options, data, asset, Path(directory), stage_id, remote, save_remote
            )
        with factory() as session:
            job = session.scalar(select(Job).where(Job.id == job_uuid).with_for_update())
            if job.lease_token != token:
                return {"status": "stale"}
            stage = session.get(StageRun, stage_id)
            if result.get("waiting"):
                continuation(session, job.id, 30)
            else:
                if name == "render":
                    artifact = Artifact(
                        job_id=job.id,
                        kind="video",
                        storage_key=result["final_key"],
                        checksum=result["checksum"],
                        render_settings=job.workflow_config,
                    )
                    session.add(artifact)
                    session.flush()
                    result["artifact_id"] = str(artifact.id)
                stage.outputs = result
                stage.state = StageRunState.SUCCEEDED
                stage.finished_at = utcnow()
                finish_holds(session, stage)
                job.workflow_data = {**data, **result}
                continuation(session, job.id)
            job.lease_token = job.lease_until = None
            job.state_reason = None
            session.commit()
        return {"status": "waiting" if result.get("waiting") else "step_complete", "stage": name}
    except Exception as exc:
        with factory() as session:
            job = session.get(Job, job_uuid)
            if job.lease_token == token:
                stage = session.get(StageRun, stage_id) if stage_id else None
                if stage and (not stage.provider_job_id or isinstance(exc, RemoteTerminalFailure)):
                    stage.state = StageRunState.FAILED
                    stage.error = type(exc).__name__
                    if isinstance(exc, RemoteTerminalFailure):
                        stage.outputs = {**stage.outputs, "terminal_failure": True}
                known = isinstance(exc, Blocked | BudgetShortfall | TimingError)
                job.state = (
                    JobState.BLOCKED
                    if known or (stage and stage.outputs.get("invoked"))
                    else JobState.FAILED
                )
                job.state_reason = (
                    str(exc)
                    if known
                    else f"{type(exc).__name__}: 단계 실행 실패. 설정과 공급자 상태를 확인하세요."
                )
                job.lease_token = job.lease_until = None
                session.commit()
        return {"status": "blocked_or_failed"}
