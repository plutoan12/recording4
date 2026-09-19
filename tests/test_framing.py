"""세로로 자를 때 어디를 남길지 정하는 규칙. 검출기는 돌리지 않습니다.

얼굴을 찾는 일과 그 결과로 제안을 만드는 일을 나눠 두었습니다. 여기서는
뒤쪽만 봅니다. 검출기가 없어도, 검출기를 바꿔도 이 규칙은 그대로여야
합니다.
"""

from __future__ import annotations

import pytest

from pipeline.framing import Box, biggest, middle, suggest_focus


def face(x: float, width: float = 100.0) -> Box:
    return Box(x=x, y=100.0, width=width, height=width)


def test_the_biggest_face_wins_not_the_crowd() -> None:
    """뒤에 지나가는 사람까지 세면 화면이 가운데로 끌려갑니다."""
    speaker, passerby = face(800, 200), face(100, 40)
    assert biggest([passerby, speaker]) is speaker


def test_no_face_means_no_choice() -> None:
    assert biggest([]) is None


def test_the_middle_value_ignores_one_bad_frame() -> None:
    """평균이면 한 장의 오검출이 제안을 끌고 갑니다."""
    assert middle([0.4, 0.42, 0.41, 0.95]) == pytest.approx(0.415)


def test_a_steady_speaker_moves_the_crop_to_them() -> None:
    """이게 이 기능의 요점입니다. 한쪽에 서 있는 사람을 가운데로 데려옵니다."""
    frames = [[face(1300)] for _ in range(10)]
    found = suggest_focus(frames, width=1920)
    assert found.focus_x == pytest.approx(0.703, abs=0.01)
    assert found.coverage == 1.0
    assert "가운뎃값" in found.reason


def test_a_face_seen_only_once_in_a_while_is_not_enough() -> None:
    """몇 장에서만 보인 얼굴로 화면을 옮기면 나머지 시간에 엉뚱한 곳을 비춥니다."""
    frames = [[face(1300)], [], [], [], [], [], [], [], [], []]
    found = suggest_focus(frames, width=1920)
    assert found.focus_x == 0.5
    assert found.found == 1 and found.samples == 10
    assert "10%" in found.reason


def test_a_face_that_moves_across_the_screen_gets_no_single_point() -> None:
    """한 점으로 정할 수 없는 것을 정하면 절반의 시간에 틀립니다."""
    frames = [[face(x)] for x in (100, 1700, 200, 1600, 150, 1800)]
    found = suggest_focus(frames, width=1920)
    assert found.focus_x == 0.5
    assert found.spread > 0.25
    assert "흔들려" in found.reason


def test_nothing_found_falls_back_to_the_middle_instead_of_failing() -> None:
    """얼굴이 없는 영상도 많습니다. 실패가 아니라 가운데입니다."""
    found = suggest_focus([[], [], []], width=1920)
    assert found.focus_x == 0.5 and found.found == 0


def test_a_face_outside_the_frame_cannot_push_the_crop_out() -> None:
    """검출기가 화면 밖 좌표를 줄 수 있습니다. 그대로 쓰면 자르기가 깨집니다."""
    found = suggest_focus([[face(3000)] for _ in range(5)], width=1920)
    assert 0.0 <= found.focus_x <= 1.0


def test_a_video_with_no_width_is_a_mistake_not_a_guess() -> None:
    with pytest.raises(ValueError):
        suggest_focus([[face(100)]], width=0)


def test_sample_times_stay_inside_the_clip() -> None:
    """처음과 끝은 화면 전환이 걸리기 쉬워 조금 안쪽에서 봅니다."""
    from worker.faces import sample_times

    times = sample_times(10.0, step=1.0)
    assert times and all(0 < t < 10.0 for t in times)
    assert sample_times(0.0) == []
    # 아주 짧은 영상도 한 장은 봐야 합니다.
    assert len(sample_times(0.4, step=1.0)) == 1


def test_the_cascade_file_is_looked_for_where_the_image_puts_it(tmp_path, monkeypatch) -> None:
    """opencv-python-headless에는 이 파일이 없습니다(CI 실측). 어디를 보는지 고정합니다."""
    from worker.faces import CASCADE_NAME, MissingDependency, cascade_path

    placed = tmp_path / CASCADE_NAME
    placed.write_text("<opencv_storage/>", encoding="utf-8")
    monkeypatch.setenv("R4_FACE_CASCADE", str(placed))
    assert cascade_path() == placed

    # 없으면 조용히 "얼굴 없음"이 아니라 무엇이 없는지 말해야 합니다. 그래야
    # 설정을 켜 놓고도 왜 안 되는지 알 수 있습니다.
    monkeypatch.setenv("R4_FACE_CASCADE", str(tmp_path / "없는파일.xml"))
    monkeypatch.setattr("worker.faces.IMAGE_CASCADE", tmp_path / "역시없음.xml")
    with pytest.raises(MissingDependency) as failure:
        cascade_path()
    assert "headless" in str(failure.value)
