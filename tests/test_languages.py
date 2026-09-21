"""언어 목록과 번역 방향은 pipeline.languages 한 곳에서만 나옵니다."""

from __future__ import annotations

import pytest

from pipeline.languages import (
    CORE,
    DEEPL_TARGETS,
    LANGUAGES,
    NLLB_CODES,
    TIER2,
    TIER3,
    catalogue,
    is_supported,
    provider_code,
    sources,
    targets_for,
)


@pytest.mark.parametrize("source", CORE)
@pytest.mark.parametrize("target", CORE)
def test_core_languages_translate_in_every_direction(source, target):
    assert is_supported(source, target)


@pytest.mark.parametrize("target", TIER2 + TIER3)
def test_extra_languages_come_from_korean_only(target):
    assert is_supported("ko", target)
    assert not is_supported("en", target)
    assert not is_supported(target, "ko")


def test_same_language_passes_without_translation():
    assert is_supported("es", "es")


def test_unknown_source_accepts_any_listed_target():
    assert is_supported(None, "hi")
    assert not is_supported(None, "fr")


def test_region_suffix_is_ignored():
    assert is_supported("zh-CN", "ja")


def test_catalogue_matches_the_tables():
    data = catalogue()
    assert [row["code"] for row in data["languages"]] == list(LANGUAGES)
    assert data["sources"] == sources() == list(CORE)
    assert ("ko", "vi") in {tuple(d) for d in data["directions"]}
    assert targets_for("ko") == [c for c in LANGUAGES if c != "ko"]
    assert targets_for("ja") == ["ko", "en", "zh"]


def test_every_language_has_a_provider_code():
    for code in LANGUAGES:
        assert provider_code(DEEPL_TARGETS, code, "DeepL")
        assert provider_code(NLLB_CODES, code, "NLLB")
    with pytest.raises(ValueError, match="NLLB"):
        provider_code(NLLB_CODES, "fr", "NLLB")
