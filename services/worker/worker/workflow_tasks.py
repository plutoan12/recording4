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
from sqlalchemy.exc import IntegrityError

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import (
    Artifact,
    Budget,
    BudgetReservation,
    Glossary,
    Job,
    SourceAsset,
    StageRun,
    TranscriptSegment,
    TranslationMemory,
    utcnow,
)
from adminapi.outbox import enqueue
from adminapi.services.budget import reserve, settle
from adminapi.storage import get_storage
from pipeline.batching import batch_starts
from pipeline.budget import BudgetShortfall
from pipeline.editing import Cue, clip_cues
from pipeline.glossary import apply_terms, missing_numbers, protect, restore, violations
from pipeline.hashing import StageInputs
from pipeline.languages import is_supported
from pipeline.states import JobState, StageRunState
from pipeline.translation_jobs import build_job
from pipeline.workflow import WorkflowOptions, rendered_cues, rendered_language
from worker.analysis import transcribe
from worker.celery_app import celery_app
from worker.composition import TimingError, compose_dub, mix_speech, render_final
from worker.providers import (
    TRANSLATE_PROMPT_VERSION,
    ClaudeTranslator,
    DeepLTranslator,
    ElevenLabsSpeech,
    GoogleTranslator,
    HuggingFaceTranslator,
    SyncLipsync,
)
from worker.separation import MissingDependency as SeparationMissing
from worker.separation import separate_background
from worker.subtitle_rules import rules_from_settings


class Blocked(RuntimeError):
    pass


log = logging.getLogger(__name__)
# 공급자별 배치 상한. DeepL은 요청당 50문장입니다.
PROVIDER_MAX_LINES = {"deepl": 50}


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
    if options.audio_mode == "subtitles":
        return None if "artifact_id" in data else "render"
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


def paid_estimate(name, data, options, settings, session=None):
    if name.startswith("translate:"):
        if options.translated_cues is not None or options.source_language == data.get("target"):
            return None
        texts = [c["text"] for c in translation_batch(data, settings)]
        if session is not None:
            # 기억에 있는 문장은 공급자에 보내지 않으므로 비용에도 넣지 않습니다.
            _, version = glossary_for(session, options.source_language, data["target"])
            known = cached_translations(
                session,
                texts,
                options.source_language,
                data["target"],
                final_suffix(settings, version),
            )
            texts = [t for t in texts if t not in known]
        if not texts:
            return None
        count = sum(len(t) for t in set(texts))
        rate = translation_rate(settings)
        if rate is None:
            # 로컬 모델만 쓰고 보정도 없으면 돈이 들지 않습니다.
            return None
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


def translation_rate(settings):
    """글자당 단가. 기계 번역 단가와 보정 단가를 더합니다. 둘 다 없으면 None."""
    rate = Decimal("0")
    if settings.translation_provider == "google":
        if not settings.google_cloud_project:
            raise Blocked("Google Cloud 프로젝트와 인증을 설정하세요.")
        rate += _positive(settings.translate_usd_per_1k_chars, "번역")
    elif settings.translation_provider == "deepl":
        if not settings.deepl_api_key:
            raise Blocked("DeepL API 키를 설정하세요.")
        rate += _positive(settings.translate_usd_per_1k_chars, "번역")
    if settings.translation_refine_enabled:
        rate += _positive(settings.refine_usd_per_1k_chars, "번역 보정")
    return rate if rate > 0 else None


def _positive(rate, label):
    if rate is None or rate <= 0:
        raise Blocked(f"{label} 공급자의 보수적인 단가 상한을 서버에 설정하세요.")
    return rate


def translation_batch(data, settings=None):
    """다음에 보낼 묶음. 장면 경계(LLM-Subtrans 방식)로 나눈 묶음 중 offset에서 시작하는 것.

    옛 데이터가 묶음 경계가 아닌 곳에서 멈춰 있어도 다음 경계까지를 한 묶음으로 봅니다.
    """
    cues, offset = data["cues"], len(data.get("translated", []))
    options = {}
    if settings is not None:
        options = {
            "scene_gap": settings.translate_scene_gap_seconds,
            "min_lines": settings.translate_min_batch_lines,
            "max_lines": min(
                settings.translate_max_batch_lines,
                PROVIDER_MAX_LINES.get(settings.translation_provider, 100),
            ),
        }
    boundary = next((s for s in batch_starts(cues, **options) if s > offset), len(cues))
    return cues[offset:boundary]


def glossary_for(session, source, target):
    """이 방향에 적용할 용어집과 그 버전. `*`는 모든 언어에 적용되는 행입니다.

    좁은 행이 넓은 행을 덮습니다: (*,*) < (source,*) < (*,target) < (source,target).
    버전 문자열은 기억 키에 들어가므로 용어집이 바뀌면 옛 번역을 다시 쓰지 않습니다.
    """
    entries, parts = {}, []
    for s, t in (("*", "*"), (source or "*", "*"), ("*", target), (source or "*", target)):
        row = session.scalar(
            select(Glossary)
            .where(
                Glossary.scope == "project",
                Glossary.source_language == s,
                Glossary.target_language == t,
                Glossary.effective_from <= utcnow(),
            )
            .order_by(Glossary.version.desc())
        )
        if row is None:
            continue
        entries.update(row.entries)
        parts.append(f"{s}-{t}:{row.version}")
    return entries, "|".join(parts) or None


def draft_suffix(settings, glossary_version):
    """기계 번역 초안의 기억 키 접미사. 공급자·모델·용어집 버전이 바뀌면 새 항목입니다.

    rockbenben/subtitle-translator의 generateCacheSuffix 방식입니다: 기존 MT는
    {출발, 목표, 공급자}만, 모델이 있는 공급자는 모델까지 키에 넣습니다.
    """
    parts = [settings.translation_provider]
    if settings.translation_provider == "huggingface":
        parts.append(settings.huggingface_translation_model)
    parts.append(glossary_version or "")
    return "|".join(parts)


def final_suffix(settings, glossary_version):
    """보정까지 끝난 번역의 기억 키 접미사. 보정을 안 쓰면 초안과 같습니다."""
    suffix = draft_suffix(settings, glossary_version)
    if settings.translation_refine_enabled:
        suffix += f"|refine:{settings.translation_refine_model}:{TRANSLATE_PROMPT_VERSION}"
    return suffix


def memory_hash(text, suffix):
    return hashlib.sha256(f"{suffix}\n{text}".encode()).hexdigest()


def cached_translations(session, texts, source, target, suffix):
    """기억에 있는 번역. 원문 → 번역문."""
    wanted = {memory_hash(t, suffix): t for t in set(texts)}
    if not wanted:
        return {}
    rows = session.scalars(
        select(TranslationMemory).where(
            TranslationMemory.source_language == (source or "auto"),
            TranslationMemory.target_language == target,
            TranslationMemory.text_hash.in_(list(wanted)),
        )
    )
    return {row.source_text: row.translated_text for row in rows}


def remember(session, pairs, source, target, suffix, provider):
    """공급자가 낸 답을 기억에 넣습니다. 다른 작업이 먼저 넣었으면 그대로 둡니다."""
    for text, translated in pairs:
        session.add(
            TranslationMemory(
                source_language=source or "auto",
                target_language=target,
                text_hash=memory_hash(text, suffix),
                source_text=text,
                translated_text=translated,
                provider=provider,
                glossary_version=suffix,
            )
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()


def machine_translate(settings, texts, target, source):
    """설정한 공급자로 초안을 만듭니다. Google·DeepL은 유료, Hugging Face는 로컬입니다."""
    provider = settings.translation_provider
    if provider == "google":
        return GoogleTranslator(settings.google_cloud_project, allow_paid=True).translate(
            texts, target, source
        )
    if provider == "deepl":
        with httpx.Client() as client:
            return DeepLTranslator(
                settings.deepl_api_key, client=client, allow_paid=True
            ).translate(texts, target, source)
    if provider == "huggingface":
        return HuggingFaceTranslator(
            settings.huggingface_translation_model, device=settings.whisper_device
        ).translate(texts, target, source)
    raise Blocked(f"알 수 없는 번역 공급자: {provider}")


def translate_texts(settings, texts, target, source, *, before=(), after=()):
    """기억 → 기계 번역(용어·숫자 보호) → 용어집 → Claude 보정 → 기억에 저장.

    같은 묶음 안의 같은 문장도 한 번만 보냅니다. 초안과 보정본을 따로 기억하므로
    보정이 실패해 단계가 다시 돌아도 기계 번역은 다시 사지 않습니다.
    자리표시자가 답에서 사라진 문장은 되돌릴 수 없어 그대로 두고 기록에 남깁니다.
    """
    if source and not is_supported(source, target):
        raise Blocked(f"지원하지 않는 번역 방향입니다: {source} → {target}")
    factory = get_session_factory()
    with factory() as session:
        entries, version = glossary_for(session, source, target)
        suffix, draft_key = final_suffix(settings, version), draft_suffix(settings, version)
        memory = cached_translations(session, texts, source, target, suffix)
        missing = list(dict.fromkeys(t for t in texts if t not in memory))
        if not missing:
            return [memory[t] for t in texts]
        drafts = cached_translations(session, missing, source, target, draft_key)
        fresh = [t for t in missing if t not in drafts]
        if fresh:
            protected = protect(fresh, entries)
            output = machine_translate(settings, protected.texts, target, source)
            restored, lost = restore(output, protected)
            for index in lost:
                log.warning("용어집 자리표시자가 번역에서 사라졌습니다: %r", fresh[index])
            terms = {term: (target_text or term) for term, target_text in entries.items()}
            restored = [apply_terms(text, terms) for text in restored]
            drafts.update(zip(fresh, restored, strict=True))
            if suffix != draft_key:
                remember(
                    session,
                    list(zip(fresh, restored, strict=True)),
                    source,
                    target,
                    draft_key,
                    settings.translation_provider,
                )
        final = [drafts[t] for t in missing]
        if settings.translation_refine_enabled:
            job = build_job(
                missing,
                source=source,
                target=target,
                before=before,
                after=after,
                entries=entries,
                context_lines=settings.translate_context_lines,
            )
            final = ClaudeTranslator(
                allow_paid=True, model=settings.translation_refine_model
            ).translate(job, drafts=final)
            final = [apply_terms(text, terms_for(entries)) for text in final]
        remember(
            session,
            list(zip(missing, final, strict=True)),
            source,
            target,
            suffix,
            settings.translation_provider
            + (":refine" if settings.translation_refine_enabled else ""),
        )
        memory.update(zip(missing, final, strict=True))
    return [memory[t] for t in texts]


def terms_for(entries):
    return {term: (target or term) for term, target in entries.items()}


def translation_qa(session, source, target, cues, translated):
    """번역 뒤 검사. 자동으로 고치지 않고 검수 화면에 보여 줄 문제만 모읍니다.

    용어집 위반(원문에 용어가 있는데 목표 표기가 없음)과 사라진 숫자를 봅니다.
    자막 규칙(줄 수·읽기 속도)은 렌더와 내보내기가 이미 봅니다.
    """
    entries, _ = glossary_for(session, source, target)
    issues = []
    for index, (cue, text) in enumerate(zip(cues, translated, strict=True)):
        found = []
        wrong = violations(cue["text"], text, entries)
        if wrong:
            found.append("용어집: " + ", ".join(f"{k}→{v}" for k, v in wrong.items()))
        numbers = missing_numbers(cue["text"], text)
        if numbers:
            found.append("숫자 누락: " + ", ".join(numbers))
        if found:
            issues.append({"index": index, "issues": found})
    return issues


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
        if not cues and options.audio_mode != "original":
            raise Blocked("음성이 감지되지 않았습니다. 대본을 입력하세요.")
        return {"cues": [c.model_dump() for c in cues]}
    if name.startswith("translate:"):
        batch = translation_batch(data, settings)
        offset = len(data.get("translated", []))
        if options.translated_cues is not None:
            supplied = options.translated_cues
            if len(supplied) != len(data["cues"]):
                raise Blocked("수정 번역과 대본의 문장 개수가 다릅니다.")
            texts = [c.text for c in supplied[offset : offset + len(batch)]]
        elif options.source_language == data["target"]:
            texts = [c["text"] for c in batch]
        else:
            cues = data["cues"]
            texts = translate_texts(
                settings,
                [c["text"] for c in batch],
                data["target"],
                options.source_language,
                before=[c["text"] for c in cues[max(0, offset - 20) : offset]],
                after=[c["text"] for c in cues[offset + len(batch) : offset + len(batch) + 20]],
            )
        translated = data.get("translated", []) + [
            {**cue, "text": text} for cue, text in zip(batch, texts, strict=True)
        ]
        result = {"translated": translated}
        if options.translated_cues is None and options.source_language != data["target"]:
            with get_session_factory()() as session:
                result["translation_qa"] = translation_qa(
                    session,
                    options.source_language,
                    data["target"],
                    data["cues"][: len(translated)],
                    [c["text"] for c in translated],
                )
        return result
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
            burn_subtitles=options.burn_subtitles,
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
            estimate = None if remote else paid_estimate(name, data, options, settings, session)
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
