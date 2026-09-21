"""자동 리프레이밍. 세로로 자를 때 말하는 사람을 따라갑니다.

16:9를 9:16으로 자르면 가로의 절반 넘게 버립니다. 지금까지는 어디를 남길지
`EditSpec.focus_x`에 **고정 숫자 하나**로 정했습니다(기본 0.5, 가운데). 인물이
움직이면 화면 밖으로 나가도 그대로였습니다.

여기서는 얼굴 위치(`worker.analysis.face_track`, MediaPipe)를 받아 **시간에
따라 변하는 중심**을 만들고, FFmpeg `crop`의 x를 그 식으로 바꿉니다.

## 왜 그냥 따라가면 안 되는가

검출 결과를 그대로 따라가면 **화면이 덜덜 떨립니다.** 얼굴 상자는 프레임마다
몇 픽셀씩 흔들리고, 검출이 한 프레임 실패하면 중심이 튑니다. 그래서:

- `deadzone`보다 작게 움직이면 **가만히 둡니다.** 말하는 사람이 고개만 까딱할
  때 화면이 따라 흔들리지 않습니다.
- 움직일 때는 `max_speed`(초당 화면 폭 비율)를 넘지 않게 끌고 갑니다. 컷처럼
  튀지 않고 카메라가 천천히 따라가는 모양이 됩니다.
- 검출이 없는 구간은 **마지막 위치를 유지합니다.** 가운데로 되돌리면 그때마다
  화면이 크게 움직입니다.

## 아는 한계

- 사람이 여럿이면 **가장 큰 얼굴**만 따라갑니다. 말하는 사람을 고르는 것이
  아닙니다(누가 말하는지는 여기서 알 수 없습니다).
- 세로(y)는 건드리지 않습니다. 16:9 → 9:16에서는 세로가 거의 그대로라 얻는
  것이 적고, 위아래로 흔들리면 더 눈에 띕니다.
- `mode="crop"`에서만 씁니다. `pad`는 화면 전체를 남기므로 자를 것이 없습니다.
"""

from __future__ import annotations

from collections.abc import Sequence

from pipeline.editing import ReframeSettings

# 만들 최대 꼭짓점 수. FFmpeg 식이 끝없이 길어지지 않게 합니다.
MAX_KEYS = 40
# 꼭짓점을 찍는 가장 짧은 간격(초). 이보다 촘촘해도 사람 눈에는 같습니다.
MIN_STEP = 0.2

Point = tuple[float, float]


def follow(track: Sequence[Point], *, settings: ReframeSettings | None = None) -> list[Point]:
    """검출 위치를 따라가되 떨지 않는 중심 경로. (시각, 0~1 가로 위치)입니다.

    비어 있으면 빈 목록입니다. 부르는 쪽은 그때 `focus_x`를 그대로 씁니다.
    """
    settings = settings or ReframeSettings()
    if not track:
        return []
    ordered = sorted(track)
    current = ordered[0][1]
    path: list[Point] = [(ordered[0][0], current)]
    for at, (moment, wanted) in enumerate(ordered[1:], start=1):
        gap = moment - ordered[at - 1][0]
        if abs(wanted - current) > settings.deadzone:
            # 한 번에 끌고 갈 수 있는 거리까지만 움직입니다.
            reach = settings.max_speed * max(gap, 0.0)
            step = max(-reach, min(reach, wanted - current))
            current = min(1.0, max(0.0, current + step))
        path.append((moment, current))
    return path


def keyframes(
    path: Sequence[Point], *, limit: int = MAX_KEYS, step: float = MIN_STEP
) -> list[Point]:
    """식에 넣을 꼭짓점만 남깁니다. 너무 촘촘하거나 많으면 솎아 냅니다."""
    if not path:
        return []
    thinned: list[Point] = [path[0]]
    for moment, value in path[1:]:
        if moment - thinned[-1][0] >= step:
            thinned.append((moment, value))
    if thinned[-1] != path[-1]:
        thinned.append(path[-1])
    while len(thinned) > limit:
        # 가운데를 하나 걸러 버립니다. 처음과 끝은 남깁니다.
        thinned = [thinned[0], *thinned[1:-1:2], thinned[-1]]
    return thinned


def center_expression(path: Sequence[Point]) -> str:
    """0~1 가로 위치를 시간의 식으로. 구간마다 직선으로 잇습니다.

    구간을 `gte(t,a)*lt(t,b)`로 나눕니다. `between()`은 양끝을 모두 포함해서
    경계에서 두 구간이 함께 더해집니다(그 한 프레임만 값이 튑니다).
    """
    keys = keyframes(path)
    if not keys:
        return ""
    if len(keys) == 1:
        return f"{keys[0][1]:.4f}"
    parts: list[str] = []
    for at, ((start, low), (end, high)) in enumerate(zip(keys, keys[1:], strict=False)):
        span = end - start
        moving = (
            f"{low:.4f}"
            if span <= 0
            else f"({low:.4f}+({high - low:.4f})*(t-{start:.3f})/{span:.3f})"
        )
        last = at == len(keys) - 2
        window = f"gte(t,{start:.3f})" if last else f"gte(t,{start:.3f})*lt(t,{end:.3f})"
        parts.append(f"{window}*{moving}")
    # 첫 꼭짓점 앞은 첫 값으로 붙잡아 둡니다.
    parts.insert(0, f"lt(t,{keys[0][0]:.3f})*{keys[0][1]:.4f}")
    return "+".join(parts)


def crop_x(path: Sequence[Point], fallback: float) -> str:
    """FFmpeg `crop`의 x 인자. 화면 밖으로 나가지 않게 가둡니다.

    경로가 비어 있으면 지금까지 쓰던 고정 위치(`focus_x`) 그대로입니다.
    """
    center = center_expression(path) or f"{fallback:.4f}"
    return f"clip(({center})*iw-ow/2,0,iw-ow)"
