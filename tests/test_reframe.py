"""자동 리프레이밍. 떨지 않는 경로와 FFmpeg crop 식."""

from __future__ import annotations

import pytest

from pipeline.editing import EditSpec, ReframeSettings
from pipeline.reframe import center_expression, crop_x, follow, keyframes
from worker.rendering import clip_path, video_filter

STEADY = ReframeSettings(deadzone=0.0, max_speed=2.0)


def test_a_small_wobble_does_not_move_the_frame():
    """고개만 까딱할 때 화면이 따라 흔들리면 보기 나쁩니다."""
    track = [(0.0, 0.50), (0.5, 0.53), (1.0, 0.48), (1.5, 0.52)]
    assert [value for _, value in follow(track, settings=ReframeSettings(deadzone=0.06))] == [
        0.5
    ] * 4


def test_a_real_move_is_followed_but_not_faster_than_the_limit():
    track = [(0.0, 0.2), (1.0, 0.9)]
    path = follow(track, settings=ReframeSettings(deadzone=0.0, max_speed=0.25))
    # 1초에 0.25까지만 끌고 갑니다.
    assert path[-1][1] == pytest.approx(0.45)


def test_the_path_stays_inside_the_frame():
    track = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]
    assert all(0.0 <= value <= 1.0 for _, value in follow(track, settings=STEADY))


def test_no_faces_means_no_path():
    assert follow([]) == []


def test_keyframes_thin_out_points_that_are_too_close():
    dense = [(at / 100, 0.5) for at in range(300)]
    keys = keyframes(dense, limit=40, step=0.2)
    assert len(keys) <= 40
    assert keys[0] == dense[0] and keys[-1] == dense[-1]


def test_the_expression_holds_the_first_value_before_it_starts():
    path = [(1.0, 0.3), (2.0, 0.7)]
    expression = center_expression(path)
    assert expression.startswith("lt(t,1.000)*0.3000")
    # 마지막 구간은 끝을 열어 둡니다(영상 끝까지).
    assert "gte(t,1.000)*(0.3000+(0.4000)*(t-1.000)/1.000)" in expression


def test_segments_do_not_overlap_at_their_edges():
    """`between()`은 양끝을 포함해 경계에서 두 구간이 함께 더해집니다."""
    expression = center_expression([(0.0, 0.2), (1.0, 0.4), (2.0, 0.6)])
    assert "between(" not in expression
    assert "gte(t,0.000)*lt(t,1.000)" in expression


def test_crop_x_clamps_to_the_frame_and_falls_back_to_focus_x():
    assert crop_x([], 0.25) == "clip((0.2500)*iw-ow/2,0,iw-ow)"
    assert crop_x([(0.0, 0.5)], 0.25).startswith("clip((0.5000)*iw-ow/2,0,iw-ow)")


def test_the_crop_filter_quotes_the_expression():
    spec = EditSpec(start=0, end=10, mode="crop", reframe=ReframeSettings())
    chain = video_filter(spec, [(0.0, 0.3), (1.0, 0.7)])
    assert ":'clip((" in chain, chain
    # 고정 위치일 때는 지금까지와 같은 모양입니다.
    assert "crop=1080:1920:(iw-ow)*0.5:" in video_filter(spec)


def spec(**extra) -> EditSpec:
    return EditSpec(start=10, end=20, mode="crop", reframe=ReframeSettings(**extra))


def test_reframing_is_off_for_padded_output(tmp_path):
    """`pad`는 화면 전체를 남기므로 따라갈 것이 없습니다."""
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    padded = EditSpec(start=10, end=20, mode="pad", reframe=ReframeSettings())
    assert clip_path(source, padded, [(0.0, 10.0)], [(0.0, 0.8)]) == []


def test_reframing_is_off_without_settings(tmp_path):
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    assert clip_path(source, EditSpec(start=10, end=20), [(0.0, 10.0)], [(0.0, 0.8)]) == []


def test_face_times_move_onto_the_trimmed_timeline(tmp_path):
    """crop은 자르기 뒤에 옵니다. 얼굴 시각도 잘린 뒤의 시각이어야 합니다."""
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    kept = [(0.0, 2.0), (5.0, 7.0)]
    faces = [(1.0, 0.5), (3.0, 0.9), (6.0, 0.5)]  # 3.0초는 잘려 나간 자리입니다
    path = clip_path(source, spec(deadzone=0.0, max_speed=2.0), kept, faces)
    assert [round(at, 2) for at, _ in path] == [1.0, 3.0]  # 6.0초 → 3.0초


def test_the_whole_clip_keeps_the_original_times(tmp_path):
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    faces = [(1.0, 0.5), (3.0, 0.9)]
    path = clip_path(source, spec(deadzone=0.0, max_speed=2.0), [(0.0, 10.0)], faces)
    assert [at for at, _ in path] == [1.0, 3.0]
