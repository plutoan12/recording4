"""자동 리프레이밍. 떨지 않는 경로와 FFmpeg crop 식."""

from __future__ import annotations

import pytest

from pipeline.editing import EditSpec, ReframeSettings, TimeSpan
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


def test_reframing_is_off_for_padded_output():
    """`pad`는 화면 전체를 남기므로 따라갈 것이 없습니다."""
    padded = EditSpec(start=10, end=20, mode="pad", reframe=ReframeSettings())
    assert clip_path(padded, [(0.0, 0.8)]) == []


def test_reframing_is_off_without_settings():
    assert clip_path(EditSpec(start=10, end=20), [(0.0, 0.8)]) == []


def test_no_faces_means_no_path_to_follow():
    assert clip_path(spec(), None) == []
    assert clip_path(spec(), []) == []


def test_face_times_move_onto_the_joined_timeline():
    """crop은 이어 붙이기 뒤에 옵니다. 얼굴 시각도 그 뒤의 시각이어야 합니다."""
    chosen = EditSpec(
        start=0,
        end=10,
        mode="crop",
        reframe=ReframeSettings(deadzone=0.0, max_speed=2.0),
        segments=[TimeSpan(start=0.0, end=2.0), TimeSpan(start=5.0, end=7.0)],
    )
    # 3.0초는 빠진 자리입니다. 6.0초는 두 번째 구간의 1.0초 → 결과 3.0초입니다.
    path = clip_path(chosen, [(1.0, 0.5), (3.0, 0.9), (6.0, 0.5)])
    assert [round(at, 2) for at, _ in path] == [1.0, 3.0]


def test_speed_pulls_the_face_times_in():
    """배속을 걸면 얼굴 시각도 그만큼 당겨집니다."""
    chosen = EditSpec(
        start=0,
        end=10,
        mode="crop",
        reframe=ReframeSettings(deadzone=0.0, max_speed=2.0),
        segments=[TimeSpan(start=0.0, end=4.0, speed=2.0)],
    )
    assert [round(at, 2) for at, _ in clip_path(chosen, [(2.0, 0.5)])] == [1.0]


def test_the_whole_clip_keeps_the_original_times():
    chosen = spec(deadzone=0.0, max_speed=2.0)
    path = clip_path(chosen, [(11.0, 0.5), (13.0, 0.9)])
    # 구간을 고르지 않았으면 start~end 하나이고, 시각은 그 시작 기준입니다.
    assert [round(at, 2) for at, _ in path] == [1.0, 3.0]


def test_no_usable_detector_says_so_instead_of_reporting_zero_faces(monkeypatch, tmp_path):
    """검출기가 없으면 "얼굴 0개"가 아니라 "검출기 없음"이어야 합니다.

    `scenedetect`가 끌고 오는 opencv-headless 에는 haarcascade XML 이 없고,
    그때 `CascadeClassifier` 는 예외 없이 빈 분류기가 됩니다. 걸러 내지 않으면
    "얼굴이 화면에 없다"와 구별되지 않습니다.
    """
    from worker import analysis

    monkeypatch.setattr(analysis, "face_model", lambda: None)
    monkeypatch.setattr(analysis, "_opencv_detector", lambda: None)
    assert analysis._open_face_detector() == (None, "none")
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    assert analysis.face_track(source) == ([], "none")


def test_the_mediapipe_model_is_only_used_when_the_file_is_there(monkeypatch, tmp_path):
    """MediaPipe 1.0 에는 모델이 들어 있지 않습니다. 파일이 있어야 씁니다."""
    from worker import analysis

    monkeypatch.delenv("R4_FACE_MODEL", raising=False)
    assert analysis.face_model() is None
    missing = tmp_path / "없는파일.tflite"
    monkeypatch.setenv("R4_FACE_MODEL", str(missing))
    assert analysis.face_model() is None
    present = tmp_path / "model.tflite"
    present.write_bytes(b"not a real model")
    monkeypatch.setenv("R4_FACE_MODEL", str(present))
    assert analysis.face_model() == present
    # 진짜 모델이 아니므로 MediaPipe 가 열지 못하고 조용히 내려갑니다.
    assert analysis._mediapipe_detector(present) is None


def test_a_worker_without_opencv_falls_back_instead_of_failing_the_render(monkeypatch, tmp_path):
    """`[analysis]` 없는 워커에서 리프레이밍만 못 할 뿐 렌더는 끝까지 갑니다.

    리프레이밍은 곁다리입니다. 의존성이 없다고 예외를 던지면 자막·크기까지
    같이 못 만들게 됩니다. 검출기가 없을 때와 같은 자리로 돌아갑니다.
    """
    import builtins

    from worker import analysis

    real = builtins.__import__

    def blocked(name, *args, **kwargs):  # noqa: ANN001, ANN202
        if name.split(".")[0] in {"cv2", "mediapipe"}:
            raise ImportError(name)
        return real(name, *args, **kwargs)

    monkeypatch.delenv("R4_FACE_MODEL", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)
    source = tmp_path / "a.mp4"
    source.write_bytes(b"x")
    assert analysis.face_track(source) == ([], "none")
