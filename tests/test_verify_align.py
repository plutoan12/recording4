"""정렬 검증 스크립트의 판정 규칙. 검증기가 틀리면 검증이 통과해도 소용없습니다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from pipeline.editing import Cue


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location(
        "r4verify_align", Path(__file__).parents[1] / "scripts/verify_align.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SENTENCES = [
    {"text": "가", "start": 1.0, "end": 5.45},
    {"text": "나", "start": 6.45, "end": 11.23},
]


def test_end_inside_its_own_sentence_is_fine(verify) -> None:
    cues = [Cue(start=1.0, end=5.4, text="가"), Cue(start=6.45, end=11.2, text="나")]
    assert verify.report_ends(cues, SENTENCES) == []


def test_end_reaching_into_the_next_sentence_is_reported(verify) -> None:
    """앞 자막이 다음 말이 시작된 뒤에도 남으면 화면에서 겹쳐 보입니다."""
    cues = [Cue(start=1.0, end=7.0, text="가"), Cue(start=7.05, end=11.2, text="나")]
    problems = verify.report_ends(cues, SENTENCES)
    assert len(problems) == 1
    assert "6.45" in problems[0]


def test_a_cue_spanning_its_own_sentence_only_is_not_an_intrusion(verify) -> None:
    """자기 문장의 시작은 침범 판정에서 빼야 합니다. 안 빼면 모든 자막이 걸립니다."""
    cues = [Cue(start=1.0, end=5.45, text="가")]
    assert verify.report_ends(cues, SENTENCES) == []


def test_line_rule_broken_after_shaping_is_a_failure(verify, monkeypatch) -> None:
    """규칙을 거친 뒤에도 줄 수가 넘으면 화면에서 깨집니다."""
    from pipeline import subtitles

    monkeypatch.setattr(verify, "apply_rules", lambda cues, rules: cues)
    long_text = "가나다라마바사아자차카타파하" * 4
    problems = verify.report_rules([Cue(start=1.0, end=20.0, text=long_text)])
    assert any("줄" in p for p in problems)
    assert subtitles.text_width(long_text) > subtitles.DEFAULT_RULES.capacity


def test_reading_speed_is_reported_not_failed(verify) -> None:
    """CPS는 나눠도 줄지 않습니다. 말이 빠른 대본의 성질이지 정렬 결함이 아닙니다."""
    cues = [Cue(start=1.0, end=1.6, text="아주 빠르게 말한 긴 문장입니다 정말로 빠릅니다")]
    assert verify.report_rules(cues) == []
