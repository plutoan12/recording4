import json
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


def test_deepl_request_contract_and_language_codes():
    def handler(request):
        assert request.headers["Authorization"] == "DeepL-Auth-Key k:fx"
        assert request.url.host == "api-free.deepl.com"
        body = json.loads(request.content)
        assert body["target_lang"] == "ZH-HANS" and body["source_lang"] == "KO"
        assert body["split_sentences"] == "0"
        return httpx.Response(200, json={"translations": [{"text": "录音中"}]})

    from worker.providers import DeepLTranslator

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = DeepLTranslator("k:fx", client=client, allow_paid=True).translate(
            ["녹화 중입니다."], "zh", "ko"
        )
    assert out == ["录像中"]
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("network"))) as client:
        with pytest.raises(ProviderError):
            DeepLTranslator("k", client=client).translate(["x"], "en")


def test_huggingface_translator_needs_a_source_and_maps_codes():
    from worker.providers import HuggingFaceTranslator

    seen = {}

    def fake_pipeline(texts, **kwargs):
        seen.update(kwargs)
        return [{"translation_text": t.upper()} for t in texts]

    adapter = HuggingFaceTranslator(pipeline=fake_pipeline)
    assert adapter.translate(["a"], "en", "ko") == ["A"]
    assert seen["src_lang"] == "kor_Hang" and seen["tgt_lang"] == "eng_Latn"
    with pytest.raises(ValueError):
        adapter.translate(["a"], "en", None)


class FakeMessages:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(answer))],
        )


def test_claude_translator_retries_once_on_a_bad_line_count():
    from pipeline.translation_jobs import build_job
    from worker.providers import ClaudeTranslator

    job = build_job(["하나", "둘"], source="ko", target="en", entries={})
    messages = FakeMessages(
        [
            {"lines": [{"id": 0, "text": "one"}]},
            {"lines": [{"id": 0, "text": "one"}, {"id": 1, "text": "two"}]},
        ]
    )
    adapter = ClaudeTranslator(client=SimpleNamespace(messages=messages), allow_paid=True)
    assert adapter.translate(job) == ["one", "two"]
    assert len(messages.calls) == 2
    assert "rejected" in messages.calls[1]["messages"][0]["content"]


def test_claude_translator_gives_up_after_the_retry():
    from pipeline.translation_jobs import build_job
    from worker.providers import ClaudeTranslator

    job = build_job(["하나"], source="ko", target="en", entries={})
    messages = FakeMessages([{"lines": []}, {"lines": [{"id": 7, "text": "x"}]}])
    with pytest.raises(ProviderError):
        ClaudeTranslator(client=SimpleNamespace(messages=messages), allow_paid=True).translate(job)


def test_claude_refine_sends_drafts_and_paid_gate_holds():
    from pipeline.translation_jobs import build_job
    from worker.providers import ClaudeTranslator

    job = build_job(["안녕"], source="ko", target="en", entries={})
    with pytest.raises(ProviderError):
        ClaudeTranslator(client=SimpleNamespace()).translate(job, drafts=["Hi"])
    messages = FakeMessages([{"lines": [{"id": 0, "text": "Hello"}]}])
    out = ClaudeTranslator(client=SimpleNamespace(messages=messages), allow_paid=True).translate(
        job, drafts=["Hi"]
    )
    assert out == ["Hello"]
    assert "polish" in messages.calls[0]["system"].lower()
    assert "#0\t안녕\tHi" in messages.calls[0]["messages"][0]["content"]
