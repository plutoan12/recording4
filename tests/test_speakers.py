"""화자 배정 규칙. 순수 계산이라 외부 의존성 없이 검증합니다."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn, assign_speakers, speaker_totals


def test_turn_rejects_impossible_values() -> None:
    with pytest.raises(ValueError):
        SpeakerTurn(start=2, end=1, speaker="A")
    with pytest.raises(ValueError):
        SpeakerTurn(start=0, end=1, speaker="")


def test_cue_takes_the_speaker_it_overlaps_most() -> None:
    cues = [Cue(start=0, end=4, text="안녕하세요")]
    turns = [
        SpeakerTurn(start=0, end=1, speaker="A"),
        SpeakerTurn(start=1, end=4, speaker="B"),
    ]
    assert assign_speakers(cues, turns) == ["B"]


def test_cue_without_overlap_stays_unlabeled() -> None:
    """가까운 화자를 추측해서 붙이지 않습니다."""
    cues = [Cue(start=10, end=12, text="여기는 화자 구간 밖")]
    turns = [SpeakerTurn(start=0, end=5, speaker="A")]
    assert assign_speakers(cues, turns) == [None]


def test_ties_go_to_the_earlier_speaker() -> None:
    cues = [Cue(start=0, end=2, text="반반")]
    turns = [
        SpeakerTurn(start=1, end=2, speaker="B"),
        SpeakerTurn(start=0, end=1, speaker="A"),
    ]
    assert assign_speakers(cues, turns) == ["A"]


def test_each_cue_is_labeled_independently() -> None:
    cues = [
        Cue(start=0, end=2, text="첫 번째"),
        Cue(start=2, end=4, text="두 번째"),
        Cue(start=4, end=6, text="세 번째"),
    ]
    turns = [
        SpeakerTurn(start=0, end=2, speaker="A"),
        SpeakerTurn(start=2, end=4, speaker="B"),
        SpeakerTurn(start=4, end=6, speaker="A"),
    ]
    assert assign_speakers(cues, turns) == ["A", "B", "A"]


def test_no_turns_means_no_labels() -> None:
    assert assign_speakers([Cue(start=0, end=1, text="가")], []) == [None]


def test_totals_sum_per_speaker_in_descending_order() -> None:
    turns = [
        SpeakerTurn(start=0, end=1, speaker="A"),
        SpeakerTurn(start=1, end=4, speaker="B"),
        SpeakerTurn(start=4, end=5, speaker="A"),
    ]
    assert speaker_totals(turns) == {"B": 3.0, "A": 2.0}
    assert list(speaker_totals(turns)) == ["B", "A"]


def test_windows_cut_a_long_span_into_overlapping_pieces() -> None:
    """한 구간 안에서 화자가 바뀔 수 있습니다. 통째로 보면 경계를 못 찾습니다."""
    from pipeline.speakers import windows

    cut = windows([(0.0, 3.0)], length=1.5, hop=0.75)
    assert cut[0] == (0.0, 1.5)
    assert cut[1][0] == 0.75  # 겹칩니다
    assert cut[-1][1] == 3.0  # 끝을 버리지 않습니다


def test_a_span_shorter_than_the_window_is_kept_whole() -> None:
    from pipeline.speakers import windows

    assert windows([(1.0, 1.9)], length=1.5, hop=0.75) == [(1.0, 1.9)]


def test_cluster_splits_two_directions_of_vectors() -> None:
    """같은 방향끼리 묶입니다. 크기가 달라도 방향이 같으면 같은 묶음입니다."""
    from pipeline.speakers import cluster

    labels = cluster([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 2.0]], 2)
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]


def test_cluster_is_the_same_on_a_second_run() -> None:
    """무작위 시작점을 쓰면 같은 음성을 두 번 재도 답이 달라집니다."""
    from pipeline.speakers import cluster

    vectors = [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0], [0.2, 0.9], [0.9, 0.1]]
    assert cluster(vectors, 2) == cluster(vectors, 2)


def test_turns_join_neighbouring_windows_of_the_same_voice() -> None:
    from pipeline.speakers import turns_from_labels

    turns = turns_from_labels([(0.0, 1.5), (0.75, 2.25), (3.0, 4.5)], [0, 0, 1])
    assert [(t.start, t.end, t.speaker) for t in turns] == [
        (0.0, 2.25, "SPEAKER_00"),
        (3.0, 4.5, "SPEAKER_01"),
    ]


def test_a_voice_change_inside_a_span_becomes_two_turns() -> None:
    from pipeline.speakers import turns_from_labels

    turns = turns_from_labels([(0.0, 1.5), (1.5, 3.0)], [0, 1])
    assert [t.speaker for t in turns] == ["SPEAKER_00", "SPEAKER_01"]
    assert turns[1].start == 1.5


def test_embedding_diarizer_refuses_a_speaker_count_below_one() -> None:
    """모델을 내려받기 전에 막습니다. 잘못된 값으로 큰 모델을 부르지 않습니다."""
    from worker.analysis import diarize_by_embedding

    with pytest.raises(ValueError):
        diarize_by_embedding(Path("/nonexistent.wav"), speakers=0)


def test_diarization_arguments_use_the_name_this_version_accepts() -> None:
    """인자 이름이 버전마다 바뀝니다. 고정해 두면 다음 버전에서 또 막힙니다.

    측정: 설치된 whisperx는 use_auth_token을 받지 않아 화자 분리가 시작조차
    되지 못했습니다(TypeError). 토큰이 있어도 실패했을 것입니다.
    """
    from worker.analysis import diarization_arguments

    class New:  # 새 이름만 받는 버전
        def __init__(self, token=None, device="cpu"): ...

    class Old:  # 옛 이름만 받는 버전
        def __init__(self, use_auth_token=None, device="cpu"): ...

    assert diarization_arguments(New, token="t", device="cpu") == {"token": "t", "device": "cpu"}
    assert diarization_arguments(Old, token="t", device="cpu") == {
        "use_auth_token": "t",
        "device": "cpu",
    }


def test_diarization_arguments_refuse_a_version_with_no_token_slot() -> None:
    """토큰을 넘길 자리가 없으면 조용히 토큰 없이 부르지 않습니다."""
    import pytest

    from worker.analysis import MissingDependency, diarization_arguments

    class NoToken:
        def __init__(self, device="cpu"): ...

    with pytest.raises(MissingDependency):
        diarization_arguments(NoToken, token="t", device="cpu")


def test_gated_hint_names_the_model_this_version_uses() -> None:
    """버전마다 기본 모델이 다릅니다. 쓰는 모델 페이지에서 동의해야 합니다."""
    from worker.analysis import default_model_name, gated_hint

    class Pipeline:
        def __init__(self, model_name="pyannote/speaker-diarization-community-1"): ...

    model = default_model_name(Pipeline)
    assert model == "pyannote/speaker-diarization-community-1"
    text = gated_hint("무엇", model)
    assert f"https://huggingface.co/{model}" in text
    assert "segmentation-3.0" in text
