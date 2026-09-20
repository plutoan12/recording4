import base64
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from adminapi.models import Approval, Artifact, SourceAsset
from pipeline import subtitle_files


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


def upload(text: str, encoding: str = "utf-8") -> dict:
    """브라우저가 보내는 모양대로 파일 바이트를 base64로 싣습니다."""
    return {"content_base64": base64.b64encode(text.encode(encoding)).decode()}


def test_imported_subtitles_become_a_new_transcript_version(client, auth_headers, asset):
    """밖에서 만든 자막 파일을 대본으로 들입니다. 기존 버전은 남습니다."""
    path = f"/source-assets/{asset.id}/transcript"
    client.put(
        path, headers=auth_headers, json={"cues": [{"start": 1, "end": 2, "text": "옛 대본"}]}
    )
    srt = "1\n00:00:03,000 --> 00:00:05,000\n들여온 자막\n둘째 줄\n"

    response = client.post(f"{path}/import", headers=auth_headers, json=upload(srt))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == 2 and body["count"] == 1 and body["skipped"] == []
    assert client.get(path, headers=auth_headers).json() == [
        {"start": 3.0, "end": 5.0, "text": "들여온 자막 둘째 줄"}
    ]


def test_import_reports_what_it_skipped_and_refuses_what_it_cannot_use(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/transcript/import"
    assert client.post(path, json=upload("x")).status_code == 401
    assert client.post(path, headers=auth_headers, json=upload("자막 아님")).status_code == 422
    assert (
        client.post(path, headers=auth_headers, json={"content_base64": "***"}).status_code == 422
    )

    # 원본 길이(120초)를 넘는 자막은 저장하지 않습니다.
    too_long = "1\n00:02:30,000 --> 00:02:35,000\n원본보다 뒤\n"
    assert client.post(path, headers=auth_headers, json=upload(too_long)).status_code == 422

    mixed = (
        "1\n00:00:01,000 --> 00:00:02,000\n쓸 자막\n\n2\n00:00:03,000 --> 00:00:03,000\n길이 0\n"
    )
    body = client.post(path, headers=auth_headers, json=upload(mixed)).json()
    assert body["count"] == 1
    assert len(body["skipped"]) == 1 and "2번" in body["skipped"][0]


def test_a_cp949_file_is_read_by_the_detector_and_says_it_guessed(client, auth_headers, asset):
    """한국어 자막에 흔한 CP949는 판별기가 읽습니다. 무엇으로 읽었는지 함께 돌려줍니다."""
    path = f"/source-assets/{asset.id}/transcript/import"
    srt = "1\n00:00:01,000 --> 00:00:02,000\n안녕하세요 자막입니다\n"

    saved = client.post(path, headers=auth_headers, json=upload(srt, "cp949"))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["count"] == 1 and body["encoding"] == "cp949"
    # 판별은 추측이라 밝힙니다. 화면이 이 표시를 보고 사람에게 확인을 청합니다.
    assert body["encoding_detected"] is True
    assert client.get(f"/source-assets/{asset.id}/transcript", headers=auth_headers).json() == [
        {"start": 1.0, "end": 2.0, "text": "안녕하세요 자막입니다"}
    ]


def test_a_utf8_file_is_not_marked_as_a_guess(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/transcript/import"
    srt = "1\n00:00:01,000 --> 00:00:02,000\n안녕하세요\n"
    body = client.post(path, headers=auth_headers, json=upload(srt)).json()
    assert body["encoding"] == "utf-8" and body["encoding_detected"] is False


def test_a_file_the_detector_cannot_place_asks_instead_of_saving_broken_text(
    client, auth_headers, asset, monkeypatch
):
    """판별까지 실패하면 추측해서 저장하지 않습니다. 후보를 미리보기와 함께 돌려줍니다.

    잘못 고르면 글자가 조용히 깨진 채로 저장되고 나중에 영상에 그대로 구워집니다.
    이름만 보고는 못 골라도 자기 자막 글자는 알아봅니다.
    """
    monkeypatch.setattr(subtitle_files, "detect_encoding", lambda data: None)
    path = f"/source-assets/{asset.id}/transcript/import"
    srt = "1\n00:00:01,000 --> 00:00:02,000\n안녕하세요 자막입니다\n"

    asked = client.post(path, headers=auth_headers, json=upload(srt, "cp949"))
    assert asked.status_code == 422
    detail = asked.json()["detail"]
    assert "인코딩" in detail["message"]
    correct = [c for c in detail["choices"] if c["preview"] == "안녕하세요 자막입니다"]
    assert correct and correct[0]["encoding"] == "cp949"
    # 글자가 깨져 보이는 후보도 함께 보여 주어 사람이 고를 수 있게 합니다.
    assert len(detail["choices"]) > 1
    assert client.get(f"/source-assets/{asset.id}/transcript", headers=auth_headers).json() == []

    saved = client.post(
        path, headers=auth_headers, json={**upload(srt, "cp949"), "encoding": "cp949"}
    )
    assert saved.status_code == 200 and saved.json()["count"] == 1
    assert saved.json()["encoding_detected"] is False
    assert client.get(f"/source-assets/{asset.id}/transcript", headers=auth_headers).json() == [
        {"start": 1.0, "end": 2.0, "text": "안녕하세요 자막입니다"}
    ]


def test_a_wrong_encoding_choice_is_reported_not_saved(client, auth_headers, asset):
    path = f"/source-assets/{asset.id}/transcript/import"
    srt = "1\n00:00:01,000 --> 00:00:02,000\n안녕하세요\n"
    response = client.post(
        path, headers=auth_headers, json={**upload(srt, "cp949"), "encoding": "utf-8"}
    )
    assert response.status_code == 422 and "utf-8" in response.json()["detail"]


def test_sync_needs_a_transcript_and_does_not_queue_twice(client, auth_headers, asset, monkeypatch):
    """보정은 최신 대본을 대상으로 합니다. 대본이 없으면 요청을 만들지 않습니다."""
    path = f"/source-assets/{asset.id}/transcript/sync"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=auth_headers).status_code == 409

    client.put(
        f"/source-assets/{asset.id}/transcript",
        headers=auth_headers,
        json={"cues": [{"start": 3, "end": 5, "text": "어긋난 자막"}]},
    )
    first = client.post(path, headers=auth_headers)
    assert first.status_code == 202 and first.json()["kind"] == "sync"
    # 같은 요청을 다시 눌러도 작업이 늘지 않습니다.
    assert client.post(path, headers=auth_headers).json()["id"] == first.json()["id"]


def test_sync_saves_a_new_version_and_keeps_the_old_one(client, auth_headers, asset, monkeypatch):
    """보정은 새 대본 버전을 만듭니다. 마음에 들지 않으면 옛 버전을 다시 쓰면 됩니다."""
    import worker.media_tasks as module
    from pipeline.editing import Cue

    class Storage:
        def download_file(self, key, path):
            path.write_bytes(b"media")

    monkeypatch.setattr(module, "get_storage", lambda: Storage())
    # 보정기는 여기서 대역입니다. 실제 보정 품질은 test_subtitle_sync.py가 봅니다.
    monkeypatch.setattr(
        module,
        "sync_subtitles",
        lambda source, cues, options=None, **kwargs: (
            [Cue(start=c.start + 2, end=c.end + 2, text=c.text) for c in cues],
            {"offset_seconds": 2.0, "framerate_scale": 1.0, "clamped": 0},
        ),
    )
    client.put(
        f"/source-assets/{asset.id}/transcript",
        headers=auth_headers,
        json={"cues": [{"start": 3, "end": 5, "text": "어긋난 자막"}]},
    )
    created = client.post(f"/source-assets/{asset.id}/transcript/sync", headers=auth_headers).json()

    result = module.run_media.run(created["id"])
    assert result["status"] == "succeeded"
    assert result["sync"] == {"offset_seconds": 2.0, "framerate_scale": 1.0, "clamped": 0}
    assert result["transcript_version"] == 2
    assert client.get(f"/source-assets/{asset.id}/transcript", headers=auth_headers).json() == [
        {"start": 5.0, "end": 7.0, "text": "어긋난 자막"}
    ]


def test_subtitle_templates_are_listed_and_a_clip_remembers_its_template(
    client, auth_headers, asset, session
):
    from adminapi.models import ClipEdit, MediaTask

    assert client.get("/subtitle-templates").status_code == 401
    listed = client.get("/subtitle-templates", headers=auth_headers)
    assert listed.status_code == 200
    names = [t["name"] for t in listed.json()]
    assert names[0] == "default" and "yellow" in names
    assert all(
        {"label", "font_size", "primary_color", "category_label", "sample"} <= set(t)
        for t in listed.json()
    )
    assert listed.json()[0]["category_label"] == "기본"

    data = {"source_asset_id": str(asset.id), "start": 10, "end": 40, "subtitle_template": "yellow"}
    created = client.post("/clips", headers=auth_headers, json=data)
    assert created.status_code == 202, created.text
    clip = session.get(ClipEdit, uuid.UUID(created.json()["clip_edit_id"]))
    assert clip.subtitle_style == {"template": "yellow", "font_size": 64, "animation": "none"}
    task = session.get(MediaTask, uuid.UUID(created.json()["id"]))
    assert task.settings["subtitle_template"] == "yellow"

    # 템플릿을 안 주면 기본이고, 모르는 이름은 저장 전에 거절합니다.
    plain = client.post("/clips", headers=auth_headers, json={**data, "subtitle_template": None})
    assert plain.status_code == 422
    del data["subtitle_template"]
    assert client.post("/clips", headers=auth_headers, json=data).status_code == 202
    unknown = client.post(
        "/clips", headers=auth_headers, json={**data, "subtitle_template": "nope"}
    )
    assert unknown.status_code == 422 and "모르는 자막 템플릿" in unknown.json()["detail"]

    # 움직임은 템플릿 값을 덮어쓰고 편집본에 기록됩니다. 모르는 이름은 거절합니다.
    animations = client.get("/subtitle-animations", headers=auth_headers).json()
    assert {"name": "pop", "label": "팝(튀어나옴)"} in animations
    assert listed.json()[0]["animation_label"] == "없음"
    moving = client.post("/clips", headers=auth_headers, json={**data, "subtitle_animation": "pop"})
    assert moving.status_code == 202, moving.text
    clip = session.get(ClipEdit, uuid.UUID(moving.json()["clip_edit_id"]))
    assert clip.subtitle_style["animation"] == "pop"
    assert (
        session.get(MediaTask, uuid.UUID(moving.json()["id"])).settings["subtitle_animation"]
        == "pop"
    )
    bad = client.post("/clips", headers=auth_headers, json={**data, "subtitle_animation": "spin"})
    assert bad.status_code == 422 and "모르는 움직임" in bad.json()["detail"]
