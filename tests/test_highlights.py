"""LLM 하이라이트 추천. **실제로 부르지 않습니다.** 대역을 씁니다.

여기서 보는 것은 모델이 잘 고르는지가 아닙니다. 그건 시험으로 알 수 없습니다.
**모델이 엉뚱한 답을 줬을 때 우리가 그걸 그대로 쓰지 않는지**를 봅니다.
"""

from __future__ import annotations

import pytest

from pipeline.editing import Cue
from pipeline.highlights import (
    MAX_CUES,
    Pick,
    TooMuchTranscript,
    accept,
    numbered,
)
from worker.providers import ClaudeHighlights, ProviderError


def script(count: int = 10, seconds: float = 6.0) -> list[Cue]:
    return [
        Cue(start=i * seconds, end=(i + 1) * seconds, text=f"{i}번째 문장입니다")
        for i in range(count)
    ]


class Block:
    def __init__(self, text: str, kind: str = "text"):
        self.text, self.type = text, kind


class Reply:
    def __init__(self, text: str, stop: str = "end_turn"):
        self.content = [Block("", "thinking"), Block(text)]
        self.stop_reason = stop


class Band:
    """부르면 미리 정해 둔 답을 주는 대역. 무엇으로 불렸는지 적어 둡니다."""

    def __init__(self, reply: Reply):
        self.reply, self.calls = reply, []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


def band(payload: str, stop: str = "end_turn") -> Band:
    return Band(Reply(payload, stop))


# --- 번호를 시각으로 바꾸는 규칙 -------------------------------------------


def test_a_good_pick_becomes_a_clip_with_transcript_times() -> None:
    """이게 요점입니다. 시각은 모델이 아니라 대본에서 나옵니다."""
    taken, thrown = accept(script(), [Pick(2, 5, "제목", "웃깁니다")], duration=60)
    assert not thrown
    assert taken[0]["start"] == 12.0 and taken[0]["end"] == 36.0
    assert "자막 2~5" in taken[0]["reason"] and "웃깁니다" in taken[0]["reason"]


def test_a_number_that_is_not_in_the_transcript_is_thrown_away() -> None:
    """지어낸 번호는 여기서 걸립니다. 지어낸 시각은 걸리지 않습니다."""
    taken, thrown = accept(script(), [Pick(3, 99, "", "")], duration=60)
    assert not taken
    assert "대본에 없는 번호" in thrown[0].why


def test_a_backwards_pick_is_thrown_away() -> None:
    taken, thrown = accept(script(), [Pick(7, 2, "", "")], duration=60)
    assert not taken and "앞입니다" in thrown[0].why


def test_a_pick_shorter_than_a_shortform_is_thrown_away() -> None:
    """6초짜리 자막 하나는 숏폼이 아닙니다."""
    taken, thrown = accept(script(count=10, seconds=2.0), [Pick(0, 1, "", "")], duration=60)
    assert not taken and "5초는 넘어야" in thrown[0].why


def test_a_pick_longer_than_the_limit_is_thrown_away() -> None:
    taken, thrown = accept(script(count=40, seconds=6.0), [Pick(0, 39, "", "")], duration=300)
    assert not taken and "180초를 넘습니다" in thrown[0].why


def test_a_pick_past_the_end_of_the_video_is_thrown_away() -> None:
    """대본이 영상보다 길게 남아 있을 수 있습니다."""
    taken, thrown = accept(script(), [Pick(0, 9, "", "")], duration=30)
    assert not taken and "영상 길이" in thrown[0].why


def test_overlapping_picks_keep_only_the_first() -> None:
    """겹친 두 편을 만들면 같은 장면이 두 번 올라갑니다."""
    taken, thrown = accept(script(), [Pick(0, 3, "", ""), Pick(2, 6, "", "")], duration=60)
    assert len(taken) == 1 and "겹칩니다" in thrown[0].why


def test_the_limit_is_enforced_and_the_extra_says_so() -> None:
    """조용히 잘리면 모델이 적게 준 건지 우리가 버린 건지 알 수 없습니다."""
    picks = [Pick(i * 2, i * 2 + 1, "", "") for i in range(5)]
    taken, thrown = accept(script(count=20, seconds=6.0), picks, duration=200, limit=2)
    assert len(taken) == 2 and len(thrown) == 3
    assert all("2개까지만" in row.why for row in thrown)


def test_a_missing_title_falls_back_to_the_transcript() -> None:
    taken, _ = accept(script(), [Pick(1, 3, "", "")], duration=60)
    assert taken[0]["title"] == "1번째 문장입니다"


def test_a_missing_reason_says_so_instead_of_pretending() -> None:
    taken, _ = accept(script(), [Pick(1, 3, "제목", "  ")], duration=60)
    assert "이유를 말하지 않았습니다" in taken[0]["reason"]


def test_the_result_has_the_same_shape_as_the_rule_based_suggestions() -> None:
    """관리화면이 어느 쪽 후보인지 몰라도 되게 하려는 것입니다."""
    from pipeline.editing import suggest_clips

    rules = suggest_clips(script(count=20, seconds=6.0), duration=200)
    taken, _ = accept(script(count=20, seconds=6.0), [Pick(0, 7, "", "")], duration=200)
    assert rules and set(taken[0]) == set(rules[0])


# --- 모델에게 보낼 대본 ------------------------------------------------------


def test_the_transcript_we_send_is_numbered_from_zero() -> None:
    lines = numbered(script(count=3)).splitlines()
    assert lines[0].startswith("0\t0.0\t6.0\t")
    assert len(lines) == 3


def test_an_out_of_order_transcript_is_numbered_in_time_order() -> None:
    """번호가 시간 순이 아니면 모델이 고른 구간이 뒤집힙니다."""
    rows = script(count=3)
    lines = numbered([rows[2], rows[0], rows[1]]).splitlines()
    assert [line.split("\t")[2] for line in lines] == ["6.0", "12.0", "18.0"]


def test_too_long_a_transcript_is_refused_not_quietly_cut() -> None:
    """조용히 자르면 뒷부분이 후보에서 빠진 것을 아무도 모릅니다."""
    with pytest.raises(TooMuchTranscript):
        numbered(script(count=MAX_CUES + 1, seconds=1.0))


# --- 공급자 (대역) -----------------------------------------------------------


def test_the_paid_call_is_blocked_unless_it_is_turned_on() -> None:
    """기본 설치와 시험은 유료 API를 부르지 않습니다."""
    with pytest.raises(ProviderError):
        ClaudeHighlights(client=band("{}")).pick("0\t0.0\t6.0\t안녕")


def test_a_good_answer_becomes_picks() -> None:
    client = band('{"picks": [{"first": 1, "last": 4, "title": "제목", "reason": "이유"}]}')
    picks = ClaudeHighlights(client=client, allow_paid=True).pick(numbered(script()))
    assert picks == [Pick(1, 4, "제목", "이유")]
    sent = client.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert sent["thinking"] == {"type": "adaptive"}
    # 번호로 답하게 하는 규칙이 실제로 실려 나가는지 봅니다.
    assert "시각이 아니라 번호로 답합니다" in sent["system"]
    assert sent["output_config"]["format"]["type"] == "json_schema"


def test_a_refusal_is_reported_not_swallowed() -> None:
    client = band("", stop="refusal")
    with pytest.raises(ProviderError, match="거절"):
        ClaudeHighlights(client=client, allow_paid=True).pick(numbered(script()))


def test_a_truncated_answer_is_reported() -> None:
    """잘린 JSON을 억지로 읽으면 반쪽짜리 후보가 나옵니다."""
    client = band('{"picks": [{"first": 1,', stop="max_tokens")
    with pytest.raises(ProviderError, match="잘렸"):
        ClaudeHighlights(client=client, allow_paid=True).pick(numbered(script()))


def test_an_unreadable_answer_is_reported() -> None:
    client = band("여기 좋은 구간이 있습니다!")
    with pytest.raises(ProviderError, match="읽지 못했습니다"):
        ClaudeHighlights(client=client, allow_paid=True).pick(numbered(script()))


def test_an_empty_transcript_never_reaches_the_paid_call() -> None:
    client = band('{"picks": []}')
    with pytest.raises(ValueError):
        ClaudeHighlights(client=client, allow_paid=True).pick("   ")
    assert not client.calls


def test_the_model_can_answer_with_nothing() -> None:
    """좋은 후보가 없으면 없다고 답해야 합니다. 숫자를 채우면 안 됩니다."""
    client = band('{"picks": []}')
    picks = ClaudeHighlights(client=client, allow_paid=True).pick(numbered(script()))
    taken, thrown = accept(script(), picks, duration=60)
    assert taken == [] and thrown == []
