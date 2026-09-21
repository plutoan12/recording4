"""번역 묶음의 모양: 번호 줄 + 앞뒤 문맥 + 이 묶음에 필요한 규칙만."""

from __future__ import annotations

import pytest

from pipeline.translation_jobs import build_job


def test_context_is_bounded_and_marked_not_to_translate():
    job = build_job(
        ["방탄소년단 노래", "안녕"],
        source="ko",
        target="en",
        before=["a", "b", "c", "d"],
        after=["e", "f", "g", "h"],
        entries={"방탄소년단": "BTS", "없는말": "x"},
    )
    prompt = job.prompt()
    assert [line.text for line in job.context_before] == ["b", "c", "d"]
    assert [line.text for line in job.context_after] == ["e", "f", "g"]
    assert "#0\t방탄소년단 노래" in prompt and "#1\t안녕" in prompt
    assert "방탄소년단 → BTS" in prompt and "없는말" not in prompt
    assert "do not translate" in prompt and "한국어 → 영어" in prompt


def test_refine_prompt_carries_source_and_draft_per_line():
    job = build_job(["안녕"], source="ko", target="en", entries={})
    assert "#0\t안녕\tHi" in job.prompt(drafts=["Hi"])
    with pytest.raises(ValueError):
        job.prompt(drafts=["one", "two"])
