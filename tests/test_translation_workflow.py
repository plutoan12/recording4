"""번역 단계 통합: 기억(캐시) · 용어집 · 공급자 전환 · 보정 · QA · 방향 검사 · 용어집 API.

유료 공급자는 전부 대역입니다. 여기서 보는 것은 번역 품질이 아니라 **불필요한
호출이 나가지 않는지**와 **용어가 지켜지는지**입니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from adminapi.config import get_settings
from adminapi.models import SourceAsset, TranslationMemory
from pipeline.workflow import WorkflowOptions
from worker import workflow_tasks as wf
from worker.providers import ProviderError


@pytest.fixture
def paid(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "paid_processing_enabled": True,
            "google_cloud_project": "test-only",
            "translate_usd_per_1k_chars": Decimal("0.02"),
        }
    )
    monkeypatch.setattr(wf, "get_settings", lambda: settings)
    return settings


class Recorder:
    """공급자 대역. 받은 원문을 기록하고 대문자로 돌려줍니다."""

    calls: list[list[str]] = []

    def __init__(self, *args, **kwargs):
        pass

    def translate(self, texts, target, source=None):
        Recorder.calls.append(list(texts))
        return [t.upper() for t in texts]


@pytest.fixture(autouse=True)
def _reset():
    Recorder.calls = []


def step(settings, texts, target="en", source="ko", **kw):
    return wf.translate_texts(settings, texts, target, source, **kw)


def test_identical_lines_are_sent_once_and_remembered(paid, monkeypatch, session):
    monkeypatch.setattr(wf, "GoogleTranslator", Recorder)
    assert step(paid, ["안녕", "안녕", "잘 가"]) == [
        "안녕".upper(),
        "안녕".upper(),
        "잘 가".upper(),
    ]
    assert Recorder.calls == [["안녕", "잘 가"]]
    # 두 번째 묶음은 기억에서만 옵니다. 공급자는 불리지 않습니다.
    assert step(paid, ["잘 가", "안녕"]) == ["잘 가".upper(), "안녕".upper()]
    assert Recorder.calls == [["안녕", "잘 가"]]
    rows = list(session.scalars(select(TranslationMemory)))
    assert {r.source_text for r in rows} == {"안녕", "잘 가"}
    assert all(r.provider == "google" and r.target_language == "en" for r in rows)


def test_memory_is_keyed_by_direction_and_provider(paid, monkeypatch):
    monkeypatch.setattr(wf, "GoogleTranslator", Recorder)
    step(paid, ["안녕"], target="en")
    step(paid, ["안녕"], target="ja")
    assert Recorder.calls == [["안녕"], ["안녕"]]
    other = paid.model_copy(update={"translation_provider": "deepl", "deepl_api_key": "k"})
    monkeypatch.setattr(wf, "DeepLTranslator", Recorder)
    step(other, ["안녕"], target="en")
    assert len(Recorder.calls) == 3


def test_glossary_terms_are_protected_and_restored(paid, monkeypatch, client, auth_headers):
    response = client.put(
        "/workflow/glossary",
        headers=auth_headers,
        json={"source_language": "ko", "target_language": "*", "entries": {"방탄소년단": "BTS"}},
    )
    assert response.status_code == 200 and response.json()["version"] == 1
    seen = []

    class Translator(Recorder):
        def translate(self, texts, target, source=None):
            seen.extend(texts)
            return [t.replace("의 노래", "'s song") for t in texts]

    monkeypatch.setattr(wf, "GoogleTranslator", Translator)
    assert step(paid, ["방탄소년단의 노래 2개"]) == ["BTS's song 2개"]
    # 공급자는 용어도 숫자도 보지 못했습니다.
    assert "방탄소년단" not in seen[0] and "2개" not in seen[0]


def test_a_new_glossary_version_invalidates_the_memory(paid, monkeypatch, client, auth_headers):
    monkeypatch.setattr(wf, "GoogleTranslator", Recorder)
    step(paid, ["안녕"])
    client.put(
        "/workflow/glossary",
        headers=auth_headers,
        json={"source_language": "*", "target_language": "en", "entries": {"안녕": "Hi"}},
    )
    assert client.get("/workflow/glossary?target=en", headers=auth_headers).json() == {
        "source_language": "*",
        "target_language": "en",
        "version": 1,
        "entries": {"안녕": "Hi"},
    }
    assert step(paid, ["안녕"]) == ["Hi"]
    assert len(Recorder.calls) == 2


def test_glossary_api_rejects_unknown_languages(client, auth_headers):
    response = client.put(
        "/workflow/glossary",
        headers=auth_headers,
        json={"source_language": "fr", "target_language": "en", "entries": {"a": "b"}},
    )
    assert response.status_code == 422


def test_unsupported_direction_is_blocked_before_any_call(paid, monkeypatch):
    monkeypatch.setattr(wf, "GoogleTranslator", lambda *a, **k: pytest.fail("called"))
    with pytest.raises(wf.Blocked, match="방향"):
        step(paid, ["hola"], target="ko", source="es")


def test_local_model_costs_nothing_and_needs_no_budget(paid, monkeypatch):
    local = paid.model_copy(
        update={"translation_provider": "huggingface", "paid_processing_enabled": False}
    )
    monkeypatch.setattr(wf, "HuggingFaceTranslator", Recorder)
    data = {"cues": [{"start": 0, "end": 1, "text": "안녕"}], "target": "en"}
    assert (
        wf.paid_estimate("translate:0", data, WorkflowOptions(source_language="ko"), local) is None
    )
    assert step(local, ["안녕"]) == ["안녕".upper()]


def test_estimate_counts_only_lines_the_memory_lacks(paid, monkeypatch, session):
    monkeypatch.setattr(wf, "GoogleTranslator", Recorder)
    step(paid, ["안녕"])
    data = {
        "cues": [{"start": 0, "end": 1, "text": "안녕"}, {"start": 1, "end": 2, "text": "새 문장"}],
        "target": "en",
    }
    options = WorkflowOptions(source_language="ko")
    estimate = wf.paid_estimate("translate:0", data, options, paid, session)
    assert estimate == (Decimal(len("새 문장")) / 1000 * Decimal("0.02")).quantize(
        Decimal("0.0001")
    )
    data["cues"] = data["cues"][:1]
    assert wf.paid_estimate("translate:0", data, options, paid, session) is None


def test_refinement_reuses_the_draft_when_it_fails_and_then_succeeds(paid, monkeypatch, session):
    refining = paid.model_copy(
        update={"translation_refine_enabled": True, "refine_usd_per_1k_chars": Decimal("0.05")}
    )
    monkeypatch.setattr(wf, "GoogleTranslator", Recorder)
    prompts = []

    class Refiner:
        answers = ["fail", ["polished"]]

        def __init__(self, **kwargs):
            pass

        def translate(self, job, *, drafts=None):
            prompts.append((job.prompt(drafts=drafts), list(drafts)))
            answer = Refiner.answers.pop(0)
            if answer == "fail":
                raise ProviderError("boom")
            return answer

    monkeypatch.setattr(wf, "ClaudeTranslator", Refiner)
    with pytest.raises(ProviderError):
        step(refining, ["안녕"], before=["앞 문장"], after=["뒤 문장"])
    # 보정이 실패해도 기계 번역 초안은 기억에 남아 다시 사지 않습니다.
    assert Recorder.calls == [["안녕"]]
    assert step(refining, ["안녕"], before=["앞 문장"], after=["뒤 문장"]) == ["polished"]
    assert Recorder.calls == [["안녕"]]
    assert prompts[-1][1] == ["안녕".upper()]
    assert "앞 문장" in prompts[-1][0] and "뒤 문장" in prompts[-1][0]
    providers = {r.provider for r in session.scalars(select(TranslationMemory))}
    assert providers == {"google", "google:refine"}
    # 단가는 번역과 보정을 더한 값입니다.
    assert wf.translation_rate(refining) == Decimal("0.07")


def test_translate_step_records_qa_without_changing_the_text(
    paid, monkeypatch, client, auth_headers, tmp_path
):
    client.put(
        "/workflow/glossary",
        headers=auth_headers,
        json={"source_language": "ko", "target_language": "en", "entries": {"뉴진스": "NewJeans"}},
    )

    class Translator(Recorder):
        def translate(self, texts, target, source=None):
            # 자리표시자를 지워 버리는 나쁜 번역기. 숫자도 잃습니다.
            return ["New Jeans debuted" for _ in texts]

    monkeypatch.setattr(wf, "GoogleTranslator", Translator)
    options = WorkflowOptions(audio_mode="subtitles", source_language="ko")
    data = {"cues": [{"start": 0, "end": 1, "text": "뉴진스는 2022년에 데뷔했다"}], "target": "en"}
    result = wf.execute_step(
        "translate:0", options, data, None, tmp_path, "s", None, lambda x: None
    )
    assert result["translated"][0]["text"] == "New Jeans debuted"
    assert result["translation_qa"] == [
        {"index": 0, "issues": ["용어집: 뉴진스→NewJeans", "숫자 누락: 2022"]}
    ]


def test_batches_follow_scene_gaps_and_the_provider_cap(paid):
    cues = [{"start": i, "end": i + 0.5, "text": "x"} for i in range(60)]
    for i, c in enumerate(cues[30:], start=30):
        c["start"], c["end"] = 100 + (i - 30), 100.5 + (i - 30)
    assert len(wf.translation_batch({"cues": cues}, paid)) == 30
    assert len(wf.translation_batch({"cues": cues, "translated": cues[:30]}, paid)) == 30
    deepl = paid.model_copy(
        update={"translation_provider": "deepl", "translate_max_batch_lines": 100}
    )
    assert all(
        len(wf.translation_batch({"cues": cues[:52], "translated": cues[:i]}, deepl)) <= 50
        for i in (0, 26)
    )


def test_job_creation_rejects_unsupported_directions(client, auth_headers, session, user):
    asset = SourceAsset(
        storage_key="s",
        original_filename="s.mp4",
        upload_state="verified",
        duration_seconds=10,
        created_by_id=user.id,
    )
    session.add(asset)
    session.commit()

    def create(target, source):
        return client.post(
            "/jobs",
            headers=auth_headers,
            json={
                "source_asset_id": str(asset.id),
                "target_language": target,
                "workflow": {
                    "audio_mode": "subtitles",
                    "source_language": source,
                    "transcript": [{"start": 1, "end": 2, "text": "x"}],
                },
            },
        )

    assert create("vi", "ko").status_code == 201
    assert create("vi", "en").status_code == 422
    assert create("fr", None).status_code == 422
    assert create("en", None).status_code == 201


def test_configuration_lists_languages_and_provider(client, auth_headers):
    data = client.get("/workflow/configuration", headers=auth_headers).json()
    assert data["translation_provider"] == "google"
    assert [row["code"] for row in data["languages"]][:4] == ["ko", "en", "ja", "zh"]
    assert ["ko", "hi"] in data["directions"]
