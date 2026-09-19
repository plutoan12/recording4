"""자막을 단어 단위로 다시 맞추는 경로. 정렬기는 대역입니다.

실제 정렬 품질은 CI의 사람 목소리 검증이 봅니다. 여기서는 **정렬 결과를 우리
자막에 어떻게 붙이는지**만 봅니다. 그 자리에서 났던 실수가 있습니다.
`keep_duration` 코드가 빠진 채 문서만 들어갔는데, 측정값이 그대로라 CI도
알아채지 못했습니다.

ffsubsync가 없어도 도는 검사만 둡니다. 통째로 옮기기 검사는 test_subtitle_sync.py에
있고 그쪽은 ffsubsync가 있어야 돌아서, 섞어 두면 이 검사들까지 건너뜁니다.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.editing import Cue


def test_realign_keeps_our_durations_and_uses_only_the_aligned_start(monkeypatch):
    """정렬기의 끝 시각은 쓰지 않습니다. 말끝 숨소리·잔향을 잘라 이르게 끝납니다.

    이 검사가 없어서 `keep_duration` 코드가 빠진 채로 문서만 들어간 적이
    있습니다. 측정값이 그대로라 CI도 알아채지 못했습니다.
    """
    import worker.analysis as analysis

    original = [
        Cue(start=10, end=14, text="첫 문장입니다"),
        Cue(start=20, end=23, text="둘째 문장입니다"),
    ]
    # 정렬기가 시작을 1초 당기고 끝을 1.5초 이르게 잡은 상황입니다.
    monkeypatch.setattr(
        analysis,
        "align_text",
        lambda source, text, **kwargs: [
            Cue(start=9, end=11.5, text="첫 문장입니다"),
            Cue(start=19, end=20.5, text="둘째 문장입니다"),
        ],
    )
    moved, report = analysis.realign_subtitles(Path("unused"), original)
    assert report["keep_duration"] is True
    # 시작은 정렬기 값, 길이는 원래 값입니다.
    assert [(c.start, c.end) for c in moved] == [(9.0, 13.0), (19.0, 22.0)]

    raw, _ = analysis.realign_subtitles(Path("unused"), original, keep_duration=False)
    assert [(c.start, c.end) for c in raw] == [(9.0, 11.5), (19.0, 20.5)]


def test_realign_does_not_let_a_kept_duration_run_into_the_next_cue(monkeypatch):
    """길이를 지키다 다음 자막을 덮으면 화면에서 두 자막이 겹칩니다."""
    import worker.analysis as analysis

    original = [Cue(start=10, end=19, text="긴 자막"), Cue(start=20, end=22, text="다음")]
    monkeypatch.setattr(
        analysis,
        "align_text",
        lambda source, text, **kwargs: [
            Cue(start=10, end=12, text="긴 자막"),
            Cue(start=13, end=15, text="다음"),
        ],
    )
    moved, _ = analysis.realign_subtitles(Path("unused"), original)
    assert moved[0].end == 13.0 and moved[1].start == 13.0
