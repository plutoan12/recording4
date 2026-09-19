"""Durable workflow tests: no external credentials or network calls."""

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal
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

    def create(target_language="en", **options):
        response = client.post(
            "/jobs",
            headers=auth_headers,
            json={
                "source_asset_id": str(asset.id),
                "target_language": target_language,
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


@pytest.mark.parametrize("budget,allowed", [("1", True), ("0", False)])
def test_subtitle_translation_budget_and_no_dubbing(
    setup_flow, client, auth_headers, session, monkeypatch, budget, allowed
):
    create, _ = setup_flow
    settings = get_settings().model_copy(
        update={
            "paid_processing_enabled": True,
            "google_cloud_project": "test-project",
            "translate_usd_per_1k_chars": Decimal("1"),
            "elevenlabs_api_key": "",
        }
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)
    calls = []

    class Translator:
        def __init__(self, *args, **kwargs):
            pass

        def translate(self, texts, target, source):
            calls.append((texts, target, source))
            return ["안녕하세요"]

    def forbidden(*args, **kwargs):
        pytest.fail("subtitle mode called an audio replacement stage")

    def render(source, output, **kwargs):
        assert source.read_bytes() == b"source bytes"
        assert kwargs["cues"][0].text == "안녕하세요"
        assert kwargs["cues"][0].original_text == "hello"
        assert kwargs["subtitle_template"] == "bilingual"
        assert kwargs["cues"][0].start == 1
        output.write_bytes(b"final")

    monkeypatch.setattr(wf, "GoogleTranslator", Translator)
    for name in ("ElevenLabsSpeech", "mix_speech", "compose_dub"):
        monkeypatch.setattr(wf, name, forbidden)
    monkeypatch.setattr(wf, "render_final", render)
    client.put("/workflow/monthly-budget", headers=auth_headers, json={"limit_usd": "10"})
    jid = create(
        audio_mode="subtitles",
        source_language="en",
        target_language="ko",
        budget_usd=budget,
        subtitle_template="bilingual",
    )
    assert wf.run_job(jid)["stage"] == "transcribe"
    result = wf.run_job(jid)
    if not allowed:
        assert result["status"] == "blocked_or_failed"
        assert calls == []
        return
    assert calls == [(["hello"], "ko", "en")]
    assert result["stage"] == "translate:0"
    assert wf.run_job(jid)["stage"] == "render"
    assert wf.run_job(jid)["status"] == "review_required"
    assert all(b.spent_amount == Decimal("0.0050") for b in session.query(Budget).all())


def test_edited_subtitles_keep_clip_offset_without_provider_calls(setup_flow, monkeypatch):
    create, _ = setup_flow

    def forbidden(*args, **kwargs):
        pytest.fail("supplied subtitle edit must not call paid providers")

    def render(source, output, **kwargs):
        assert source.read_bytes() == b"source bytes"
        assert kwargs["start"] == 1
        assert kwargs["duration"] == 3
        assert kwargs["cues"][0].start == 0
        assert kwargs["cues"][0].end == 1
        assert kwargs["cues"][0].text == "수정한 자막"
        output.write_bytes(b"edited")

    monkeypatch.setattr(wf, "GoogleTranslator", forbidden)
    monkeypatch.setattr(wf, "ElevenLabsSpeech", forbidden)
    monkeypatch.setattr(wf, "render_final", render)
    jid = create(
        audio_mode="subtitles",
        target_language="ko",
        clip={"start": 1, "end": 4},
        translated_cues=[{"start": 0, "end": 1, "text": "수정한 자막"}],
    )
    for stage in ("transcribe", "translate:0", "render"):
        assert wf.run_job(jid)["stage"] == stage
    assert wf.run_job(jid)["status"] == "review_required"


def test_subtitles_reject_lipsync_and_empty_transcript(setup_flow):
    from pydantic import ValidationError

    from pipeline.workflow import WorkflowOptions

    with pytest.raises(ValidationError):
        WorkflowOptions(audio_mode="subtitles", lipsync=True)
    create, _ = setup_flow
    jid = create(audio_mode="subtitles", transcript=[])
    assert wf.run_job(jid)["status"] == "blocked_or_failed"
