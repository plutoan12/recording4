"""영상에서 얼굴을 찾습니다. 어디를 남길지 제안하는 데만 씁니다.

가로 영상을 세로로 자르면 가로의 대부분이 잘려 나갑니다. 지금은 사람이
`focus_x` 손잡이를 눈으로 맞춥니다. 이 모듈은 몇 장을 뽑아 얼굴을 찾고,
`pipeline.framing`이 그것으로 제안값을 만듭니다.

**제안일 뿐입니다.** 자동으로 적용하지 않습니다. 검출기가 틀리면 사람이
맞춘 값을 망치기 때문입니다.

검출기는 OpenCV가 함께 싣는 Haar 캐스케이드입니다. 내려받을 것이 없어서
고른 것이고, **정면 얼굴만** 그럭저럭 찾습니다. 옆얼굴·가린 얼굴·작은
얼굴은 놓칩니다. 더 나은 검출기(YuNet 등)는 모델 파일을 받아야 해서 여기서는
쓰지 않았습니다. 바꿀 자리는 `detect_faces` 하나입니다.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.framing import Box, Suggestion, suggest_focus

# 몇 초에 한 장씩 볼지. 촘촘히 볼수록 느려지고 제안은 크게 달라지지 않습니다.
SAMPLE_SECONDS = 1.0
# 너무 작은 얼굴은 배경의 무늬일 때가 많습니다. 화면 높이 대비 최소 비율입니다.
MIN_FACE_RATIO = 0.06


class MissingDependency(RuntimeError):
    """얼굴 검출에 필요한 것이 없을 때."""


def _cascade():  # noqa: ANN202 - cv2 타입을 여기서 들이지 않습니다.
    try:
        import cv2
    except ImportError as exc:
        raise MissingDependency(
            "OpenCV가 없습니다. pip install '.[analysis]'를 실행하세요."
        ) from exc
    path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not path.is_file():
        raise MissingDependency(f"얼굴 검출기 파일이 없습니다: {path}")
    found = cv2.CascadeClassifier(str(path))
    if found.empty():
        raise MissingDependency(f"얼굴 검출기를 읽지 못했습니다: {path}")
    return found


def sample_times(duration: float, step: float = SAMPLE_SECONDS) -> list[float]:
    """볼 시각들. 처음과 끝은 화면 전환이 걸리기 쉬워 조금 안쪽에서 봅니다."""
    if duration <= 0:
        return []
    inset = min(step / 2, duration / 4)
    times, at = [], inset
    while at < duration - inset:
        times.append(round(at, 3))
        at += step
    return times or [round(duration / 2, 3)]


def detect_faces(source: Path, *, step: float = SAMPLE_SECONDS) -> tuple[list[list[Box]], int]:
    """표본 시각마다 찾은 얼굴들과 영상 가로 크기를 돌려줍니다."""
    import cv2

    cascade = _cascade()
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise MissingDependency(f"영상을 열지 못했습니다: {source}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = count / fps if fps > 0 else 0.0
        frames: list[list[Box]] = []
        for at in sample_times(duration, step):
            capture.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
            ok, frame = capture.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            smallest = max(24, int(height * MIN_FACE_RATIO))
            found = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=6, minSize=(smallest, smallest)
            )
            frames.append([Box(float(x), float(y), float(w), float(h)) for x, y, w, h in found])
    finally:
        capture.release()
    return frames, width


def suggest(source: Path, *, step: float = SAMPLE_SECONDS) -> Suggestion:
    """이 영상에서 `focus_x`를 얼마로 두면 좋을지 제안합니다. 적용하지 않습니다."""
    frames, width = detect_faces(source, step=step)
    if width <= 0:
        raise MissingDependency(f"영상 가로 크기를 읽지 못했습니다: {source}")
    return suggest_focus(frames, width)
