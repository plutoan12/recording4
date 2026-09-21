"""Transcript import, clip editing, local analysis and immutable artifact approval."""

from __future__ import annotations

import base64
import binascii
import io
import re
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from adminapi.artifact_subtitles import Missing
from adminapi.artifact_subtitles import clip_subtitles as subtitles_for_clip
from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import (
    Approval,
    Artifact,
    ClipEdit,
    ClipRange,
    Job,
    MediaTask,
    SourceAsset,
    TranscriptSegment,
)
from adminapi.outbox import enqueue
from adminapi.storage import ObjectStorage, get_storage
from adminapi.subtitle_rules import subtitle_rules
from pipeline.editing import Cue, EditSpec, TrimSettings, suggest_clips
from pipeline.states import JobState
from pipeline.subtitle_files import (
    MEDIA_TYPES,
    SubtitleFormat,
    UnknownEncoding,
    decode_subtitles,
    encoding_choices,
    parse_subtitles,
)
from pipeline.subtitle_metrics import font_file_for
from pipeline.subtitle_motion import ANIMATION_LABELS
from pipeline.subtitle_presets import (
    PACK_LABELS,
    PRESET_NAME,
    PRESET_README,
    MotionPreset,
    all_presets,
    get_preset,
    presets_by_pack,
    user_presets_dir,
)
from pipeline.subtitle_stickers import STICKER_LABELS, Sticker, add_sticker_events
from pipeline.subtitle_templates import (
    CATEGORY_LABELS,
    TEMPLATE_NAME,
    get_template,
    styled_document,
    templates_by_category,
)
from pipeline.subtitles import PACING_LABELS, apply_rules, check, pacing_rules
from pipeline.time import as_utc

router = APIRouter(tags=["editing"])


def asset_for_edit(session, asset_id):
    asset = session.scalar(select(SourceAsset).where(SourceAsset.id == asset_id).with_for_update())
    if asset is None:
        raise HTTPException(404, "원본을 찾을 수 없습니다.")
    if asset.upload_state != "verified":
        raise HTTPException(409, "검사를 통과한 원본이 필요합니다.")
    return asset


def transcript(session, asset_id):
    version = session.scalar(
        select(func.max(TranscriptSegment.transcript_version)).where(
            TranscriptSegment.source_asset_id == asset_id
        )
    )
    return list(
        session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.source_asset_id == asset_id,
                TranscriptSegment.transcript_version == version,
            )
            .order_by(TranscriptSegment.start_seconds)
        )
    )


def task_response(task):
    return {
        "id": str(task.id),
        "source_asset_id": str(task.source_asset_id),
        "clip_edit_id": str(task.clip_edit_id) if task.clip_edit_id else None,
        "kind": task.kind,
        "state": task.state,
        "result": task.result,
        "error": task.error,
        "settings": task.settings,
    }


def schedule(session, task):
    session.add(task)
    session.flush()
    enqueue(
        session,
        topic="media.run",
        payload={"task_id": str(task.id)},
        dedupe_key=f"media.run:{task.id}:{task.attempt}",
    )
    return task_response(task)


def violations(cues: list[Cue]) -> list[dict]:
    """자막 가독성 문제를 목록으로 돌려줍니다. 글자를 자동으로 고치지 않습니다."""
    return [
        {"index": v.index, "kind": v.kind, "detail": v.detail}
        for v in check(cues, subtitle_rules())
    ]


class TranscriptRequest(BaseModel):
    cues: list[Cue] = Field(min_length=1, max_length=20000)


@router.get("/source-assets/{asset_id}/transcript")
def get_transcript(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    asset_for_edit(session, asset_id)
    return [
        {
            "start": float(s.start_seconds),
            "end": float(s.end_seconds),
            "text": s.text,
            # 단어 시각은 있을 때만 붙입니다. 편집기는 이를 그대로 돌려보내고 글자를
            # 고친 자막에서는 비웁니다.
            **({"words": s.words} if s.words else {}),
        }
        for s in transcript(session, asset_id)
    ]


def save_transcript(session, asset, cues: list[Cue]) -> dict:  # noqa: ANN001
    """대본을 새 버전으로 저장합니다. 기존 버전은 감사용으로 남깁니다."""
    if any(c.end > float(asset.duration_seconds) for c in cues):
        raise HTTPException(422, "대본 구간이 원본 길이를 넘습니다.")
    latest = transcript(session, asset.id)
    version = latest[0].transcript_version + 1 if latest else 1
    session.add_all(
        [
            TranscriptSegment(
                source_asset_id=asset.id,
                start_seconds=c.start,
                end_seconds=c.end,
                text=c.text,
                transcript_version=version,
                words=[w.model_dump() for w in c.words] if c.words else None,
            )
            for c in cues
        ]
    )
    return {"version": version, "count": len(cues), "violations": violations(cues)}


@router.put("/source-assets/{asset_id}/transcript")
def put_transcript(
    asset_id: uuid.UUID, payload: TranscriptRequest, user: CurrentUser, session: SessionDep
):
    return save_transcript(session, asset_for_edit(session, asset_id), payload.cues)


class SubtitleImportRequest(BaseModel):
    """밖에서 만든 자막 파일. 형식은 글자를 보고 판별합니다.

    파일은 바이트 그대로(base64) 받습니다. 브라우저가 글자로 먼저 바꾸면 UTF-8이
    아닌 파일(한국어 자막에 흔한 CP949)이 그 자리에서 깨집니다.
    """

    content_base64: str = Field(min_length=1, max_length=2_000_000)
    encoding: str | None = Field(default=None, max_length=32, pattern=r"^[A-Za-z0-9_.:-]+$")


@router.post("/source-assets/{asset_id}/transcript/import")
def import_subtitles(
    asset_id: uuid.UUID, payload: SubtitleImportRequest, user: CurrentUser, session: SessionDep
):
    """SRT·WebVTT·ASS 파일을 읽어 대본 새 버전으로 저장합니다.

    인코딩은 파일이 밝힌 표시(BOM) → UTF-8 → 판별기 순으로 정합니다. 무엇으로
    읽었는지 `encoding`으로, 판별기가 고른 것인지 `encoding_detected`로 함께
    돌려줍니다. **판별은 추측이라 글자가 깨져도 조용히 성공합니다.** 판별로
    읽었으면 다른 후보를 `choices`로 함께 주니, 화면에서 글자를 확인하고 틀렸으면
    그중 하나를 `encoding`에 넣어 다시 부르세요.

    판별기까지 실패하면 후보마다 첫 자막이 어떻게 보이는지 붙여 422로
    돌려줍니다. 글자가 제대로 보이는 것을 골라 `encoding`에 넣어 다시 부르세요.

    시각은 **파일에 적힌 그대로** 씁니다. 원본 음성과 맞는지는 확인하지 않습니다.
    다른 판본에서 만든 자막이면 통째로 어긋날 수 있으니 편집기에서 확인하세요.

    글자가 없거나 시간이 올바르지 않은 자막은 빼고, 무엇을 왜 뺐는지 `skipped`로
    함께 돌려줍니다. 조용히 버리지 않습니다.
    """
    asset = asset_for_edit(session, asset_id)
    try:
        data = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "자막 파일을 읽지 못했습니다. 다시 올려 주세요.") from None
    try:
        found = decode_subtitles(data, payload.encoding)
        cues, notes = parse_subtitles(found.text)
    except UnknownEncoding as exc:
        raise HTTPException(
            422,
            {
                "message": str(exc),
                "choices": [
                    {"encoding": choice.encoding, "preview": choice.preview}
                    for choice in exc.choices
                ],
            },
        ) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    saved = {
        **save_transcript(session, asset, cues),
        "skipped": notes,
        "encoding": found.encoding,
        "encoding_detected": found.detected,
    }
    if found.detected:
        # 판별로 읽었으면 다른 후보도 함께 줍니다. 글자가 깨졌을 때 화면에서
        # 바로 다른 인코딩으로 다시 들일 수 있어야 합니다.
        saved["choices"] = [
            {"encoding": choice.encoding, "preview": choice.preview}
            for choice in encoding_choices(data)
        ]
    return saved


class AnalysisRequest(BaseModel):
    kind: Literal["transcribe", "scenes", "highlights", "silence"]
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    # 추천 구간의 목표 길이(초). `highlights`에서만 씁니다.
    target: float | None = Field(default=None, ge=5, le=600)
    # 무음 컷을 재 볼 구간과 세기. `silence`에서만 씁니다.
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    settings: TrimSettings | None = None


class DiarizeRequest(BaseModel):
    """화자 분리 요청. 화자 수를 알면 알려 주는 편이 정확합니다."""

    min_speakers: int | None = Field(default=None, ge=1, le=20)
    max_speakers: int | None = Field(default=None, ge=1, le=20)


class AlignRequest(BaseModel):
    """타이밍 없는 대본. 글자는 그대로 두고 시각만 찾습니다."""

    text: str = Field(min_length=1, max_length=50000)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


@router.post("/source-assets/{asset_id}/analyze", status_code=202)
def analyze(asset_id: uuid.UUID, payload: AnalysisRequest, user: CurrentUser, session: SessionDep):
    asset_for_edit(session, asset_id)
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == payload.kind,
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset_id,
            kind=payload.kind,
            settings={
                "language": payload.language,
                "target": payload.target,
                "start": payload.start,
                "end": payload.end,
                "settings": payload.settings.model_dump() if payload.settings else None,
            },
        ),
    )


@router.post("/source-assets/{asset_id}/align", status_code=202)
def align(asset_id: uuid.UUID, payload: AlignRequest, user: CurrentUser, session: SessionDep):
    """대본을 원본 오디오에 정렬해 새 대본 버전을 만듭니다. 유료 호출이 아닙니다."""
    asset_for_edit(session, asset_id)
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == "align",
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset_id,
            kind="align",
            settings={"text": payload.text, "language": payload.language},
        ),
    )


@router.post("/source-assets/{asset_id}/diarize", status_code=202)
def diarize(asset_id: uuid.UUID, payload: DiarizeRequest, user: CurrentUser, session: SessionDep):
    """누가 말했는지 찾아 최신 대본에 화자를 붙인 새 버전을 만듭니다."""
    asset_for_edit(session, asset_id)
    if (
        payload.min_speakers
        and payload.max_speakers
        and payload.min_speakers > payload.max_speakers
    ):
        raise HTTPException(422, "최소 화자 수가 최대 화자 수보다 큽니다.")
    if not transcript(session, asset_id):
        raise HTTPException(409, "화자를 붙일 대본이 없습니다. 먼저 전사하거나 대본을 올리세요.")
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == "diarize",
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset_id,
            kind="diarize",
            settings={
                "min_speakers": payload.min_speakers,
                "max_speakers": payload.max_speakers,
            },
        ),
    )


@router.post("/source-assets/{asset_id}/transcript/sync", status_code=202)
def sync_transcript(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    """최신 대본의 시각을 원본 음성에 맞춰 통째로 옮긴 새 버전을 만듭니다.

    밖에서 들인 자막이 원본과 어긋날 때 씁니다. **글자는 건드리지 않고** 시각만
    옮기며, 얼마나 옮겼는지(`result.sync.offset_seconds`)를 작업 결과에 남깁니다.

    기존 대본 버전은 그대로 남습니다. 보정이 마음에 들지 않으면 그 버전을 다시
    쓰면 됩니다. 유료 호출이 아니며 `[subtitles]` 설치가 필요합니다.
    """
    asset_for_edit(session, asset_id)
    if not transcript(session, asset_id):
        raise HTTPException(409, "보정할 대본이 없습니다. 먼저 대본을 만들거나 들이세요.")
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == "sync",
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(session, MediaTask(source_asset_id=asset_id, kind="sync", settings={}))


@router.get("/source-assets/{asset_id}/speakers")
def speakers(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    """최신 대본에 붙은 화자 목록. 화자별 발화 시간과 구간 수를 함께 봅니다."""
    asset_for_edit(session, asset_id)
    rows = transcript(session, asset_id)
    found: dict[str, dict] = {}
    for row in rows:
        if not row.speaker:
            continue
        entry = found.setdefault(row.speaker, {"speaker": row.speaker, "seconds": 0.0, "count": 0})
        entry["seconds"] += float(row.end_seconds) - float(row.start_seconds)
        entry["count"] += 1
    return {
        "version": rows[0].transcript_version if rows else None,
        "unlabeled": sum(1 for row in rows if not row.speaker),
        "speakers": sorted(found.values(), key=lambda e: (-e["seconds"], e["speaker"])),
    }


@router.get("/source-assets/{asset_id}/subtitle-check")
def subtitle_check(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    """저장된 최신 대본의 가독성 문제를 보고합니다."""
    asset_for_edit(session, asset_id)
    cues = [
        Cue(start=float(s.start_seconds), end=float(s.end_seconds), text=s.text)
        for s in transcript(session, asset_id)
    ]
    return {"count": len(cues), "violations": violations(cues)}


@router.get("/source-assets/{asset_id}/suggestions")
def suggestions(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    asset = asset_for_edit(session, asset_id)
    cues = [
        Cue(start=float(s.start_seconds), end=float(s.end_seconds), text=s.text)
        for s in transcript(session, asset_id)
    ]
    return suggest_clips(cues, duration=float(asset.duration_seconds))


class ClipRequest(EditSpec):
    source_asset_id: uuid.UUID


@router.post("/clips", status_code=202)
def create_clip(payload: ClipRequest, user: CurrentUser, session: SessionDep):
    asset = asset_for_edit(session, payload.source_asset_id)
    if payload.end > float(asset.duration_seconds):
        raise HTTPException(422, "선택 구간이 원본 길이를 넘습니다.")
    spec = EditSpec.model_validate(payload.model_dump(exclude={"source_asset_id"}))
    try:
        pacing_rules(spec.subtitle_pacing)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        template = get_template(spec.subtitle_template)
        if spec.subtitle_preset:
            template = template.with_preset(spec.subtitle_preset)
        if spec.subtitle_animation:
            template = template.with_animation(spec.subtitle_animation)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # Client sends its edited captions explicitly; an empty list means no captions.
    version = (
        session.scalar(
            select(func.max(ClipEdit.edit_version)).where(ClipEdit.source_asset_id == asset.id)
        )
        or 0
    ) + 1
    clip = ClipEdit(
        source_asset_id=asset.id,
        edit_version=version,
        output_language=payload.caption_language or asset.source_language or "und",
        created_by_id=user.id,
        output_width=spec.width,
        output_height=spec.height,
        screen_title=spec.title,
        publish_title=spec.title,
        subtitle_style={
            "template": template.name,
            "font_size": spec.font_size or template.font_size,
            "animation": template.animation,
            "preset": template.preset,
            "pacing": spec.subtitle_pacing or "broadcast",
        },
    )
    session.add(clip)
    session.flush()
    session.add(
        ClipRange(
            clip_edit_id=clip.id,
            source_start_seconds=spec.start,
            source_end_seconds=spec.end,
            crop={"mode": spec.mode, "focus_x": spec.focus_x, "focus_y": spec.focus_y},
        )
    )
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset.id,
            clip_edit_id=clip.id,
            kind="render",
            settings=spec.model_dump(),
        ),
    )


@router.get("/subtitle-templates")
def subtitle_templates(user: CurrentUser) -> list[dict]:
    """편집기가 고를 수 있는 내장 자막 템플릿. 이름을 `subtitle_template`로 보냅니다.

    카테고리 순서대로 돌려주고 `category_label`을 붙입니다. 화면은 이 값으로 묶어
    보여 주고, CSS로 모양을 흉내 낸 미리보기를 그립니다(실제 렌더는 libass).
    """
    return [
        {
            **t.model_dump(),
            "category_label": CATEGORY_LABELS[t.category],
            "animation_label": t.animation_label,
        }
        for templates in templates_by_category().values()
        for t in templates
    ]


@router.get("/stickers")
def stickers(user: CurrentUser) -> list[dict]:
    """편집기가 붙일 수 있는 스티커 종류. `kind`를 `stickers[].kind`로 보냅니다.

    `image`는 워커의 스티커 디렉터리(R4_STICKERS_DIR)에 있는 PNG 파일 이름을 `image`로
    함께 보냅니다. 파일 목록은 서버 설정(R4_STICKERS_DIR)이 API에도 있을 때만 붙습니다.
    """
    import os

    directory = os.environ.get("R4_STICKERS_DIR", "").strip()
    images = []
    if directory and os.path.isdir(directory):
        images = sorted(name for name in os.listdir(directory) if name.lower().endswith(".png"))
    return [
        {"kind": kind, "label": label, **({"images": images} if kind == "image" else {})}
        for kind, label in STICKER_LABELS.items()
    ]


@router.get("/subtitle-presets")
def subtitle_presets(user: CurrentUser) -> list[dict]:
    """편집기가 고를 수 있는 모션 프리셋. 이름을 `subtitle_preset`으로 보냅니다.

    프리셋은 동작(등장·사라짐·계속)을 겹쳐 만든 움직임 한 벌로, 고르면 템플릿과
    `subtitle_animation`보다 먼저 쓰입니다. 빈 문자열이면 템플릿 값으로 돌아갑니다.
    팩(`pack`)으로 묶어 보여 주면 됩니다.
    """
    return [
        {
            "name": preset.name,
            "label": preset.label,
            "pack": pack,
            "pack_label": PACK_LABELS[pack],
            "summary": preset.summary,
            "description": preset.description,
            # 내 프리셋만 지울 수 있습니다(내장은 파일이 없습니다).
            "editable": pack == "user",
        }
        for pack, presets in presets_by_pack().items()
        for preset in presets
    ]


def _preset_or_404(name: str) -> MotionPreset:
    if not re.fullmatch(PRESET_NAME, name):
        raise HTTPException(422, "프리셋 이름 형식이 아닙니다.")
    try:
        return get_preset(name)
    except ValueError:
        raise HTTPException(404, f"모르는 프리셋입니다: {name}") from None


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/subtitle-presets/{name}/file")
def subtitle_preset_file(name: str, user: CurrentUser) -> Response:
    """프리셋 하나를 JSON 파일로 내려줍니다. 고쳐서 다시 올리거나 명령줄에서 씁니다."""
    preset = _preset_or_404(name)
    return Response(
        content=preset.to_json(),
        media_type="application/json",
        headers=_attachment(f"{preset.name}.json"),
    )


@router.get("/subtitle-preset-packs/{pack}")
def subtitle_preset_pack(pack: str, user: CurrentUser) -> Response:
    """팩 하나를 통째로 zip으로 내려줍니다. 프리셋 JSON과 읽어보기 파일이 들어갑니다."""
    grouped = presets_by_pack()
    if pack not in grouped:
        raise HTTPException(404, f"모르는 팩입니다: {pack}. 쓸 수 있는 것: {', '.join(grouped)}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("읽어보기.txt", PRESET_README)
        for preset in grouped[pack]:
            archive.writestr(f"{preset.name}.json", preset.to_json())
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers=_attachment(f"r4-presets-{pack}.zip"),
    )


@router.post("/subtitle-presets", status_code=201)
def save_subtitle_preset(payload: MotionPreset, user: CurrentUser) -> dict:
    """프리셋 파일을 올려 "내 프리셋"으로 저장합니다(서버의 R4_PRESETS_DIR).

    내장 프리셋과 같은 이름은 받지 않습니다. 저장한 프리셋은 목록·편집기·렌더에서
    바로 쓸 수 있습니다. 실제로 영상에 구우려면 워커도 같은 디렉터리를 봐야 합니다.
    """
    directory = user_presets_dir()
    if directory is None:
        raise HTTPException(503, "서버에 프리셋 디렉터리(R4_PRESETS_DIR)가 없습니다.")
    builtin = {name for name, preset in all_presets().items() if preset.pack != "user"}
    if payload.name in builtin:
        raise HTTPException(409, f"내장 프리셋과 같은 이름입니다: {payload.name}")
    target = directory / f"{payload.name}.json"
    if not target.exists() and len(list(directory.glob("*.json"))) >= 200:
        raise HTTPException(409, "프리셋 디렉터리가 가득 찼습니다(200개).")
    stored = payload.model_copy(update={"pack": "user"})
    try:
        target.write_text(stored.to_json(), encoding="utf-8")
    except OSError:
        raise HTTPException(503, "프리셋을 저장하지 못했습니다.") from None
    return {"name": stored.name, "label": stored.label, "pack": "user"}


@router.delete("/subtitle-presets/{name}", status_code=204)
def delete_subtitle_preset(name: str, user: CurrentUser) -> Response:
    """내 프리셋을 지웁니다. 내장 프리셋은 지울 수 없습니다."""
    preset = _preset_or_404(name)
    directory = user_presets_dir()
    if preset.pack != "user" or directory is None:
        raise HTTPException(409, "내 프리셋만 지울 수 있습니다.")
    target = directory / f"{name}.json"
    if not target.is_file():
        raise HTTPException(404, f"프리셋 파일이 없습니다: {name}")
    target.unlink()
    return Response(status_code=204)


@router.get("/subtitle-pacings")
def subtitle_pacings(user: CurrentUser) -> list[dict]:
    """자막을 끊는 방식. 이름을 `subtitle_pacing`으로 보냅니다.

    `shortform`은 말한 시각(대본의 단어 시각)에 맞춰 한 줄로 짧게 끊습니다. 단어 시각이
    없거나 사람이 글자를 고친 자막은 글자 수로 끊는 방식으로 자동으로 돌아갑니다.
    """
    return [{"name": name, "label": label} for name, label in PACING_LABELS.items()]


@router.get("/subtitle-animations")
def subtitle_animations(user: CurrentUser) -> list[dict]:
    """편집기가 고를 수 있는 자막 움직임. 이름을 `subtitle_animation`으로 보냅니다.

    비우면 템플릿의 움직임을 쓰고, `none`이면 움직임을 뺍니다.
    """
    return [{"name": name, "label": label} for name, label in ANIMATION_LABELS.items()]


class PreviewRequest(BaseModel):
    template: str = Field(default="default", pattern=TEMPLATE_NAME)
    animation: str | None = Field(default=None, pattern=r"^[a-z][a-z-]{0,19}$")
    preset: str | None = Field(default=None, pattern=r"^$|^[a-z][a-z0-9-]{1,39}$")
    pacing: str | None = Field(default=None, pattern=r"^(broadcast|shortform)$")
    text: str | None = Field(default=None, max_length=200)
    width: int = Field(default=540, ge=180, le=1080, multiple_of=2)
    height: int = Field(default=960, ge=180, le=1920, multiple_of=2)
    seconds: float = Field(default=3.0, gt=0, le=10)
    font_size: int | None = Field(default=None, ge=20, le=120)
    # 벡터 스티커만 미리보기에 그립니다(이미지는 합성 단계라 빠집니다). 시각은 0초 기준입니다.
    stickers: list[Sticker] = Field(default_factory=list, max_length=20)


_FONT_TAG = re.compile(r"\\fn([^\\}]+)")


@router.post("/subtitle-preview")
def subtitle_preview(payload: PreviewRequest, user: CurrentUser) -> dict:
    """편집기의 정확 미리보기용 ASS 문서. 워커가 굽는 것과 같은 코드로 만듭니다.

    브라우저는 이 ASS를 libass WASM(jassub)으로 그립니다. `fonts`는 문서가 쓰는 글꼴
    이름이며 `/subtitle-fonts/{family}`로 받아 렌더러에 넣습니다. 글자 크기는 화면
    크기에 맞춰 줄이지 않고 템플릿 값(1080x1920 기준)을 그대로 두므로, 화면을 그
    비율로 주면 실제 영상과 같은 배치가 됩니다.
    """
    try:
        template = get_template(payload.template)
        if payload.preset is not None:
            template = template.with_preset(payload.preset) if payload.preset else template
        if payload.animation:
            template = template.with_animation(payload.animation)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    text = (payload.text or "").strip() or template.sample or template.label
    rules = pacing_rules(payload.pacing) if payload.pacing else subtitle_rules()
    cues = apply_rules([Cue(start=0, end=payload.seconds, text=text)], rules)
    document = styled_document(
        cues,
        template,
        width=payload.width,
        height=payload.height,
        duration=payload.seconds,
        font_size=payload.font_size,
    )
    add_sticker_events(
        document,
        payload.stickers,
        width=payload.width,
        height=payload.height,
        duration=payload.seconds,
    )
    ass = document.to_string("ass")
    families = {style.fontname for style in document.styles.values()}
    families.update(name.strip() for name in _FONT_TAG.findall(ass))
    return {
        "ass": ass,
        "seconds": payload.seconds,
        "width": payload.width,
        "height": payload.height,
        "fonts": sorted(families),
    }


_FONT_MEDIA = {".ttf": "font/ttf", ".otf": "font/otf", ".ttc": "font/collection"}
_FAMILY = re.compile(r"^[^,{}\\\r\n\t/]{1,80}$")


@router.get("/subtitle-fonts/{family}")
def subtitle_font(family: str, user: CurrentUser) -> FileResponse:
    """미리보기 렌더러에 넣을 글꼴 파일. 설치된 글꼴(R4_FONTS_DIR 또는 시스템)만 내려줍니다.

    이름으로 파일을 찾으므로 경로를 받지 않습니다. 없으면 404이고 화면은 그 글꼴 없이
    (다른 글꼴로 대체돼) 그립니다.
    """
    if not _FAMILY.match(family):
        raise HTTPException(422, "글꼴 이름 형식이 아닙니다.")
    path = font_file_for(family)
    if path is None or not path.is_file():
        raise HTTPException(404, f"설치되지 않은 글꼴입니다: {family}")
    return FileResponse(
        path,
        media_type=_FONT_MEDIA.get(path.suffix.lower(), "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/clips/{clip_edit_id}/subtitles")
def clip_subtitles(
    clip_edit_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    subtitle_format: SubtitleFormat = Query("srt", alias="format"),
) -> Response:
    """편집본 자막을 SRT·VTT 파일로 내려줍니다.

    렌더할 때 쓴 표시 규칙을 그대로 거치고 시각은 클립 시작이 0초입니다. 화면
    제목은 자막이 아니므로 넣지 않습니다.

    이 기능 전에 렌더한 기록에는 그때 쓴 규칙이 남아 있지 않습니다. 그럴 때만
    지금 설정을 쓰고, 응답 헤더 `X-Subtitle-Rules`에 `settings`로 적습니다.
    설정을 그 사이에 바꿨다면 영상과 줄바꿈·분할이 다를 수 있습니다.
    """
    if session.get(ClipEdit, clip_edit_id) is None:
        raise HTTPException(404, "편집본을 찾을 수 없습니다.")
    found = subtitles_for_clip(session, clip_edit_id, subtitle_format)
    if isinstance(found, Missing):
        raise HTTPException(409, found.reason)
    return Response(
        content=found.text,
        media_type=f"{MEDIA_TYPES[subtitle_format]}; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="clip-{clip_edit_id}.{subtitle_format}"'
            ),
            # 영상과 같은 규칙인지 받는 쪽이 알 수 있게 합니다. rendered면 렌더
            # 때 쓴 규칙, settings면 지금 설정(옛 기록이라 남은 것이 없음)입니다.
            "X-Subtitle-Rules": found.rules_source,
        },
    )


@router.get("/media-tasks")
def list_tasks(user: CurrentUser, session: SessionDep):
    return [
        task_response(t)
        for t in session.scalars(select(MediaTask).order_by(MediaTask.created_at.desc()).limit(100))
    ]


@router.post("/media-tasks/{task_id}/retry", status_code=202)
def retry_task(task_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    task = session.scalar(select(MediaTask).where(MediaTask.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    # A worker enforces a 1-hour hard limit. Only recover leases after 2 hours.
    stale = (
        task.state == "running"
        and task.started_at
        and (datetime.now(UTC) - as_utc(task.started_at)).total_seconds() > 7200
    )
    if task.state != "failed" and not stale:
        raise HTTPException(409, "실패하거나 2시간 이상 정체된 작업만 재시도할 수 있습니다.")
    task.state, task.error, task.started_at = "pending", None, None
    task.attempt += 1
    return schedule(session, task)


@router.get("/artifacts/{artifact_id}/preview")
def preview(
    artifact_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: ObjectStorage = Depends(get_storage),
):
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "결과물을 찾을 수 없습니다.")
    return {"url": storage.presigned_get_url(artifact.storage_key, 300)}


@router.post("/artifacts/{artifact_id}/approve")
def approve(artifact_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    artifact = session.scalar(select(Artifact).where(Artifact.id == artifact_id).with_for_update())
    if artifact is None:
        raise HTTPException(404, "결과물을 찾을 수 없습니다.")
    if artifact.job_id:
        job = session.scalar(select(Job).where(Job.id == artifact.job_id).with_for_update())
        if job.state not in (JobState.REVIEW_REQUIRED, JobState.APPROVED) or job.workflow_data.get(
            "artifact_id"
        ) != str(artifact.id):
            raise HTTPException(409, "현재 검수 대상 결과물만 승인할 수 있습니다.")
        job.state = JobState.APPROVED
    existing = session.scalar(
        select(Approval).where(Approval.artifact_id == artifact_id, Approval.metadata_version == 1)
    )
    if existing is None:
        existing = Approval(artifact_id=artifact.id, approver_id=user.id)
        session.add(existing)
        session.flush()
    return {"approval_id": str(existing.id), "artifact_id": str(artifact.id)}
