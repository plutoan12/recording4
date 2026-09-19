"""자막 싱크 보정. 실제 ffsubsync를 돌립니다.

기준을 SRT로 주면 오디오도 ffmpeg도 없이 같은 코드 경로가 돕니다. 원본 음성을
기준으로 쓸 때와 다른 것은 기준을 무엇에서 뽑느냐뿐입니다. 실제 음성으로 재는
것은 scripts/verify_sync.py가 CI에서 합니다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.editing import Cue
from pipeline.subtitle_files import dump_subtitles, parse_subtitles

pytest.importorskip("ffsubsync", reason="subtitles extra가 있어야 보정기를 돌립니다.")

from worker.analysis import SyncOptions, sync_subtitles  # noqa: E402

TRUE_CUES = [
    Cue(start=5, end=7, text="첫 문장입니다"),
    Cue(start=10, end=12, text="둘째 문장입니다"),
    Cue(start=15, end=17, text="셋째 문장입니다"),
]


def reference(tmp_path: Path) -> Path:
    path = tmp_path / "reference.srt"
    path.write_text(dump_subtitles(TRUE_CUES), encoding="utf-8")
    return path


def shifted(seconds: float) -> list[Cue]:
    return [Cue(start=c.start + seconds, end=c.end + seconds, text=c.text) for c in TRUE_CUES]


@pytest.mark.parametrize("offset", [2.5, -2.5])
def test_sync_recovers_a_known_shift(tmp_path, offset):
    """아는 만큼 밀어 둔 자막을 되돌려 놓는지 봅니다. 통과만 보면 아무것도 모릅니다."""
    moved, report = sync_subtitles(reference(tmp_path), shifted(offset))
    assert report["offset_seconds"] == pytest.approx(-offset, abs=0.1)
    for got, want in zip(moved, TRUE_CUES, strict=True):
        assert got.start == pytest.approx(want.start, abs=0.1)
        assert got.text == want.text


def test_sync_keeps_our_text_even_if_the_tool_rewrites_it(tmp_path):
    """대본은 사람이 정한 것입니다. 보정기가 글자를 다시 써도 우리 글자를 지킵니다."""
    cues = [
        Cue(start=c.start + 2.5, end=c.end + 2.5, text=f"{c.text} <i>꾸밈</i>") for c in TRUE_CUES
    ]
    moved, _ = sync_subtitles(reference(tmp_path), cues)
    assert [c.text for c in moved] == [c.text for c in cues]


def test_sync_refuses_when_there_is_nothing_to_move(tmp_path):
    with pytest.raises(ValueError):
        sync_subtitles(reference(tmp_path), [])


def test_dump_keeps_one_cue_per_cue(tmp_path):
    """규칙을 적용해 보내면 개수가 달라져 돌아온 시각을 맞출 수 없습니다."""
    long_line = Cue(start=0, end=8, text="가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차")
    again, _ = parse_subtitles(dump_subtitles([long_line]))
    assert len(again) == 1


def test_default_options_turn_off_framerate_fixing():
    """대본은 이 원본에서 나왔습니다. 프레임률이 다를 수 없으므로 맞추지 않습니다.

    켜 두면 보정기가 없는 차이를 맞추려고 자막을 늘였다 줄입니다. 합성 음성
    측정에서 배율 0.999가 나와 이미 맞는 자막을 0.013초 흔들었고, 끄면 오차가
    0.000초였습니다.
    """
    assert "--no-fix-framerate" in SyncOptions().arguments()
    assert "--no-fix-framerate" not in SyncOptions(fix_framerate=True).arguments()


def test_options_bound_the_search_instead_of_leaving_it_wide_open():
    """ffsubsync 기본값 60초는 다른 판본에서 받은 자막을 위한 값입니다."""
    assert SyncOptions().max_offset_seconds < 60
    assert "--max-offset-seconds" in SyncOptions().arguments()


def test_options_reject_a_vad_name_the_tool_does_not_know():
    """모르는 이름을 넘기면 argparse가 그 자리에서 워커를 끝냅니다. 미리 막습니다."""
    with pytest.raises(ValueError, match="발화 검출기"):
        SyncOptions(vad="webrtcvad").arguments()
    assert SyncOptions(vad="auditok").arguments()[-2:] == ["--vad", "auditok"]


def test_options_reject_a_search_bound_that_cannot_work():
    with pytest.raises(ValueError):
        SyncOptions(max_offset_seconds=0).arguments()


def test_sync_refuses_a_correction_that_pushes_subtitles_before_the_start(tmp_path, monkeypatch):
    """원본 앞으로 밀린 자막은 파일에서 사라집니다.

    그러면 "개수가 다르다"는 말만 남고 무엇이 잘못됐는지 안 보입니다. 사람
    목소리 34초 표본에서 보정기가 -23.25초를 **성공이라고** 내놓은 적이 있어
    실제로 겪은 실패입니다.
    """
    import worker.analysis as analysis

    def pretend(args):
        # 보정기가 자신 있게 터무니없는 값을 돌려주는 상황입니다.
        Path(args.srtout).write_text(dump_subtitles(TRUE_CUES), encoding="utf-8")
        return {"retval": 0, "sync_was_successful": True, "offset_seconds": -23.25}

    monkeypatch.setattr(analysis, "_run_sync", pretend)
    with pytest.raises(ValueError, match="원본 시작 앞으로"):
        sync_subtitles(reference(tmp_path), shifted(2.5))
