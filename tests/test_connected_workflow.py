"""Durable workflow tests: no external credentials or network calls."""

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from adminapi.config import get_settings
from adminapi.models import Artifact, Budget, Job, SourceAsset, StageRun, utcnow
from pipeline.states import JobState
from worker import publication_tasks as pub
from worker import workflow_tasks as wf


@pytest.fixture
def setup_flow(client, auth_headers, session, user, monkeypatch):
    objects = {"source": b"source bytes"}
    storage = SimpleNamespace(
        head=lambda key: object() if key in objects else None,
        download_file=lambda key, path: path.write_bytes(objects[key]),
        upload_file=lambda key, path, content_type: objects.update({key: path.read_bytes()}),
        presigned_get_url=lambda key, ttl: f"https://storage.test/{key}",
    )
    monkeypatch.setattr(wf, "get_storage", lambda: storage)
    monkeypatch.setattr(pub, "get_storage", lambda: storage)
    monkeypatch.setattr(
        wf, "render_final", lambda source, output, **kw: output.write_bytes(b"final")
    )
    asset = SourceAsset(
        storage_key="source",
        original_filename="source.mp4",
        upload_state="verified",
        duration_seconds=10,
        width=640,
        height=360,
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()

    def create(**options):
        response = client.post(
            "/jobs",
            headers=auth_headers,
            json={
                "source_asset_id": str(asset.id),
                "target_language": "en",
                "workflow": {
                    "audio_mode": "original",
                    "transcript": [{"start": 1, "end": 2, "text": "hello"}],
                    **options,
                },
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return create, objects


def test_original_to_approval_and_duplicate_delivery(setup_flow, client, auth_headers, session):
    create, objects = setup_flow
    jid = create()
    assert wf.run_job(jid)["stage"] == "transcribe"
    assert wf.run_job(jid)["stage"] == "render"
    assert wf.run_job(jid)["status"] == "review_required"
    assert wf.run_job(jid)["status"] == "not_runnable"
    detail = client.get(f"/jobs/{jid}/workflow", headers=auth_headers).json()
    assert len(detail["stages"]) == 2
    artifact = session.get(Artifact, uuid.UUID(detail["artifact_id"]))
    assert artifact.checksum == hashlib.sha256(b"final").hexdigest()
    assert client.post(f"/artifacts/{artifact.id}/approve", headers=auth_headers).status_code == 200
    session.expire_all()
    assert session.get(Job, uuid.UUID(jid)).state == JobState.APPROVED


def test_budget_blocks_before_call_and_uncertain_call_needs_resolution(
    setup_flow, client, auth_headers, session, monkeypatch
):
    create, _ = setup_flow
    settings = get_settings().model_copy(
        update={
            "paid_processing_enabled": True,
            "elevenlabs_api_key": "test-only",
            "tts_usd_per_1k_chars": Decimal("1"),
        }
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)
    calls = []

    class Speech:
        def __init__(self, *args, **kwargs):
            pass

        def synthesize(self, *args, **kwargs):
            calls.append(1)
            raise RuntimeError("response lost")

    monkeypatch.setattr(wf, "ElevenLabsSpeech", Speech)
    jid = create(audio_mode="dub", source_language="en", voice_id="test")
    assert (
        client.put(
            "/workflow/monthly-budget", headers=auth_headers, json={"limit_usd": "10"}
        ).status_code
        == 200
    )
    wf.run_job(jid)
    wf.run_job(jid)
    assert wf.run_job(jid)["status"] == "blocked_or_failed"
    assert not calls
    client.put(f"/jobs/{jid}/budget", headers=auth_headers, json={"limit_usd": "1"})
    assert client.post(f"/jobs/{jid}/resume", headers=auth_headers).status_code == 202
    wf.run_job(jid)
    assert calls == [1]
    assert client.post(f"/jobs/{jid}/resume", headers=auth_headers).status_code == 409
    assert wf.run_job(jid)["status"] == "not_runnable"
    stage = session.query(StageRun).filter_by(job_id=uuid.UUID(jid), stage="dub:0").one()
    assert (
        client.post(
            f"/jobs/{jid}/stages/{stage.id}/resolve",
            headers=auth_headers,
            json={"outcome": "charged_without_result", "note": "provider billing confirmed"},
        ).status_code
        == 200
    )
    session.expire_all()
    assert all(b.spent_amount == Decimal("0.0050") for b in session.query(Budget).all())
    assert client.post(f"/jobs/{jid}/resume", headers=auth_headers).status_code == 202


def test_full_dub_stages_and_budget_settlement(
    setup_flow, client, auth_headers, session, monkeypatch
):
    create, _ = setup_flow
    settings = get_settings().model_copy(
        update={
            "paid_processing_enabled": True,
            "elevenlabs_api_key": "test",
            "tts_usd_per_1k_chars": Decimal("1"),
        }
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)

    class Speech:
        def __init__(self, *args, **kwargs):
            pass

        def synthesize(self, text, voice, output, **kwargs):
            output.write_bytes(b"voice")

    monkeypatch.setattr(wf, "ElevenLabsSpeech", Speech)

    def mix(paths, cues, duration, output):
        output.write_bytes(b"wav")
        return cues

    monkeypatch.setattr(wf, "mix_speech", mix)
    monkeypatch.setattr(
        wf, "compose_dub", lambda src, audio, out, start, duration: out.write_bytes(b"dub")
    )
    client.put("/workflow/monthly-budget", headers=auth_headers, json={"limit_usd": "10"})
    jid = create(audio_mode="dub", source_language="en", voice_id="test", budget_usd="1")
    stages = [wf.run_job(jid) for _ in range(7)]
    assert [s.get("stage") for s in stages[:-1]] == [
        "transcribe",
        "translate:0",
        "dub:0",
        "mix",
        "compose",
        "render",
    ]
    assert stages[-1]["status"] == "review_required"
    assert all(b.spent_amount == Decimal("0.0050") for b in session.query(Budget).all())


def test_publication_approval_resume_schedule_and_no_duplicate_upload(
    setup_flow, client, auth_headers, session, monkeypatch
):
    from adminapi.routers import workflow

    create, _ = setup_flow
    settings = get_settings().model_copy(update={"youtube_channel_id": "channel"})
    monkeypatch.setattr(workflow, "get_settings", lambda: settings)
    monkeypatch.setattr(pub, "get_settings", lambda: settings)
    jid = create()
    for _ in range(3):
        wf.run_job(jid)
    aid = client.get(f"/jobs/{jid}/workflow", headers=auth_headers).json()["artifact_id"]
    payload = {
        "artifact_id": aid,
        "title": "test",
        "made_for_kids": False,
        "publish_at": (utcnow() + timedelta(days=1)).isoformat(),
    }
    assert client.post("/publications", headers=auth_headers, json=payload).status_code == 409
    client.post(f"/artifacts/{aid}/approve", headers=auth_headers)
    response = client.post("/publications", headers=auth_headers, json=payload)
    assert response.status_code == 202, response.text
    pid = response.json()["id"]
    assert client.post("/publications", headers=auth_headers, json=payload).json()["id"] == pid
    state = {"privacyStatus": "private"}
    info = {
        "snippet": {"channelId": "channel"},
        "status": state,
        "processingDetails": {"processingStatus": "succeeded"},
    }

    class Service:
        def channels(self):
            return SimpleNamespace(
                list=lambda **kw: SimpleNamespace(execute=lambda: {"items": [{"id": "channel"}]})
            )

        def videos(self):
            return SimpleNamespace(
                list=lambda **kw: SimpleNamespace(execute=lambda: {"items": [info]})
            )

    monkeypatch.setattr(pub, "youtube_service", Service)
    uploads = []

    def upload(*args, **kw):
        uploads.append(kw["checkpoint"])
        kw["save"]({"started": True, "session_uri": "https://test/session", "video_id": "video"})
        return "video"

    monkeypatch.setattr(pub, "upload_approved", upload)
    monkeypatch.setattr(
        pub, "schedule_video", lambda service, vid, at, **kw: state.update(publishAt=at.isoformat())
    )
    pub.run_publication(pid)
    assert client.get("/publications", headers=auth_headers).json()[0]["state"] == "scheduled"
    pub.run_publication(pid)
    assert len(uploads) == 1
    state["privacyStatus"] = "public"
    pub.run_publication(pid)
    assert client.get("/publications", headers=auth_headers).json()[0]["state"] == "published"


def test_live_lease_prevents_second_worker(setup_flow, session):
    create, _ = setup_flow
    jid = create()
    job = session.get(Job, uuid.UUID(jid))
    job.lease_until = utcnow() + timedelta(hours=1)
    job.lease_token = "other-worker"
    session.commit()
    assert wf.run_job(jid)["status"] == "not_runnable"
    assert session.query(StageRun).count() == 0


def test_delayed_messages_are_not_dispatched_early(session):
    from adminapi.outbox import enqueue
    from worker.dispatcher import dispatch_pending

    enqueue(
        session,
        topic="job.step",
        payload={"job_id": "future"},
        dedupe_key="future",
        delay_seconds=30,
    )
    enqueue(session, topic="job.start", payload={"job_id": "now"}, dedupe_key="now")
    session.commit()
    sent = []
    assert dispatch_pending(session, lambda name, payload: sent.append((name, payload))) == 1
    assert sent == [("worker.workflow_tasks.run_job", {"job_id": "now"})]


def test_translation_provider_and_lipsync_reuses_remote_id(setup_flow, monkeypatch, tmp_path):
    from pipeline.workflow import WorkflowOptions

    create, _ = setup_flow
    settings = get_settings().model_copy(
        update={"google_cloud_project": "test", "sync_api_key": "test"}
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)

    class Translator:
        def __init__(self, *args, **kwargs):
            pass

        def translate(self, texts, target, source):
            return ["translated"]

    monkeypatch.setattr(wf, "GoogleTranslator", Translator)
    options = WorkflowOptions(voice_id="voice", lipsync=True)
    data = {
        "cues": [{"start": 0, "end": 1, "text": "original"}],
        "target": "en",
        "base_key": "base",
        "audio_key": "audio",
    }
    translated = wf.execute_step(
        "translate:0", options, data, None, tmp_path, "stage", None, lambda x: None
    )
    assert translated["translated"][0]["text"] == "translated"
    submitted = []

    class Sync:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, video, audio):
            submitted.append((video, audio))
            return "remote"

        def status(self, remote):
            assert remote == "remote"
            return {"status": "PROCESSING"}

    monkeypatch.setattr(wf, "SyncLipsync", Sync)
    saved = []
    assert wf.execute_step(
        "lipsync", options, data, None, tmp_path, "stage", None, saved.append
    ) == {"waiting": True}
    assert wf.execute_step(
        "lipsync", options, data, None, tmp_path, "stage", saved[0], saved.append
    ) == {"waiting": True}
    assert len(submitted) == 1


def test_real_dub_mix_composition_and_subtitles(tmp_path):
    import os
    import shutil
    import wave

    from pipeline.editing import Cue
    from worker.composition import TimingError, compose_dub, ffmpeg, mix_speech, render_final

    if not os.environ.get("R4_FFMPEG_BINARY") and not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    source, speech = tmp_path / "source.mp4", tmp_path / "speech.wav"
    ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=320x180:d=3", "-c:v", "libx264", str(source)])
    ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", str(speech)])
    mixed = tmp_path / "mixed.wav"
    aligned = mix_speech([speech], [Cue(start=1, end=2, text="Hello")], 3, mixed)
    assert abs(aligned[0].end - 1.5) < 0.02
    with wave.open(str(mixed), "rb") as audio:
        assert audio.getnframes() == 3 * 48000
        assert audio.readframes(48000) == b"\0\0" * 48000
        assert any(audio.readframes(24000))
    dubbed, final = tmp_path / "dubbed.mp4", tmp_path / "final.mp4"
    compose_dub(source, mixed, dubbed, 0, 3)
    render_final(dubbed, final, cues=aligned, duration=3, width=320, height=180)
    ffmpeg(["-i", str(final), "-f", "null", "-"])
    assert final.stat().st_size > 1000
    with pytest.raises(TimingError):
        mix_speech([speech], [Cue(start=0, end=0.1, text="Too long")], 0.1, tmp_path / "bad.wav")


def test_terminal_lipsync_can_be_reconciled_and_retried_without_redoing_tts(
    setup_flow, client, auth_headers, session, monkeypatch
):
    from adminapi.services.budget import held_total

    create, _ = setup_flow
    settings = get_settings().model_copy(
        update={
            "paid_processing_enabled": True,
            "sync_api_key": "test",
            "lipsync_usd_per_second": Decimal("0.1"),
        }
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)
    submitted = []
    status = ["FAILED"]

    class Sync:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, *args):
            submitted.append(args)
            return f"remote-{len(submitted)}"

        def status(self, remote):
            return {"status": status[0]}

    monkeypatch.setattr(wf, "SyncLipsync", Sync)
    client.put("/workflow/monthly-budget", headers=auth_headers, json={"limit_usd": "10"})
    jid = create(audio_mode="dub", lipsync=True, budget_usd="2", voice_id="voice")
    job = session.get(Job, uuid.UUID(jid))
    job.workflow_data = {
        "cues": [{"start": 1, "end": 2, "text": "hello"}],
        "translated": [{"start": 1, "end": 2, "text": "hello"}],
        "voices": ["voice"],
        "audio_key": "audio",
        "base_key": "base",
        "start": 0,
        "duration": 10,
        "target": "en",
    }
    session.commit()
    assert wf.run_job(jid)["status"] == "blocked_or_failed"
    detail = client.get(f"/jobs/{jid}/workflow", headers=auth_headers).json()
    assert detail["stages"][0]["state"] == "failed"
    assert detail["stages"][0]["uncertain"] is True
    assert client.post(f"/jobs/{jid}/resume", headers=auth_headers).status_code == 409
    sid = detail["stages"][0]["id"]
    assert (
        client.post(
            f"/jobs/{jid}/stages/{sid}/resolve",
            headers=auth_headers,
            json={"outcome": "confirmed_no_charge", "note": "Provider confirmed no charge"},
        ).status_code
        == 200
    )
    session.expire_all()
    assert all(held_total(session, b.id) == 0 for b in session.query(Budget))
    status[0] = "PROCESSING"
    assert client.post(f"/jobs/{jid}/resume", headers=auth_headers).status_code == 202
    assert wf.run_job(jid)["status"] == "waiting"
    assert len(submitted) == 2
    session.expire_all()
    assert session.get(Job, uuid.UUID(jid)).workflow_data["voices"] == ["voice"]
    assert session.query(StageRun).filter_by(job_id=uuid.UUID(jid), stage="lipsync").count() == 2


def test_explicit_parent_reuses_only_unchanged_voice_and_charges_only_changed_sentence(
    setup_flow, client, auth_headers, session, monkeypatch
):
    create, objects = setup_flow
    settings = get_settings().model_copy(
        update={
            "paid_processing_enabled": True,
            "elevenlabs_api_key": "test",
            "tts_usd_per_1k_chars": Decimal("1"),
        }
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)
    calls = []

    class Speech:
        def __init__(self, *args, **kwargs):
            pass

        def synthesize(self, text, voice, output, **kwargs):
            calls.append(text)
            output.write_bytes(text.encode())

    monkeypatch.setattr(wf, "ElevenLabsSpeech", Speech)
    client.put("/workflow/monthly-budget", headers=auth_headers, json={"limit_usd": "10"})
    cues = [{"start": 1, "end": 2, "text": "hello"}, {"start": 3, "end": 4, "text": "world"}]
    parent = create(
        audio_mode="dub", source_language="en", voice_id="voice", budget_usd="1", transcript=cues
    )
    for _ in range(4):
        wf.run_job(parent)
    assert calls == ["hello", "world"]
    child = create(
        audio_mode="dub",
        source_language="en",
        voice_id="voice",
        budget_usd="1",
        transcript=cues,
        translated_cues=[cues[0], {**cues[1], "text": "changed"}],
        reuse_from_job_id=parent,
    )
    results = [wf.run_job(child) for _ in range(4)]
    assert results[2]["status"] == "reused"
    assert calls == ["hello", "world", "changed"]
    session.expire_all()
    parent_job, child_job = session.get(Job, uuid.UUID(parent)), session.get(Job, uuid.UUID(child))
    assert parent_job.workflow_data["voices"][0] == child_job.workflow_data["voices"][0]
    assert parent_job.workflow_data["voices"][1] != child_job.workflow_data["voices"][1]
    child_budget = session.query(Budget).filter_by(scope="job", scope_ref=child).one()
    assert child_budget.spent_amount == Decimal("0.0070")
    # Unknown provider revisions never enable implicit cross-job cache reuse.
    independent = create(
        audio_mode="dub", source_language="en", voice_id="voice", budget_usd="1", transcript=cues
    )
    for _ in range(3):
        wf.run_job(independent)
    assert calls[-1] == "hello" and len(calls) == 4


def test_tts_hash_changes_for_voice_and_model_revision():
    from pipeline.workflow import WorkflowOptions

    data = {"translated": [{"text": "hello"}], "target": "en"}
    settings = get_settings()
    original = wf.tts_inputs(data, WorkflowOptions(voice_id="one"), settings).digest()
    assert original != wf.tts_inputs(data, WorkflowOptions(voice_id="two"), settings).digest()
    assert (
        original
        != wf.tts_inputs(
            data,
            WorkflowOptions(voice_id="one"),
            settings.model_copy(update={"tts_model_version": "new-revision"}),
        ).digest()
    )


def test_original_job_exports_source_language_subtitles(setup_flow, client, auth_headers):
    """원어 작업은 번역 단계가 없어 원본 대본을 원본 언어로 내보냅니다."""
    create, _ = setup_flow
    jid = create(source_language="ko")
    empty = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers)
    assert empty.status_code == 409 and "대본 단계" in empty.json()["detail"]
    assert wf.run_job(jid)["stage"] == "transcribe"

    srt = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers)
    assert srt.status_code == 200
    assert srt.headers["content-type"] == "application/x-subrip; charset=utf-8"
    assert srt.headers["content-disposition"] == f'attachment; filename="job-{jid}.ko.srt"'
    assert srt.text.startswith("1\n00:00:01,000 --> 00:00:02,000\nhello")

    vtt = client.get(f"/jobs/{jid}/subtitles?format=vtt", headers=auth_headers)
    assert vtt.text.startswith("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n")
    assert client.get(f"/jobs/{jid}/subtitles?format=ass", headers=auth_headers).status_code == 422
    assert client.get(f"/jobs/{uuid.uuid4()}/subtitles", headers=auth_headers).status_code == 404
    assert client.get(f"/jobs/{jid}/subtitles").status_code == 401


def test_dubbed_job_exports_the_speech_aligned_translation(
    setup_flow, client, auth_headers, session
):
    """더빙 작업은 합성 음성에 맞춰 재정렬한 번역 자막을 목표 언어로 내보냅니다."""
    create, _ = setup_flow
    jid = create()
    wf.run_job(jid)
    job = session.get(Job, uuid.UUID(jid))
    # 렌더가 쓰는 우선순위(aligned → translated → cues)를 그대로 확인합니다.
    job.workflow_data = {
        **job.workflow_data,
        "translated": [{"start": 1, "end": 2, "text": "번역 자막"}],
        "aligned": [{"start": 3, "end": 5, "text": "음성에 맞춘 자막"}],
    }
    session.commit()

    response = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="job-{jid}.en.srt"'
    assert "음성에 맞춘 자막" in response.text
    assert "번역 자막" not in response.text
    assert "hello" not in response.text


def test_export_uses_the_same_language_rules_as_the_render(
    setup_flow, client, auth_headers, session
):
    """영어 자막은 영어 규칙으로 나옵니다. 렌더가 목표 언어로 줄을 끊기 때문입니다."""
    from pipeline.editing import Cue
    from pipeline.subtitle_files import subtitle_file
    from pipeline.subtitles import DEFAULT_RULES, rules_for

    create, _ = setup_flow
    jid = create()
    wf.run_job(jid)
    long_line = "This sentence is long enough to be wrapped and split by the display rules."
    cues = [{"start": 0, "end": 9, "text": long_line}]
    job = session.get(Job, uuid.UUID(jid))
    job.workflow_data = {**job.workflow_data, "translated": cues}
    session.commit()

    text = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers).text
    parsed = [Cue.model_validate(c) for c in cues]
    assert text == subtitle_file(parsed, 0, 10, "srt", rules_for("en"))
    assert text != subtitle_file(parsed, 0, 10, "srt", DEFAULT_RULES)


def test_job_export_uses_the_rules_the_render_used(setup_flow, client, auth_headers, session):
    """설정을 렌더 뒤에 바꿔도 영상에 구워진 자막과 같은 줄로 내보냅니다.

    편집본 경로와 같은 규칙 기록을 작업 경로에도 둡니다. 기록이 없으면 지금
    설정을 쓰되 헤더로 그렇다고 알립니다.
    """
    create, _ = setup_flow
    jid = create(source_language="ko")
    wf.run_job(jid)

    before = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers)
    assert before.status_code == 200
    assert before.headers["x-subtitle-rules"] == "settings"

    job = session.get(Job, uuid.UUID(jid))
    job.workflow_data = {
        **job.workflow_data,
        "cues": [{"start": 0, "end": 8, "text": "가나다 라마바 사아자 차카타 파하가 나다라"}],
        "subtitle_rules": {"max_chars_per_line": 6, "max_lines": 1},
    }
    session.commit()

    after = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers)
    assert after.headers["x-subtitle-rules"] == "rendered"
    # 기록된 규칙(6자·1줄)이면 한 자막이 여러 개로 쪼개집니다.
    assert after.text.count("-->") > 1


def test_job_export_ignores_a_broken_rules_record(setup_flow, client, auth_headers, session):
    """기록이 깨졌다고 내려받기가 막히면 안 됩니다. 설정으로 내려주고 알립니다."""
    create, _ = setup_flow
    jid = create(source_language="ko")
    wf.run_job(jid)
    job = session.get(Job, uuid.UUID(jid))
    job.workflow_data = {**job.workflow_data, "subtitle_rules": {"max_chars_per_line": 0}}
    session.commit()

    response = client.get(f"/jobs/{jid}/subtitles", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["x-subtitle-rules"] == "settings"


def caption_service(existing=None, state=None, info=None):
    """게시 경로용 대역. 영상 조회와 자막 트랙 API만 흉내 냅니다."""
    tracks = {"existing": existing or [], "inserted": []}

    class Service:
        def channels(self):
            return SimpleNamespace(
                list=lambda **kw: SimpleNamespace(execute=lambda: {"items": [{"id": "channel"}]})
            )

        def videos(self):
            return SimpleNamespace(
                list=lambda **kw: SimpleNamespace(execute=lambda: {"items": [info]})
            )

        def captions(self):
            def insert(**kwargs):
                # 파일은 임시 폴더가 닫히면 사라지므로 지금 읽어 둡니다.
                sent = Path(kwargs["media_body"]._filename).read_text(encoding="utf-8")
                tracks["inserted"].append({**kwargs, "text": sent})
                return SimpleNamespace(execute=lambda: {"id": "caption-1"})

            return SimpleNamespace(
                list=lambda **kw: SimpleNamespace(execute=lambda: {"items": tracks["existing"]}),
                insert=insert,
            )

    return Service, tracks


def publish_ready(client, auth_headers, create, monkeypatch, **overrides):
    """승인까지 끝낸 게시 요청 하나를 만들고 그 ID를 돌려줍니다."""
    from adminapi.routers import workflow

    settings = get_settings().model_copy(update={"youtube_channel_id": "channel", **overrides})
    monkeypatch.setattr(workflow, "get_settings", lambda: settings)
    monkeypatch.setattr(pub, "get_settings", lambda: settings)
    jid = create(source_language="ko")
    for _ in range(3):
        wf.run_job(jid)
    aid = client.get(f"/jobs/{jid}/workflow", headers=auth_headers).json()["artifact_id"]
    client.post(f"/artifacts/{aid}/approve", headers=auth_headers)
    response = client.post(
        "/publications",
        headers=auth_headers,
        json={
            "artifact_id": aid,
            "title": "test",
            "made_for_kids": False,
            "publish_at": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["id"], jid


def test_caption_track_is_uploaded_once_with_the_burned_in_subtitles(
    setup_flow, client, auth_headers, monkeypatch
):
    """설정을 켜면 영상에 구운 자막과 같은 내용을 트랙으로 올립니다. 두 번 올리지 않습니다."""
    create, _ = setup_flow
    pid, jid = publish_ready(
        client, auth_headers, create, monkeypatch, youtube_captions_enabled=True
    )
    state = {"privacyStatus": "private"}
    info = {
        "snippet": {"channelId": "channel"},
        "status": state,
        "processingDetails": {"processingStatus": "succeeded"},
    }
    Service, tracks = caption_service(info=info)
    monkeypatch.setattr(pub, "youtube_service", Service)
    monkeypatch.setattr(pub, "upload_approved", lambda *a, **kw: "video")
    monkeypatch.setattr(
        pub, "schedule_video", lambda service, vid, at, **kw: state.update(publishAt=at.isoformat())
    )

    pub.run_publication(pid)
    assert len(tracks["inserted"]) == 1
    sent = tracks["inserted"][0]
    assert sent["body"]["snippet"]["language"] == "ko"
    # 올린 파일은 내려받기 경로가 주는 자막과 같아야 합니다. 같은 함수를 씁니다.
    assert sent["text"] == client.get(f"/jobs/{jid}/subtitles", headers=auth_headers).text
    row = client.get("/publications", headers=auth_headers).json()[0]
    assert row["captions"]["state"] == "uploaded"
    assert row["captions"]["language"] == "ko"
    assert row["captions"]["rules"] == "rendered"

    # 다시 실행해도 트랙이 늘지 않습니다. 기록에 남은 트랙 ID로 걸러집니다.
    pub.run_publication(pid)
    assert len(tracks["inserted"]) == 1


def test_caption_failure_does_not_fail_the_publication(
    setup_flow, client, auth_headers, monkeypatch
):
    """영상은 이미 올라가 있습니다. 자막 때문에 게시를 실패로 만들지 않습니다."""
    create, _ = setup_flow
    pid, _jid = publish_ready(
        client, auth_headers, create, monkeypatch, youtube_captions_enabled=True
    )
    state = {"privacyStatus": "private"}
    info = {
        "snippet": {"channelId": "channel"},
        "status": state,
        "processingDetails": {"processingStatus": "succeeded"},
    }
    Service, _tracks = caption_service(info=info)
    monkeypatch.setattr(pub, "youtube_service", Service)
    monkeypatch.setattr(pub, "upload_approved", lambda *a, **kw: "video")
    monkeypatch.setattr(
        pub, "schedule_video", lambda service, vid, at, **kw: state.update(publishAt=at.isoformat())
    )

    def broken(*args, **kwargs):
        raise RuntimeError("quota exceeded: secret-token-in-url")

    monkeypatch.setattr(pub, "upload_captions", broken)
    assert pub.run_publication(pid)["status"] == "scheduled"
    row = client.get("/publications", headers=auth_headers).json()[0]
    assert row["state"] == "scheduled"
    assert row["captions"]["state"] == "failed"
    assert "secret-token" not in str(row["captions"])


def test_captions_stay_off_until_the_setting_is_turned_on(
    setup_flow, client, auth_headers, monkeypatch
):
    """기본값은 꺼짐입니다. 영상에 자막이 이미 구워져 있어 두 벌로 보일 수 있습니다."""
    create, _ = setup_flow
    pid, _jid = publish_ready(client, auth_headers, create, monkeypatch)
    state = {"privacyStatus": "private"}
    info = {
        "snippet": {"channelId": "channel"},
        "status": state,
        "processingDetails": {"processingStatus": "succeeded"},
    }
    Service, tracks = caption_service(info=info)
    monkeypatch.setattr(pub, "youtube_service", Service)
    monkeypatch.setattr(pub, "upload_approved", lambda *a, **kw: "video")
    monkeypatch.setattr(
        pub, "schedule_video", lambda service, vid, at, **kw: state.update(publishAt=at.isoformat())
    )
    pub.run_publication(pid)
    assert tracks["inserted"] == []
    assert client.get("/publications", headers=auth_headers).json()[0]["captions"] is None
