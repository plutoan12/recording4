"""번역 품질 측정의 계산 부분. 번역기 없이 도는 것만 봅니다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location(
        "r4verify_translate", Path(__file__).parents[1] / "scripts/verify_translate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identical_text_scores_one(verify) -> None:
    assert verify.chrf("the cat sat", "the cat sat") == pytest.approx(1.0)


def test_unrelated_text_scores_near_zero(verify) -> None:
    assert verify.chrf("the cat sat on the mat", "완전히 다른 문장입니다") < 0.05


def test_a_close_translation_scores_higher_than_a_wrong_one(verify) -> None:
    """수치가 방향은 맞아야 회귀 감시에 쓸 수 있습니다."""
    reference = "Department stores and cinemas are currently open for business."
    close = "Department stores and movie theaters are open for business now."
    wrong = "The weather tomorrow will be cold and windy."
    assert verify.chrf(reference, close) > verify.chrf(reference, wrong)


def test_spacing_differences_barely_matter(verify) -> None:
    """띄어쓰기 차이를 오류로 세면 번역 품질을 볼 수 없습니다."""
    assert verify.chrf("the cat sat", "thecat  sat") == pytest.approx(1.0)


def test_english_subtitles_are_checked_against_the_english_rules(verify) -> None:
    """번역이 맞아도 자막으로 안 들어가면 화면에서는 깨집니다."""
    source = "현재 백화점과 영화관 등은 오픈해 영업하고 있습니다"
    report, problems = verify.fits_rules(
        ["Department stores and cinemas are open."], "en", verify.spans([source], "ko")
    )
    assert report and problems == []


def test_the_window_comes_from_the_source_not_the_translation(verify) -> None:
    """번역문 길이로 시간을 주면 아무리 길어져도 들어가서 검사가 헛돕니다."""
    source = "짧은 문장입니다"
    short, long = verify.spans([source], "ko"), verify.spans([source * 8], "ko")
    assert short < long


def test_a_translation_that_outgrows_its_window_is_reported(verify) -> None:
    """원문이 쓰던 시간에 못 들어가는 번역은 화면에서 줄이 넘칩니다."""
    source = "짧은 문장입니다"
    window = verify.spans([source], "ko")
    assert window[0] < 2.0  # 한 자막 몫밖에 안 되는 시간입니다.
    _, problems = verify.fits_rules(["This is a short sentence " * 6], "en", window)
    assert problems
