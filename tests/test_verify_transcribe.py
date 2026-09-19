"""전사 품질 측정의 계산 부분. 모델 없이 도는 순수 계산만 봅니다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from pipeline.editing import Cue


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location(
        "r4verify_transcribe", Path(__file__).parents[1] / "scripts/verify_transcribe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_words_with_different_spacing_have_no_error(verify) -> None:
    """띄어쓰기와 문장부호까지 오류로 세면 실제 오인식 양을 알 수 없습니다."""
    assert (
        verify.cer("안녕하세요 오늘은 자막을 만듭니다", "안녕하세요, 오늘은자막을 만듭니다.") == 0.0
    )


def test_one_wrong_character_is_one_error(verify) -> None:
    assert verify.cer("자막 정렬", "자막 정력") == pytest.approx(1 / 4)


def test_empty_transcript_is_a_total_miss(verify) -> None:
    assert verify.cer("자막", "") == 1.0


def test_empty_reference_does_not_divide_by_zero(verify) -> None:
    assert verify.cer("", "무언가") == 0.0


def test_sentences_take_the_transcript_that_overlaps_them_in_time(verify) -> None:
    """전사는 문장 수와 다르게 나뉩니다. 겹치는 시간으로 모아야 짝이 맞습니다."""
    sentences = [{"text": "가", "start": 1.0, "end": 5.0}, {"text": "나", "start": 6.0, "end": 9.0}]
    cues = [
        Cue(start=1.0, end=3.0, text="첫"),
        Cue(start=3.0, end=5.0, text="번째"),
        Cue(start=6.2, end=8.9, text="두 번째"),
    ]
    assert [heard for _, heard in verify.pair_by_time(sentences, cues)] == ["첫 번째", "두 번째"]


def test_a_sentence_with_no_transcript_is_empty_not_missing(verify) -> None:
    sentences = [{"text": "가", "start": 1.0, "end": 5.0}]
    assert verify.pair_by_time(sentences, [Cue(start=6.0, end=9.0, text="딴것")]) == [
        (sentences[0], "")
    ]
