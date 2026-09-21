"""용어집 API와, 번역 단계가 그 용어집을 실제로 고르는지."""

from __future__ import annotations

import pytest

from adminapi.services.glossary import active_glossary


def save(client, headers, entries):
    """용어집 저장. 줄이 길어지지 않게 묶어 둡니다."""
    response = client.put("/glossaries/ko/en", headers=headers, json={"entries": entries})
    assert response.status_code == 200, response.text
    return response.json()


def test_auth_required(client):
    assert client.get("/glossaries").status_code == 401
    assert client.put("/glossaries/ko/en", json={"entries": {}}).status_code == 401


def test_save_read_and_list(client, auth_headers):
    saved = client.put(
        "/glossaries/ko/en", headers=auth_headers, json={"entries": {"녹화4": "Recording 4"}}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "source_language": "ko",
        "target_language": "en",
        "version": 1,
        "term_count": 1,
        "entries": {"녹화4": "Recording 4"},
    }
    assert client.get("/glossaries/ko/en", headers=auth_headers).json()["entries"] == {
        "녹화4": "Recording 4"
    }
    assert client.get("/glossaries", headers=auth_headers).json() == [
        {"source_language": "ko", "target_language": "en", "version": 1, "term_count": 1}
    ]


def test_saving_again_replaces_terms_and_raises_version(client, auth_headers):
    client.put("/glossaries/ko/en", headers=auth_headers, json={"entries": {"가": "A"}})
    again = client.put("/glossaries/ko/en", headers=auth_headers, json={"entries": {"나": "B"}})
    assert again.json()["version"] == 2
    assert again.json()["entries"] == {"나": "B"}


def test_missing_glossary_is_404(client, auth_headers):
    assert client.get("/glossaries/ko/ja", headers=auth_headers).status_code == 404
    assert client.delete("/glossaries/ko/ja", headers=auth_headers).status_code == 404


def test_delete(client, auth_headers):
    client.put("/glossaries/ko/en", headers=auth_headers, json={"entries": {"가": "A"}})
    assert client.delete("/glossaries/ko/en", headers=auth_headers).status_code == 204
    assert client.get("/glossaries/ko/en", headers=auth_headers).status_code == 404


@pytest.mark.parametrize(
    "entries", [{"": "A"}, {" 가": "A"}, {"가": "A\nB"}, {"가": "x" * 121}, {"가": " "}]
)
def test_unusable_terms_are_refused(client, auth_headers, entries):
    response = client.put("/glossaries/ko/en", headers=auth_headers, json={"entries": entries})
    assert response.status_code == 422, response.text


def test_bad_language_code_is_refused(client, auth_headers):
    assert (
        client.put("/glossaries/korean/en", headers=auth_headers, json={"entries": {}}).status_code
        == 422
    )


def test_translation_picks_the_glossary_for_that_direction(client, auth_headers, session):
    client.put(
        "/glossaries/ko/en", headers=auth_headers, json={"entries": {"녹화4": "Recording 4"}}
    )
    client.put("/glossaries/ko/ja", headers=auth_headers, json={"entries": {"녹화4": "録画4"}})
    assert active_glossary(session, "ko", "en").entries == {"녹화4": "Recording 4"}
    assert active_glossary(session, "ko", "ja").entries == {"녹화4": "録画4"}
    assert active_glossary(session, "ja", "en") is None


def test_auto_detected_source_language_uses_no_glossary(client, auth_headers, session):
    """원문 언어를 모르면 어느 방향의 용어집인지 알 수 없습니다. 쓰지 않습니다."""
    client.put(
        "/glossaries/ko/en", headers=auth_headers, json={"entries": {"녹화4": "Recording 4"}}
    )
    assert active_glossary(session, None, "en") is None


def test_empty_glossary_is_treated_as_none(client, auth_headers, session):
    client.put("/glossaries/ko/en", headers=auth_headers, json={"entries": {}})
    assert active_glossary(session, "ko", "en") is None


def test_translate_step_hands_the_glossary_to_the_provider(
    client, auth_headers, monkeypatch, tmp_path
):
    """워커의 번역 단계가 DB의 용어집을 실제로 들고 갑니다."""
    from pipeline.workflow import WorkflowOptions
    from worker import workflow_tasks as wf

    client.put(
        "/glossaries/ko/en", headers=auth_headers, json={"entries": {"녹화4": "Recording 4"}}
    )
    settings = wf.get_settings().model_copy(update={"google_cloud_project": "test"})
    monkeypatch.setattr(wf, "get_settings", lambda: settings)
    seen = {}

    class Translator:
        def __init__(self, *args, **kwargs):
            seen["resource"] = kwargs.get("glossary_resource")

        def translate(self, texts, target, source, *, glossary=None):
            seen["glossary"] = glossary
            return ["Recording 4 was used."]

    monkeypatch.setattr(wf, "GoogleTranslator", Translator)
    wf.execute_step(
        "translate:0",
        WorkflowOptions(audio_mode="subtitles", source_language="ko"),
        {"cues": [{"start": 0, "end": 1, "text": "녹화4로 편집했습니다."}], "target": "en"},
        None,
        tmp_path,
        "stage",
        None,
        lambda x: None,
    )
    assert seen["resource"] is None
    assert seen["glossary"].entries == {"녹화4": "Recording 4"}
    assert seen["glossary"].version == 1


def test_estimate_counts_the_marked_characters_not_the_raw_ones(client, auth_headers, monkeypatch):
    """Google은 표시 글자도 세어 청구합니다. 예산도 보낼 글자 그대로 잡습니다."""
    from decimal import Decimal

    from pipeline.workflow import WorkflowOptions
    from worker import workflow_tasks as wf

    options = WorkflowOptions(audio_mode="subtitles", source_language="ko")
    data = {"cues": [{"start": 0, "end": 1, "text": "녹화4로 편집했습니다."}], "target": "en"}
    settings = wf.get_settings().model_copy(
        update={
            "google_cloud_project": "test",
            "paid_processing_enabled": True,
            "translate_usd_per_1k_chars": Decimal("0.02"),
        }
    )
    plain = wf.paid_estimate("translate:0", data, options, settings)
    save(client, auth_headers, {"녹화4": "Recording 4"})
    with wf.get_session_factory()() as session:
        marked = wf.paid_estimate("translate:0", data, options, settings, session)
    # 원문 12자 → 표시가 붙어 48자. 요금도 네 배입니다.
    assert (plain, marked) == (Decimal("0.0003"), Decimal("0.0010"))


def test_google_own_glossary_leaves_the_estimate_alone(client, auth_headers, monkeypatch):
    """Google 자체 용어집을 쓰면 우리 표시를 넣지 않으므로 글자도 늘지 않습니다."""
    from decimal import Decimal

    from pipeline.workflow import WorkflowOptions
    from worker import workflow_tasks as wf

    save(client, auth_headers, {"녹화4": "Recording 4"})
    settings = wf.get_settings().model_copy(
        update={
            "google_cloud_project": "test",
            "paid_processing_enabled": True,
            "translate_usd_per_1k_chars": Decimal("0.02"),
            "google_translate_glossary": "projects/p/locations/us-central1/glossaries/ko-en",
        }
    )
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko")
    data = {"cues": [{"start": 0, "end": 1, "text": "녹화4로 편집했습니다."}], "target": "en"}
    with wf.get_session_factory()() as session:
        estimate = wf.paid_estimate("translate:0", data, options, settings, session)
    assert estimate == Decimal("0.0003")
