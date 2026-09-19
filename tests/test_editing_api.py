import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from adminapi.models import Approval, Artifact, SourceAsset


@pytest.fixture
def asset(session, user):
    asset = SourceAsset(
        storage_key=f"sources/{uuid.uuid4()}.mp4",
        original_filename="test.mp4",
        created_by_id=user.id,
        duration_seconds=Decimal("120"),
        width=1920,
        height=1080,
        upload_state="verified",
    )
    session.add(asset)
    session.commit()
    return asset


def test_auth_required(client):
    assert client.get("/media-tasks").status_code == 401
    assert client.post("/clips", json={}).status_code == 401


def test_range_validation_and_independent_clips(client, auth_headers, asset):
    data = {"source_asset_id": str(asset.id), "start": 100, "end": 130}
    assert client.post("/clips", headers=auth_headers, json=data).status_code == 422
    data.update(start=10, end=40)
    a = client.post("/clips", headers=auth_headers, json=data)
    b = client.post("/clips", headers=auth_headers, json=data)
    assert a.status_code == b.status_code == 202
    assert a.json()["clip_edit_id"] != b.json()["clip_edit_id"]
    assert a.json()["state"] == "pending"
    assert (
        client.post(f"/media-tasks/{a.json()['id']}/retry", headers=auth_headers).status_code == 409
    )


def test_transcript_snapshots_and_suggestions(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/transcript"
    cues = [{"start": 2, "end": 10, "text": "hello"}]
    assert client.put(path, headers=auth_headers, json={"cues": cues}).json()["version"] == 1
    assert client.get(path, headers=auth_headers).json() == cues
    assert (
        client.get(f"/source-assets/{asset.id}/suggestions", headers=auth_headers).json()[0][
            "start"
        ]
        == 2
    )
    assert client.put(path, headers=auth_headers, json={"cues": cues}).json()["version"] == 2
    cues[0]["end"] = 200
    assert client.put(path, headers=auth_headers, json={"cues": cues}).status_code == 422


def test_analysis_deduplicates_active_requests(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/analyze"
    a = client.post(path, headers=auth_headers, json={"kind": "scenes"}).json()
    b = client.post(path, headers=auth_headers, json={"kind": "scenes"}).json()
    assert a["id"] == b["id"]


def test_render_worker_and_version_approval(
    client, auth_headers, asset, session, tmp_path, monkeypatch
):
    import worker.media_tasks as module
    from adminapi.db import get_session_factory

    class Storage:
        def download_file(self, key, path):
            path.write_bytes(b"input")

        def upload_file(self, key, path, content_type):
            assert path.read_bytes() == b"rendered"

    monkeypatch.setattr(module, "get_storage", lambda: Storage())
    monkeypatch.setattr(
        module, "render_clip", lambda source, output, spec, **_: output.write_bytes(b"rendered")
    )
    data = {"source_asset_id": str(asset.id), "start": 0, "end": 10}
    created = client.post("/clips", headers=auth_headers, json=data).json()
    result = module.run_media.run(created["id"])
    assert result["status"] == "succeeded"
    assert module.run_media.run(created["id"])["status"] == "already_claimed"
    artifact_id = result["artifact_id"]
    first = client.post(f"/artifacts/{artifact_id}/approve", headers=auth_headers).json()
    second = client.post(f"/artifacts/{artifact_id}/approve", headers=auth_headers).json()
    assert first == second
    another = client.post("/clips", headers=auth_headers, json={**data, "title": "new"}).json()
    result2 = module.run_media.run(another["id"])
    with get_session_factory()() as db:
        assert (
            db.scalar(
                select(Approval).where(Approval.artifact_id == uuid.UUID(result2["artifact_id"]))
            )
            is None
        )
        assert len(list(db.scalars(select(Artifact)))) == 2


def test_failed_worker_can_retry(client, auth_headers, asset, monkeypatch):
    import worker.media_tasks as module

    class BrokenStorage:
        def download_file(self, *args):
            raise RuntimeError("secret-token-in-url")

    monkeypatch.setattr(module, "get_storage", lambda: BrokenStorage())
    created = client.post(
        "/clips",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "start": 0, "end": 10},
    ).json()
    assert module.run_media.run(created["id"])["status"] == "failed"
    tasks = client.get("/media-tasks", headers=auth_headers).json()
    assert "secret-token" not in str(tasks)
    retry = client.post(f"/media-tasks/{created['id']}/retry", headers=auth_headers)
    assert retry.status_code == 202 and retry.json()["state"] == "pending"


def test_subtitle_export_uses_the_clip_edit_snapshot(client, auth_headers, asset):
    """대본이 뒤에 바뀌어도 편집본에 저장된 자막을 그대로 내보냅니다."""
    cues = [{"start": 12, "end": 16, "text": "편집본에 저장한 자막"}]
    created = client.post(
        "/clips",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "start": 10, "end": 20, "cues": cues},
    ).json()
    clip_id = created["clip_edit_id"]
    client.put(
        f"/source-assets/{asset.id}/transcript",
        headers=auth_headers,
        json={"cues": [{"start": 12, "end": 16, "text": "나중에 바꾼 대본"}]},
    )

    srt = client.get(f"/clips/{clip_id}/subtitles", headers=auth_headers)
    assert srt.status_code == 200
    assert srt.headers["content-type"] == "application/x-subrip; charset=utf-8"
    assert srt.headers["content-disposition"] == f'attachment; filename="clip-{clip_id}.srt"'
    assert srt.text.startswith("1\n00:00:02,000 --> 00:00:06,000\n편집본에 저장한 자막")
    assert "나중에 바꾼 대본" not in srt.text

    vtt = client.get(f"/clips/{clip_id}/subtitles?format=vtt", headers=auth_headers)
    assert vtt.status_code == 200
    assert vtt.headers["content-type"] == "text/vtt; charset=utf-8"
    assert vtt.text.startswith("WEBVTT\n\n1\n00:00:02.000 --> 00:00:06.000\n")


def test_subtitle_export_rejects_unknown_clip_format_and_empty_captions(
    client, auth_headers, asset
):
    assert client.get(f"/clips/{uuid.uuid4()}/subtitles").status_code == 401
    missing = client.get(f"/clips/{uuid.uuid4()}/subtitles", headers=auth_headers)
    assert missing.status_code == 404
    created = client.post(
        "/clips",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "start": 0, "end": 10},
    ).json()
    clip_id = created["clip_edit_id"]
    assert (
        client.get(f"/clips/{clip_id}/subtitles?format=ass", headers=auth_headers).status_code
        == 422
    )
    empty = client.get(f"/clips/{clip_id}/subtitles", headers=auth_headers)
    assert empty.status_code == 409 and "자막이 없습니다" in empty.json()["detail"]


def test_subtitle_export_uses_the_rules_the_render_used(client, auth_headers, asset, monkeypatch):
    """설정을 렌더 뒤에 바꿔도 영상에 구워진 자막과 같은 줄로 내보냅니다.

    표시 규칙이 바뀌면 줄바꿈과 분할이 달라집니다. 지금 설정으로 다시 계산하면
    사람은 영상과 같은 자막이라고 믿고 다른 파일을 올립니다.
    """
    import worker.media_tasks as worker_module
    from adminapi.routers import editing
    from pipeline.subtitles import SubtitleRules

    used: dict = {}

    class Storage:
        def download_file(self, key, path):
            path.write_bytes(b"input")

        def upload_file(self, key, path, content_type):
            pass

    def fake_render(source, output, spec, **kwargs):
        used["rules"] = kwargs["rules"]
        output.write_bytes(b"rendered")

    monkeypatch.setattr(worker_module, "get_storage", lambda: Storage())
    monkeypatch.setattr(worker_module, "render_clip", fake_render)

    cues = [{"start": 0, "end": 8, "text": "가나다 라마바 사아자 차카타 파하가 나다라"}]
    created = client.post(
        "/clips",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "start": 0, "end": 10, "cues": cues},
    ).json()
    assert worker_module.run_media.run(created["id"])["status"] == "succeeded"
    assert used["rules"].max_chars_per_line == 16

    # 렌더가 끝난 뒤 설정을 바꿉니다. 이 편집본은 다시 렌더하지 않았습니다.
    monkeypatch.setattr(editing, "subtitle_rules", lambda: SubtitleRules(max_chars_per_line=6))
    srt = client.get(f"/clips/{created['clip_edit_id']}/subtitles", headers=auth_headers)
    assert srt.status_code == 200
    assert srt.headers["x-subtitle-rules"] == "rendered"
    # 바뀐 설정(6자)이었다면 한 자막이 여러 개로 쪼개집니다.
    assert srt.text.count("-->") == 1


def test_subtitle_export_says_when_the_rendered_rules_are_unknown(client, auth_headers, asset):
    """이 기능 전에 렌더한 기록에는 그때 쓴 규칙이 없습니다. 아는 척하지 않습니다."""
    cues = [{"start": 0, "end": 8, "text": "규칙 기록이 없는 옛 편집본"}]
    created = client.post(
        "/clips",
        headers=auth_headers,
        json={"source_asset_id": str(asset.id), "start": 0, "end": 10, "cues": cues},
    ).json()
    srt = client.get(f"/clips/{created['clip_edit_id']}/subtitles", headers=auth_headers)
    assert srt.status_code == 200
    assert srt.headers["x-subtitle-rules"] == "settings"


def test_broken_rules_record_falls_back_instead_of_failing() -> None:
    """기록이 깨졌다고 자막 내려받기가 막히면 안 됩니다. 설정으로 내려주고 알립니다."""
    from adminapi.subtitle_rules import rules_from_record

    for saved in ({"max_chars_per_line": 0}, {"max_cps": "여섯"}, "규칙 아님", None):
        rules, source = rules_from_record(saved)
        assert source == "settings" and rules.max_chars_per_line == 16

    rules, source = rules_from_record({"max_chars_per_line": 9})
    assert source == "rendered" and rules.max_chars_per_line == 9


def test_every_analysis_kind_the_api_accepts_can_actually_be_stored(client, auth_headers, asset):
    """**이 시험이 없어서 faces가 깨진 채로 나갔습니다.**

    API는 받는데 DB 제약이 거절했습니다(실측: CHECK constraint failed:
    ck_media_task_kind). 받는 종류와 저장할 수 있는 종류를 여기서 묶어 둡니다.
    """
    import typing

    from adminapi.routers.editing import AnalysisRequest

    kinds = typing.get_args(AnalysisRequest.model_fields["kind"].annotation)
    assert "faces" in kinds
    for kind in kinds:
        made = client.post(
            f"/source-assets/{asset.id}/analyze", headers=auth_headers, json={"kind": kind}
        )
        assert made.status_code == 202, f"{kind}: {made.text}"


def test_highlights_needs_a_transcript_and_is_queued_not_called(
    client, auth_headers, asset, session
):
    """유료 호출은 여기서 하지 않습니다. 예산을 잡은 뒤 워커가 합니다."""
    from adminapi.models import MediaTask, OutboxMessage

    where = f"/source-assets/{asset.id}/highlights"
    assert client.post(where, headers=auth_headers).status_code == 409

    path = f"/source-assets/{asset.id}/transcript"
    cues = [{"start": i * 6, "end": i * 6 + 6, "text": f"{i}번째"} for i in range(8)]
    client.put(path, headers=auth_headers, json={"cues": cues})

    made = client.post(where, headers=auth_headers)
    assert made.status_code == 202 and made.json()["state"] == "pending"
    # 같은 요청을 두 번 눌러도 유료 호출이 두 번 생기지 않습니다.
    assert client.post(where, headers=auth_headers).json()["id"] == made.json()["id"]

    task = session.get(MediaTask, uuid.UUID(made.json()["id"]))
    assert task.kind == "highlights"
    topics = [m.topic for m in session.scalars(select(OutboxMessage))]
    assert "media.highlights" in topics
