"""용어집. 넣은 표기가 번역문에 그대로 남는지, 남지 않으면 알아채는지."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline.glossary import Glossary, missing, protect, restore
from worker.providers import GoogleTranslator


def make(entries: dict[str, str]) -> Glossary:
    return Glossary(source_language="ko", target_language="en", entries=entries)


def test_term_is_replaced_and_marked_do_not_translate():
    html, terms = protect("녹화4로 편집했습니다.", make({"녹화4": "Recording 4"}))
    assert html == '<span translate="no">Recording 4</span>로 편집했습니다.'
    assert terms == ("Recording 4",)


def test_text_without_any_term_stays_plain():
    """용어가 걸리지 않은 문장은 HTML로 바꾸지 않습니다. 지금까지와 같은 길입니다."""
    text = "오늘은 날씨가 좋습니다. <b>"
    assert protect(text, make({"녹화4": "Recording 4"})) == (text, ())
    assert protect(text, None) == (text, ())


def test_longer_term_wins_over_shorter_one():
    html, terms = protect("녹화4와 녹화", make({"녹화": "recording", "녹화4": "Recording 4"}))
    assert html == '<span translate="no">Recording 4</span>와 <span translate="no">recording</span>'
    assert terms == ("Recording 4", "recording")


def test_angle_brackets_in_source_are_escaped_not_treated_as_tags():
    """원문의 꺾쇠가 표시로 오해받지 않아야 합니다. 되돌리면 원래 글자입니다."""
    html, terms = protect("<b>녹화4</b>", make({"녹화4": "Recording 4"}))
    assert html == '&lt;b&gt;<span translate="no">Recording 4</span>&lt;/b&gt;'
    assert restore(html) == "<b>Recording 4</b>"
    assert terms == ("Recording 4",)


def test_restore_undoes_protect_when_the_translator_changes_nothing():
    """번역기가 표시를 그대로 돌려주면 용어만 바뀐 평문이 나옵니다."""
    html, _ = protect("녹화4와 <b>녹화</b>", make({"녹화4": "Recording 4"}))
    assert restore(html) == "Recording 4와 <b>녹화</b>"


def test_restore_strips_tags_and_entities():
    assert restore('<span translate="no">A &amp; B</span> works') == "A & B works"


def test_missing_counts_each_occurrence():
    assert missing("Recording 4 and Recording 4", ["Recording 4", "Recording 4"]) == []
    assert missing("Recording 4", ["Recording 4", "Recording 4"]) == ["Recording 4"]
    assert missing("録画4", ["Recording 4"]) == ["Recording 4"]


@pytest.mark.parametrize(
    "entries",
    [
        {"": "A"},
        {"녹화4": " "},
        {" 녹화4": "A"},
        {"녹화4": "A\nB"},
        {"녹화4": "x" * 121},
    ],
)
def test_unusable_entries_are_rejected(entries):
    with pytest.raises(ValueError):
        make(entries)


class Recorder:
    """Google 클라이언트 대역. 요청을 모으고 표시를 그대로 돌려줍니다."""

    def __init__(self, reply=None):
        self.requests = []
        self.reply = reply

    def translate_text(self, request, retry, timeout):
        self.requests.append(request)
        replies = self.reply(request) if self.reply else list(request["contents"])
        return SimpleNamespace(translations=[SimpleNamespace(translated_text=t) for t in replies])


def test_only_cues_with_terms_are_sent_as_html():
    """용어가 걸린 문장만 HTML로 갑니다. 나머지는 평문 그대로입니다."""
    client = Recorder()
    GoogleTranslator("p", client=client, allow_paid=True).translate(
        ["날씨가 좋습니다.", "녹화4로 편집했습니다."],
        "en",
        "ko",
        glossary=make({"녹화4": "Recording 4"}),
    )
    kinds = {request["mime_type"]: request["contents"] for request in client.requests}
    assert kinds["text/plain"] == ["날씨가 좋습니다."]
    assert kinds["text/html"] == ['<span translate="no">Recording 4</span>로 편집했습니다.']


def test_translation_keeps_input_order_and_strips_marks():
    client = Recorder(
        reply=lambda request: [
            text.replace("로 편집했습니다.", " was used.").replace(
                "날씨가 좋습니다.", "Nice weather."
            )
            for text in request["contents"]
        ]
    )
    assert GoogleTranslator("p", client=client, allow_paid=True).translate(
        ["날씨가 좋습니다.", "녹화4로 편집했습니다."],
        "en",
        "ko",
        glossary=make({"녹화4": "Recording 4"}),
    ) == ["Nice weather.", "Recording 4 was used."]


def test_without_glossary_nothing_changes():
    """용어집이 없으면 요청이 하나, 평문, 지금까지와 같습니다."""
    client = Recorder(reply=lambda request: ["하나", "둘"])
    translator = GoogleTranslator("p", client=client, allow_paid=True)
    assert translator.translate(["one", "two"], "ko") == ["하나", "둘"]
    assert len(client.requests) == 1
    assert client.requests[0]["mime_type"] == "text/plain"
    assert client.requests[0]["parent"] == "projects/p/locations/global"
    assert "glossary_config" not in client.requests[0]
    assert translator.missing_terms == []


def test_dropped_term_is_recorded_but_translation_is_kept():
    """번역기가 표시를 지워도 번역을 버리지 않습니다. 대신 세어 둡니다."""
    client = Recorder(reply=lambda request: ["편집했습니다"])
    translator = GoogleTranslator("p", client=client, allow_paid=True)
    assert translator.translate(
        ["녹화4로 편집했습니다."], "en", "ko", glossary=make({"녹화4": "Recording 4"})
    ) == ["편집했습니다"]
    assert translator.missing_terms == ["Recording 4"]


def test_google_own_glossary_uses_its_region_and_glossary_translations():
    resource = "projects/p/locations/us-central1/glossaries/ko-en"

    class Client:
        def translate_text(self, request, retry, timeout):
            self.request = request
            return SimpleNamespace(
                translations=[SimpleNamespace(translated_text="plain")],
                glossary_translations=[SimpleNamespace(translated_text="Recording 4 was used.")],
            )

    client = Client()
    translator = GoogleTranslator("p", client=client, allow_paid=True, glossary_resource=resource)
    # 우리 용어집을 같이 넘겨도 Google 쪽이 처리하므로 표시를 넣지 않습니다.
    assert translator.translate(
        ["녹화4로 편집했습니다."], "en", "ko", glossary=make({"녹화4": "Recording 4"})
    ) == ["Recording 4 was used."]
    assert client.request["parent"] == "projects/p/locations/us-central1"
    assert client.request["mime_type"] == "text/plain"
    assert client.request["glossary_config"] == {"glossary": resource}


@pytest.mark.parametrize(
    "resource",
    ["ko-en", "projects/p/locations/global/glossaries/ko-en", "projects/p/glossaries/ko-en"],
)
def test_unusable_glossary_resource_is_rejected(resource):
    with pytest.raises(ValueError):
        GoogleTranslator("p", glossary_resource=resource)
