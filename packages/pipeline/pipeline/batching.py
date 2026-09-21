"""장면 단위 번역 묶음. LLM-Subtrans의 SubtitleBatcher를 옮겼습니다.

출처: https://github.com/machinewrapped/llm-subtrans (PySubtrans/SubtitleBatcher.py), MIT.
THIRD_PARTY_NOTICES.md에 원 저작권 고지를 둡니다.

규칙은 둘입니다. (1) 앞 자막 끝과 다음 자막 시작 사이가 `scene_gap`보다 벌어지면
장면이 바뀐 것으로 보고 묶음을 끊습니다. (2) 한 장면이 `max_lines`보다 길면
**가장 긴 틈**에서 반으로 가르기를 반복합니다. 묶음 경계가 말의 흐름을 덜
가르므로 앞뒤 문맥을 넣는 번역기가 덜 헷갈리고, 실패한 묶음만 다시 보내도
문맥 손실이 적습니다. 여기에 글자 수 상한(`max_chars`)만 더했습니다. 공급자
요청 한도(Google 25,000자) 때문입니다.
"""

from __future__ import annotations

from collections.abc import Sequence

# LLM-Subtrans 기본값. 30초는 장면 전환으로 보는 침묵입니다.
DEFAULT_SCENE_GAP = 30.0
DEFAULT_MIN_LINES = 1
DEFAULT_MAX_LINES = 100
DEFAULT_MAX_CHARS = 25000


def _split(
    cues: Sequence[dict], min_lines: int, max_lines: int, max_chars: int
) -> list[list[dict]]:
    """가장 긴 틈에서 반복해서 가릅니다(SubtitleBatcher._split_lines)."""
    count = len(cues)
    chars = sum(len(c["text"]) for c in cues)
    if count <= max_lines and chars <= max_chars:
        return [list(cues)]
    if count < 2:
        return [list(cues)]
    longest, split_at = -1.0, max(1, min(min_lines, count - 1))
    last = count - min_lines
    for i in range(max(1, min_lines), max(last, max(1, min_lines) + 1)):
        if i >= count:
            break
        gap = float(cues[i]["start"]) - float(cues[i - 1]["end"])
        if gap > longest:
            longest, split_at = gap, i
    return _split(cues[:split_at], min_lines, max_lines, max_chars) + _split(
        cues[split_at:], min_lines, max_lines, max_chars
    )


def scene_batches(
    cues: Sequence[dict],
    *,
    scene_gap: float = DEFAULT_SCENE_GAP,
    min_lines: int = DEFAULT_MIN_LINES,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[list[dict]]:
    """자막을 장면 → 묶음으로 나눕니다. 각 묶음은 원본 순서를 지킵니다."""
    if min_lines > max_lines:
        raise ValueError("min_lines는 max_lines보다 클 수 없습니다.")
    scenes: list[list[dict]] = []
    current: list[dict] = []
    previous: dict | None = None
    for cue in cues:
        gap = float(cue["start"]) - float(previous["end"]) if previous else None
        if gap is not None and gap > scene_gap and current:
            scenes.append(current)
            current = []
        current.append(cue)
        previous = cue
    if current:
        scenes.append(current)
    batches: list[list[dict]] = []
    for scene in scenes:
        batches.extend(_split(scene, min_lines, max_lines, max_chars))
    return batches


def batch_starts(cues: Sequence[dict], **options) -> list[int]:
    """각 묶음의 첫 자막 번호. 단계 이름 `translate:N`의 N이 여기 값 중 하나입니다."""
    starts, index = [], 0
    for batch in scene_batches(cues, **options):
        starts.append(index)
        index += len(batch)
    return starts
