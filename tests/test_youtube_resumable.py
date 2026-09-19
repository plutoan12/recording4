"""업로드 어댑터를 실제 Google SDK로 가짜 YouTube 서버에 붙여 봅니다.

지금까지 업로드 경로는 SDK를 통째로 대역으로 바꿔서만 검증했습니다. 정작
위험한 곳은 SDK와 주고받는 재개 규약입니다. 중단된 업로드를 이어 올릴 때
세션을 새로 만들지 않는지, 저장한 오프셋을 믿지 않고 서버에 다시 묻는지는
실행해 봐야 알 수 있습니다. 문서에도 "SDK 버전 변경 시 재개 계약 테스트를
다시 실행"하라고 적혀 있는데, 그 테스트가 없었습니다.

계정도 네트워크도 쓰지 않습니다. 로컬에 재개 업로드 규약만 흉내 내는 서버를
띄우고 SDK가 실제로 그 규약대로 말하는지 봅니다.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from worker.youtube import UploadNeedsReview, upload_approved

pytest.importorskip("googleapiclient", reason="providers extra가 있어야 SDK를 실행합니다.")

from googleapiclient.discovery import build_from_document  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402
from googleapiclient.http import build_http  # noqa: E402

VIDEO_ID = "video-from-stub"


def discovery(root: str) -> dict:
    """videos.insert(재개 업로드)와 videos.list만 담은 최소 발견 문서."""
    return {
        "kind": "discovery#restDescription",
        "discoveryVersion": "v1",
        "id": "youtube:v3",
        "name": "youtube",
        "version": "v3",
        "rootUrl": root,
        "servicePath": "youtube/v3/",
        "baseUrl": root + "youtube/v3/",
        "protocol": "rest",
        "schemas": {"Video": {"id": "Video", "type": "object", "properties": {}}},
        "resources": {
            "videos": {
                "methods": {
                    "insert": {
                        "id": "youtube.videos.insert",
                        "path": "videos",
                        "httpMethod": "POST",
                        "parameters": {
                            "part": {"type": "string", "location": "query", "required": True}
                        },
                        "parameterOrder": ["part"],
                        "request": {"$ref": "Video"},
                        "response": {"$ref": "Video"},
                        "supportsMediaUpload": True,
                        "mediaUpload": {
                            "accept": ["video/*"],
                            "maxSize": "128GB",
                            "protocols": {
                                "simple": {"multipart": True, "path": "/upload/youtube/v3/videos"},
                                "resumable": {
                                    "multipart": True,
                                    "path": "/resumable/upload/youtube/v3/videos",
                                },
                            },
                        },
                    }
                }
            }
        },
    }


class Stub:
    """재개 업로드 규약만 흉내 냅니다. 받은 바이트 수와 호출 수를 셉니다."""

    def __init__(self) -> None:
        self.sessions = 0  # 업로드 세션 생성 횟수. 재개할 때 늘면 중복 업로드입니다.
        self.received = 0  # 서버가 실제로 받은 바이트. 재개 지점의 근거입니다.
        self.fail_next_chunk = False
        self.body = bytearray()


def serve(stub: Stub) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: ANN002 - 테스트 출력을 더럽히지 않습니다.
            pass

        def _send(self, code: int, headers: dict | None = None, body: bytes = b"") -> None:
            self.send_response(code)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 규약
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            stub.sessions += 1
            host = self.headers.get("Host")
            self._send(200, {"Location": f"http://{host}/session/{stub.sessions}"})

        def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 규약
            length = int(self.headers.get("Content-Length") or 0)
            chunk = self.rfile.read(length)
            span = self.headers.get("Content-Range", "")
            total = int(span.rsplit("/", 1)[-1]) if "/" in span else 0

            # "bytes */전체"는 어디까지 받았는지 묻는 것입니다. 몸체가 없습니다.
            if span.startswith("bytes */"):
                if stub.received == 0:
                    self._send(308)
                else:
                    self._send(308, {"Range": f"bytes=0-{stub.received - 1}"})
                return

            if stub.fail_next_chunk:
                stub.fail_next_chunk = False
                self._send(500, body=b'{"error": {"message": "stub failure"}}')
                return

            stub.body += chunk
            stub.received = len(stub.body)
            if stub.received < total:
                self._send(308, {"Range": f"bytes=0-{stub.received - 1}"})
                return
            self._send(
                200, {"Content-Type": "application/json"}, json.dumps({"id": VIDEO_ID}).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


@pytest.fixture
def youtube():
    stub = Stub()
    server, root = serve(stub)
    # 운영은 build()가 만드는 http를 씁니다. 그 http는 308을 리다이렉트 목록에서
    # 빼 둡니다. 재개 업로드의 "아직 안 끝났다"가 308이라 그렇습니다. 맨
    # httplib2.Http()를 넘기면 여기서 리다이렉트로 처리돼 실패합니다.
    service = build_from_document(discovery(root), http=build_http())
    try:
        yield service, stub
    finally:
        server.shutdown()


def media(tmp_path: Path, size: int = 40_000) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(bytes(range(256)) * (size // 256))
    return path


def test_upload_saves_the_session_and_returns_the_video_id(youtube, tmp_path) -> None:
    service, stub = youtube
    saved: list[dict] = []
    checkpoint: dict = {}
    video = upload_approved(
        service,
        media(tmp_path),
        approval_id="approval-1",
        title="제목",
        description="설명",
        checkpoint=checkpoint,
        save=saved.append,
        made_for_kids=False,
        allow_upload=True,
    )
    assert video == VIDEO_ID
    assert stub.sessions == 1
    assert stub.received == media(tmp_path).stat().st_size
    # 세션 주소와 영상 번호가 체크포인트에 남아야 재개와 중복 방지가 됩니다.
    assert saved[-1]["video_id"] == VIDEO_ID
    assert saved[-1]["session_uri"].startswith("http://127.0.0.1")
    assert saved[0]["started"] is True


def test_resume_reuses_the_session_instead_of_uploading_again(youtube, tmp_path) -> None:
    """중단된 업로드는 같은 세션으로 이어야 합니다. 새 세션은 영상을 하나 더 만듭니다."""
    service, stub = youtube
    path = media(tmp_path)
    checkpoint: dict = {}
    stub.fail_next_chunk = True

    def save(state: dict) -> None:
        checkpoint.clear()
        checkpoint.update(state)

    with pytest.raises(HttpError):
        upload_approved(
            service,
            path,
            approval_id="approval-1",
            title="제목",
            description="설명",
            checkpoint=checkpoint,
            save=save,
            made_for_kids=False,
            allow_upload=True,
        )
    # 실패해도 세션 주소는 남아 있어야 합니다. 없으면 이어 올릴 수 없습니다.
    assert checkpoint["session_uri"]
    assert stub.sessions == 1
    assert stub.received == 0

    video = upload_approved(
        service,
        path,
        approval_id="approval-1",
        title="제목",
        description="설명",
        checkpoint=dict(checkpoint),
        save=save,
        made_for_kids=False,
        allow_upload=True,
    )
    assert video == VIDEO_ID
    # 세션이 하나뿐이어야 합니다. 늘었다면 같은 승인본을 두 번 올린 것입니다.
    assert stub.sessions == 1
    assert stub.received == path.stat().st_size


def test_finished_upload_does_not_touch_the_network_again(youtube, tmp_path) -> None:
    """영상 번호가 이미 있으면 올리지 않습니다. 재시도가 중복 업로드가 되면 안 됩니다."""
    service, stub = youtube
    video = upload_approved(
        service,
        media(tmp_path),
        approval_id="approval-1",
        title="제목",
        description="설명",
        checkpoint={"approval_id": "approval-1", "video_id": "already-there"},
        save=lambda state: None,
        made_for_kids=False,
        allow_upload=True,
    )
    assert video == "already-there"
    assert stub.sessions == 0


def test_a_different_approval_stops_before_the_network(youtube, tmp_path) -> None:
    """다른 승인본으로 이어 올리면 안 됩니다. 검수한 것과 다른 영상이 올라갑니다."""
    service, stub = youtube
    with pytest.raises(UploadNeedsReview):
        upload_approved(
            service,
            media(tmp_path),
            approval_id="approval-2",
            title="제목",
            description="설명",
            checkpoint={"approval_id": "approval-1", "session_uri": "http://old/session"},
            save=lambda state: None,
            made_for_kids=False,
            allow_upload=True,
        )
    assert stub.sessions == 0
