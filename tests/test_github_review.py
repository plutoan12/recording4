"""GitHub 저장소 자막 검수: 규칙 검사 · 어댑터 계약 · 작업 · API.

실제 GitHub은 부르지 않습니다. 여기서 보는 것은 **남이 고쳐 돌아온 자막을 그대로
믿지 않는지**와, 기본 브랜치에 쓰거나 병합하지 않는지입니다.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from adminapi.config import get_settings
from adminapi.models import Job, SourceAsset, SubtitleReview
from adminapi.routers import workflow as api
from pipeline.editing import Cue
from pipeline.review import (
    branch_for,
    compare,
    glossary_tsv,
    parse_glossary_tsv,
    pull_request_body,
    subtitle_path,
)
from pipeline.subtitle_files import dump_subtitles
from pipeline.workflow import WorkflowOptions
from worker import review_tasks as rt
from worker.github import GitHubError, GitHubRepository

ORIGINAL = [Cue(start=1, end=3, text="Hello"), Cue(start=4, end=6, text="Nice to meet you")]


# ─── 규칙 검사 (네트워크 없음) ──────────────────────────────────────────────


def test_glossary_tsv_round_trips_and_keeps_bare_terms():
    entries = {"방탄소년단": "BTS", "아이유": None}
    assert parse_glossary_tsv(glossary_tsv(entries)) == entries
    # 사람이 손으로 고치는 파일이라 주석·빈 줄·CRLF·앞뒤 공백을 견딥니다.
    assert parse_glossary_tsv("# 주석\r\n\r\n 뉴진스 \tNewJeans \r\n") == {"뉴진스": "NewJeans"}


def test_same_subtitles_come_back_clean():
    assert compare(ORIGINAL, list(ORIGINAL)) == []
    edited = [Cue(start=1, end=3, text="안녕"), Cue(start=4, end=6, text="반가워")]
    assert compare(ORIGINAL, edited) == []


def test_merged_or_split_lines_stop_the_import():
    problems = compare(ORIGINAL, ORIGINAL[:1])
    assert len(problems) == 1 and "개수가 다릅니다" in problems[0]


def test_changed_timings_are_reported():
    moved = [Cue(start=1, end=3, text="Hello"), Cue(start=4.5, end=6, text="Nice")]
    assert "시각이 바뀌었습니다" in compare(ORIGINAL, moved)[0]
    # 밀리초 미만의 흔들림은 SRT 왕복에서 생기므로 문제가 아닙니다.
    assert compare(ORIGINAL, [Cue(start=1.0004, end=3, text="Hello"), ORIGINAL[1]]) == []


def test_pull_request_body_tells_the_translator_the_rules():
    body = pull_request_body("subtitles/x/en.srt", "glossary/ko-en.tsv", "en")
    assert "시각" in body and "합치거나 나누지 마세요" in body and "glossary/ko-en.tsv" in body


# ─── GitHub 어댑터 계약 ─────────────────────────────────────────────────────


def contents(text: str) -> dict:
    raw = text.encode()
    return {
        "content": base64.b64encode(raw).decode(),
        "encoding": "base64",
        "sha": "filesha",
        "size": len(raw),
    }


def repo(handler, *, allow_write=True) -> GitHubRepository:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GitHubRepository("token", "owner/repo", client=client, allow_write=allow_write)


def test_repository_must_be_owner_slash_name():
    with httpx.Client() as client:
        for bad in ("repo", "a/b/c", "/repo"):
            with pytest.raises(ValueError):
                GitHubRepository("t", bad, client=client)


def test_writes_are_blocked_before_any_request_when_review_is_off():
    adapter = repo(lambda request: pytest.fail("unexpected network"), allow_write=False)
    with pytest.raises(GitHubError, match="꺼져 있습니다"):
        adapter.create_branch("b", "sha")
    with pytest.raises(GitHubError, match="꺼져 있습니다"):
        adapter.put_file("p", "b", "t", "m")
    with pytest.raises(GitHubError, match="꺼져 있습니다"):
        adapter.open_pull_request("b", "main", "t", "b")


def test_unchanged_file_is_not_committed_again():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json=contents("same"))

    assert repo(handler).put_file("subtitles/a.srt", "branch", "same", "m") is None
    assert [m for m, _ in seen] == ["GET"]


def test_changed_file_sends_the_existing_sha():
    sent = {}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=contents("before"))
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"commit": {"sha": "newsha"}})

    assert repo(handler).put_file("subtitles/a.srt", "branch", "after", "message") == "newsha"
    assert sent["sha"] == "filesha" and sent["branch"] == "branch"
    assert base64.b64decode(sent["content"]).decode() == "after"


def test_a_missing_file_or_branch_is_not_an_error():
    adapter = repo(lambda request: httpx.Response(404, json={"message": "Not Found"}))
    assert adapter.file("nope.srt", "branch") is None
    assert adapter.branch_sha("nope") is None


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"encoding": "none", "size": 1, "content": ""}, "인코딩"),
        ({"encoding": "base64", "size": 9_000_000, "content": ""}, "너무 큽니다"),
        (
            {
                "encoding": "base64",
                "size": 2,
                "sha": "s",
                "content": base64.b64encode(b"\xff\xfe").decode(),
            },
            "UTF-8",
        ),
    ],
)
def test_unreadable_files_are_refused_not_guessed(payload, message):
    adapter = repo(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(GitHubError, match=message):
        adapter.file("subtitles/a.srt", "branch")


def test_a_folder_is_not_a_subtitle_file():
    adapter = repo(lambda request: httpx.Response(200, json=[{"name": "a"}]))
    with pytest.raises(GitHubError, match="폴더"):
        adapter.file("subtitles", "branch")


def test_an_open_pull_request_is_reused_instead_of_opening_another():
    posted = []

    def handler(request):
        if request.method == "GET":
            assert request.url.params["head"] == "owner:branch"
            return httpx.Response(200, json=[{"number": 12, "html_url": "https://gh.test/12"}])
        posted.append(request)
        return httpx.Response(201, json={"number": 99, "html_url": "x"})

    assert repo(handler).open_pull_request("branch", "main", "t", "b") == (12, "https://gh.test/12")
    assert posted == []


def test_an_existing_branch_is_kept():
    def handler(request):
        return httpx.Response(422, json={"message": "Reference already exists"})

    repo(handler).create_branch("branch", "sha")  # 예외 없이 지나갑니다.


# ─── 검수 작업 ─────────────────────────────────────────────────────────────


class FakeRepo:
    """저장소 대역. 파일과 브랜치를 사전으로 들고 있습니다."""

    def __init__(self):
        self.files: dict[str, str] = {}
        self.branches = {"main": "basesha"}
        self.pulls: dict[str, tuple[int, str, str]] = {}
        self.puts: list[str] = []

    def branch_sha(self, branch):
        return self.branches.get(branch)

    def create_branch(self, branch, sha):
        self.branches[branch] = sha

    def file(self, path, ref):
        text = self.files.get(path)
        return (text, "filesha") if text is not None else None

    def put_file(self, path, branch, text, message):
        if self.files.get(path) == text:
            return None
        self.files[path] = text
        self.puts.append(path)
        return f"commit{len(self.puts)}"

    def open_pull_request(self, branch, base, title, body):
        assert base == "main"
        if branch not in self.pulls:
            number = 7 + len(self.pulls)
            self.pulls[branch] = (number, f"https://github.test/pull/{number}", body)
        return self.pulls[branch][0], self.pulls[branch][1]

    def pull_request(self, number):
        return {"number": number, "state": "open", "merged": False, "head_sha": "head"}


@pytest.fixture
def github(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "github_review_enabled": True,
            "github_token": "token",
            "github_repository": "owner/repo",
        }
    )
    fake = FakeRepo()
    monkeypatch.setattr(rt, "get_settings", lambda: settings)
    monkeypatch.setattr(rt, "repository", lambda s, client: fake)
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    return fake


@pytest.fixture
def job(session, user):
    asset = SourceAsset(
        storage_key="source",
        original_filename="s.mp4",
        upload_state="verified",
        duration_seconds=10,
        created_by_id=user.id,
    )
    session.add(asset)
    session.flush()
    row = Job(
        source_asset_id=asset.id,
        target_language="en",
        workflow_config=WorkflowOptions(audio_mode="subtitles", source_language="ko").model_dump(
            mode="json"
        ),
        workflow_data={
            "start": 0,
            "duration": 10,
            "target": "en",
            "cues": [
                {"start": 1, "end": 3, "text": "안녕하세요"},
                {"start": 4, "end": 6, "text": "반갑습니다"},
            ],
            "translated": [c.model_dump() for c in ORIGINAL],
        },
        created_by_id=user.id,
    )
    session.add(row)
    session.commit()
    return row


def make_review(session, job, kind, **extra):
    row = SubtitleReview(
        job_id=job.id,
        kind=kind,
        language="en",
        branch=branch_for(str(job.id)),
        path=subtitle_path(str(job.id), "en"),
        **extra,
    )
    session.add(row)
    session.commit()
    return row


def run(session, row):
    assert rt.run_review(str(row.id))
    session.expire_all()
    return session.get(SubtitleReview, row.id)


def test_export_pushes_subtitles_and_glossary_then_opens_one_pull_request(session, job, github):
    row = run(session, make_review(session, job, "export"))
    assert row.state == "succeeded" and row.pull_number == 7
    assert row.pull_url == "https://github.test/pull/7"
    assert github.puts == [row.path, "glossary/ko-en.tsv"]
    assert "Hello" in github.files[row.path] and "00:00:01,000" in github.files[row.path]
    assert github.branches[row.branch] == "basesha"
    # 다시 내보내도 내용이 같으면 커밋하지 않고 PR도 새로 열지 않습니다.
    again = run(session, make_review(session, job, "export"))
    assert again.state == "succeeded" and again.pull_number == 7
    assert github.puts == [row.path, "glossary/ko-en.tsv"]


def test_export_without_subtitles_fails_with_a_reason(session, job, github):
    job.workflow_data = {"start": 0, "duration": 10, "target": "en"}
    session.commit()
    row = run(session, make_review(session, job, "export"))
    assert row.state == "failed" and "자막" in row.error


def test_import_accepts_text_only_edits(session, job, github):
    github.files[subtitle_path(str(job.id), "en")] = dump_subtitles(
        [Cue(start=1, end=3, text="안녕하세요"), Cue(start=4, end=6, text="반갑습니다")]
    )
    row = run(session, make_review(session, job, "import", pull_number=7))
    assert row.state == "succeeded"
    assert row.result["problems"] == [] and row.result["applicable"] is True
    assert [c["text"] for c in row.result["cues"]] == ["안녕하세요", "반갑습니다"]
    assert row.result["pull_state"]["number"] == 7


def test_import_refuses_to_apply_merged_lines(session, job, github):
    github.files[subtitle_path(str(job.id), "en")] = dump_subtitles(
        [Cue(start=1, end=6, text="Hello, nice to meet you")]
    )
    row = run(session, make_review(session, job, "import"))
    assert row.state == "succeeded" and row.result["applicable"] is False
    assert "개수가 다릅니다" in row.result["problems"][0]


def test_import_reports_a_changed_glossary_without_saving_it(session, job, github):
    github.files[subtitle_path(str(job.id), "en")] = dump_subtitles(list(ORIGINAL))
    github.files["glossary/ko-en.tsv"] = glossary_tsv({"방탄소년단": "BTS"})
    row = run(session, make_review(session, job, "import"))
    assert row.result["glossary"] == {"방탄소년단": "BTS"}
    assert row.result["glossary_changed"] is True
    assert row.result["source_language"] == "ko"


def test_import_without_a_file_fails_with_a_reason(session, job, github):
    row = run(session, make_review(session, job, "import"))
    assert row.state == "failed" and "먼저 내보내세요" in row.error


def test_a_claimed_review_is_not_run_twice(session, job, github):
    row = make_review(session, job, "export")
    assert rt.run_review(str(row.id))["status"] == "succeeded"
    assert rt.run_review(str(row.id))["status"] == "already_claimed"


# ─── API ───────────────────────────────────────────────────────────────────


def test_review_is_refused_until_github_is_configured(client, auth_headers, job):
    assert (
        client.get("/workflow/configuration", headers=auth_headers).json()[
            "github_review_configured"
        ]
        is False
    )
    response = client.post(f"/jobs/{job.id}/review", headers=auth_headers, json={"kind": "export"})
    assert response.status_code == 409 and "R4_GITHUB_REVIEW_ENABLED" in response.json()["detail"]


def test_export_is_queued_and_listed(client, auth_headers, session, job, github):
    assert (
        client.get("/workflow/configuration", headers=auth_headers).json()[
            "github_review_configured"
        ]
        is True
    )
    response = client.post(f"/jobs/{job.id}/review", headers=auth_headers, json={"kind": "export"})
    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "export" and body["state"] == "pending"
    assert body["branch"] == branch_for(str(job.id))
    listed = client.get(f"/jobs/{job.id}/reviews", headers=auth_headers).json()
    assert [r["id"] for r in listed] == [body["id"]]
    # 목록에는 자막을 싣지 않고, 하나만 볼 때 실어 줍니다.
    assert "cues" not in listed[0]
    assert client.get(f"/reviews/{body['id']}", headers=auth_headers).json()["cues"] == []


def test_import_needs_an_export_first(client, auth_headers, session, job, github):
    response = client.post(f"/jobs/{job.id}/review", headers=auth_headers, json={"kind": "import"})
    assert response.status_code == 409 and "먼저 내보내기" in response.json()["detail"]
    run(session, make_review(session, job, "export"))
    accepted = client.post(f"/jobs/{job.id}/review", headers=auth_headers, json={"kind": "import"})
    assert accepted.status_code == 202
    assert accepted.json()["pull_number"] == 7


def test_export_needs_subtitles(client, auth_headers, session, job, github):
    job.workflow_data = {"start": 0, "duration": 10, "target": "en"}
    session.commit()
    response = client.post(f"/jobs/{job.id}/review", headers=auth_headers, json={"kind": "export"})
    assert response.status_code == 409 and "아직 자막이 없습니다" in response.json()["detail"]
