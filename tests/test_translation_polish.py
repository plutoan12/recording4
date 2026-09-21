"""번역 단계의 문맥 배치와 LLM 재번역. 실제 공급자는 부르지 않습니다."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from pipeline.workflow import WorkflowOptions
from worker import workflow_tasks as wf
from worker.providers import ClaudeTranslator, ProviderError

CUES = [
    {"start": 0.0, "end": 1.0, "text": "그래서 저는"},
    {"start": 1.0, "end": 3.0, "text": "어제 그 자료를"},
    {"start": 3.0, "end": 4.0, "text": "다시 만들었습니다."},
]


def translator(monkeypatch, reply):
    """GoogleTranslator 대역. 받은 입력을 모아 둡니다."""
    seen = []

    class Translator:
        missing_terms: dict = {}

        def __init__(self, *args, **kwargs):
            pass

        def translate(self, texts, target, source, *, glossary=None):
            seen.append(list(texts))
            return reply(list(texts))

    monkeypatch.setattr(wf, "GoogleTranslator", Translator)
    return seen


def settings(**extra):
    return wf.get_settings().model_copy(
        update={"google_cloud_project": "test", "paid_processing_enabled": True, **extra}
    )


def test_context_off_sends_each_cue_by_itself(monkeypatch):
    """기본값입니다. 지금까지와 똑같이 한 자막씩 보냅니다."""
    seen = translator(monkeypatch, lambda texts: [f"<{text}>" for text in texts])
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko")
    texts, grouped, _ = wf.run_translation(CUES, {"target": "en"}, options, settings(), None)
    assert seen == [["그래서 저는", "어제 그 자료를", "다시 만들었습니다."]]
    assert texts == ["<그래서 저는>", "<어제 그 자료를>", "<다시 만들었습니다.>"]
    assert grouped == []


def test_context_on_merges_the_sentence_and_splits_the_translation(monkeypatch):
    sentence = "So I rebuilt that material again yesterday."
    seen = translator(monkeypatch, lambda texts: [sentence])
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_context=True)
    texts, grouped, _ = wf.run_translation(CUES, {"target": "en"}, options, settings(), None)
    # 한 문장으로 합쳐 한 번만 보냅니다.
    assert seen == [["그래서 저는 어제 그 자료를 다시 만들었습니다."]]
    assert " ".join(texts) == sentence
    assert grouped == [0, 1, 2]
    # 가운데 자막이 2초로 가장 길었으므로 가장 넓은 몫을 받습니다.
    assert len(texts[1]) > len(texts[0])


def test_a_translation_too_short_to_split_falls_back_to_one_call_per_cue(monkeypatch):
    seen = translator(
        monkeypatch,
        lambda texts: ["Hi."] if len(texts) == 1 else [f"<{text}>" for text in texts],
    )
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_context=True)
    texts, grouped, _ = wf.run_translation(CUES, {"target": "en"}, options, settings(), None)
    assert seen == [
        ["그래서 저는 어제 그 자료를 다시 만들었습니다."],
        ["그래서 저는", "어제 그 자료를", "다시 만들었습니다."],
    ]
    assert texts == ["<그래서 저는>", "<어제 그 자료를>", "<다시 만들었습니다.>"]
    assert grouped == []


def test_dubbing_refuses_context_batching():
    """더빙은 자막 조각이 곧 그 구간의 발화라 문장을 다시 나누면 어긋납니다."""
    with pytest.raises(ValueError):
        WorkflowOptions(audio_mode="dub", voice_id="v", translate_context=True)


def claude(monkeypatch, handler):
    seen = {}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers, json, timeout):
            seen["url"], seen["headers"], seen["body"] = url, headers, json
            return handler(json)

    monkeypatch.setattr(wf.httpx, "Client", Client)
    return seen


def reply(texts):
    import json as _json

    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": _json.dumps(texts, ensure_ascii=False)}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    )


def test_polish_is_off_unless_the_job_asks_for_it(monkeypatch):
    monkeypatch.setattr(wf.httpx, "Client", lambda *a, **k: pytest.fail("불러서는 안 됩니다"))
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko")
    texts, notes = wf.polish(
        CUES, ["a", "b", "c"], [], {}, {"target": "en"}, options, settings(), None
    )
    assert (texts, notes) == (["a", "b", "c"], {})


def test_polish_rewrites_only_the_cues_that_look_wrong(monkeypatch):
    seen = claude(monkeypatch, lambda body: reply(["So I rebuilt it."]))
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_polish=True)
    drafts = ["그래서 저는", "I rebuilt that material.", "I rebuilt it again."]
    texts, notes = wf.polish(
        CUES,
        list(drafts),
        [],
        {},
        {"target": "en"},
        options,
        settings(anthropic_api_key="key", llm_translate_model="test-model"),
        None,
    )
    # 원문이 그대로 남은 첫 자막만 다시 씁니다.
    assert texts == ["So I rebuilt it.", drafts[1], drafts[2]]
    assert notes == {"llm_retranslated": 1}
    assert seen["headers"]["Authorization"] == "Bearer key"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["model"] == "test-model"
    # 앞뒤 자막을 문맥으로 같이 넘깁니다.
    assert "어제 그 자료를" in seen["body"]["messages"][0]["content"]


def test_polish_keeps_the_machine_translation_when_the_llm_fails(monkeypatch):
    claude(monkeypatch, lambda body: httpx.Response(500))
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_polish=True)
    drafts = ["그래서 저는", "I rebuilt that material.", "I rebuilt it again."]
    texts, notes = wf.polish(
        CUES,
        list(drafts),
        [],
        {},
        {"target": "en"},
        options,
        settings(anthropic_api_key="key", llm_translate_model="test-model"),
        None,
    )
    assert texts == drafts
    assert "500" in notes["llm_translate_error"]


def test_polish_without_a_model_name_says_so_instead_of_calling(monkeypatch):
    monkeypatch.setattr(wf.httpx, "Client", lambda *a, **k: pytest.fail("불러서는 안 됩니다"))
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_polish=True)
    _, notes = wf.polish(CUES, ["a", "b", "c"], [], {}, {"target": "en"}, options, settings(), None)
    assert "모델 이름" in notes["llm_translate_error"]


def test_estimate_adds_a_capped_upper_bound_for_the_llm(monkeypatch):
    rates = {
        "translate_usd_per_1k_chars": Decimal("0.02"),
        "llm_translate_usd_per_1k_chars": Decimal("0.02"),
        "llm_translate_model": "test-model",
    }
    data = {"cues": CUES, "target": "en"}
    plain = WorkflowOptions(audio_mode="subtitles", source_language="ko")
    polished = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_polish=True)
    assert wf.paid_estimate("translate:0", data, plain, settings(**rates)) == Decimal("0.0005")
    # 가장 긴 자막 하나(30%의 상한) × 원문·기계 번역·문맥·출력 네 몫 + 지시문 몫.
    assert wf.paid_estimate("translate:0", data, polished, settings(**rates)) == Decimal("0.0133")


def test_estimate_blocks_when_the_llm_rate_is_not_set():
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko", translate_polish=True)
    with pytest.raises(wf.Blocked):
        wf.paid_estimate(
            "translate:0",
            {"cues": CUES, "target": "en"},
            options,
            settings(translate_usd_per_1k_chars=Decimal("0.02"), llm_translate_model="test-model"),
        )


@pytest.mark.parametrize(
    "body",
    [
        {"content": [{"type": "text", "text": "설명만 있고 배열이 없습니다"}]},
        {"content": [{"type": "text", "text": '["하나", "둘"]'}]},
        {"content": [{"type": "text", "text": '["  "]'}]},
        {"content": [{"type": "text", "text": '["하나"]'}], "stop_reason": "max_tokens"},
    ],
)
def test_an_unusable_llm_response_is_refused(body):
    class Client:
        def post(self, *args, **kwargs):
            return httpx.Response(200, json=body)

    with pytest.raises(ProviderError):
        ClaudeTranslator("key", client=Client(), model="m", allow_paid=True).retranslate(
            [{"source": "가", "draft": "a", "context": "가"}], "en", "ko"
        )


def test_the_llm_is_not_called_without_explicit_permission():
    with pytest.raises(ProviderError):
        ClaudeTranslator("key", client=SimpleNamespace(), model="m").retranslate(
            [{"source": "가", "draft": "a", "context": "가"}], "en", "ko"
        )
