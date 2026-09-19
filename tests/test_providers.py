from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from worker.providers import ElevenLabsSpeech, GoogleTranslator, ProviderError, SyncLipsync
from worker.youtube import UploadNeedsReview, upload_approved


def test_paid_disabled_before_network(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: pytest.fail("unexpected network"))
    ) as client:
        with pytest.raises(ProviderError):
            ElevenLabsSpeech("key", client=client).synthesize("hello", "voice", tmp_path / "a.mp3")
        with pytest.raises(ProviderError):
            SyncLipsync("key", client=client).submit(
                "https://example.com/v", "https://example.com/a"
            )
    with pytest.raises(ProviderError):
        GoogleTranslator("project").translate(["hello"], "ko")


def test_tts_request_contract(tmp_path):
    def handler(request):
        assert request.headers["xi-api-key"] == "key"
        assert request.url.host == "api.elevenlabs.io"
        return httpx.Response(200, content=b"mp3", headers={"request-id": "r1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ElevenLabsSpeech("key", client=client, allow_paid=True).synthesize(
            "hello", "voice", tmp_path / "a.mp3"
        )
    assert result == "r1" and (tmp_path / "a.mp3").read_bytes() == b"mp3"


def test_translation_preserves_batch_order():
    class Client:
        def translate_text(self, request, retry, timeout):
            assert request["contents"] == ["one", "two"] and retry is None
            return SimpleNamespace(
                translations=[SimpleNamespace(translated_text=t) for t in ["하나", "둘"]]
            )

    assert GoogleTranslator("p", client=Client(), allow_paid=True).translate(
        ["one", "two"], "ko"
    ) == ["하나", "둘"]


def test_lipsync_submit_then_poll():
    requests = []

    def handler(request):
        requests.append(request.method)
        return httpx.Response(
            201 if request.method == "POST" else 200, json={"id": "job-1", "status": "PENDING"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = SyncLipsync("key", client=client, allow_paid=True)
        remote_id = adapter.submit("https://example.com/v", "https://example.com/a")
        assert adapter.status(remote_id)["status"] == "PENDING"
    assert requests == ["POST", "GET"]


def test_youtube_ambiguous_upload_is_not_recreated():
    with pytest.raises(UploadNeedsReview):
        upload_approved(
            None,
            Path("video.mp4"),
            approval_id="a",
            title="t",
            description="",
            checkpoint={"started": True},
            save=lambda s: None,
            made_for_kids=False,
            allow_upload=True,
        )


@pytest.mark.parametrize(
    "source,text,expected",
    [
        ("ko", "녹화가 멈췄습니다.", "录像停止了。"),
        ("ja", "録画が止まった。", "录像停止了。"),
        ("ko", "녹음이 멈췄습니다.", "录音停止了。"),
        ("ko", "녹화와 녹음을 비교합니다.", "录音停止了。"),
        ("en", "The recording stopped.", "录音停止了。"),
        (None, "녹화가 멈췄습니다.", "录音停止了。"),
    ],
)
def test_explicit_video_terms_do_not_rewrite_audio_or_ambiguous_cues(source, text, expected):
    from worker.providers import video_terms

    assert video_terms(text, "录音停止了。", source, "zh") == expected


def test_google_translation_applies_explicit_video_terminology():
    class Client:
        def translate_text(self, request, retry, timeout):
            return SimpleNamespace(translations=[SimpleNamespace(translated_text="录音仍在继续。")])

    translated = GoogleTranslator("p", client=Client(), allow_paid=True).translate(
        ["녹화 중입니다."], "zh", "ko"
    )
    assert translated == ["录像仍在继续。"]
