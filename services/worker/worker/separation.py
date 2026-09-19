"""원본 음성에서 배경음만 남깁니다. 더빙이 음악까지 지우지 않게 하려는 것입니다.

지금 더빙은 원본 오디오를 **통째로** 새 음성으로 바꿉니다(`compose_dub`). 말은
바뀌지만 배경 음악과 효과음도 같이 사라집니다. 원본이 음악 위에서 말하는
영상이면 더빙본은 말만 남은 이상한 영상이 됩니다.

여기서는 원본을 목소리와 나머지로 나누고 **나머지만** 돌려줍니다. 그 나머지를
더빙 음성 아래에 깔면 음악이 남습니다.

모델은 torchaudio가 함께 싣는 Hybrid Demucs(`HDEMUCS_HIGH_MUSDB_PLUS`)입니다.
별도 패키지를 더 넣지 않으려고 고른 것입니다. PyPI의 `demucs` 4.0.1은
`torchaudio<2.1`을 요구하는데 이 이미지는 2.8이라 함께 설치되지 않습니다.

**완전히 지워지지 않습니다.** 분리는 근사이고 목소리 흔적이 배경에 남습니다.
얼마나 남는지는 `scripts/verify_separation.py`가 잽니다. 수치를 보지 않고
"배경음을 보존한다"고 말하지 마세요.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 한 번에 넣는 길이(초). 길면 메모리를 많이 쓰고 짧으면 경계가 늘어납니다.
CHUNK_SECONDS = 10.0
# 이어 붙일 때 겹치는 길이(초). 경계에서 소리가 튀지 않게 합니다.
OVERLAP_SECONDS = 0.1


class MissingDependency(RuntimeError):
    """분리에 필요한 것이 없을 때. 사람이 읽을 말로 바꿔서 올립니다."""


@dataclass(frozen=True, slots=True)
class Separated:
    """분리 결과. 파일과 그 파일이 무엇인지 함께 둡니다."""

    background: Path
    sample_rate: int
    seconds: float


def _pipeline():  # noqa: ANN202 - torchaudio 타입을 여기서 들이지 않습니다.
    """이 torchaudio가 싣고 있는 분리 모델. 없으면 왜 없는지 말합니다."""
    try:
        import torchaudio
    except ImportError as exc:  # pragma: no cover - 워커 이미지에는 있습니다.
        raise MissingDependency(
            "torchaudio가 없습니다. 배경음 분리는 워커 이미지 안에서만 돕니다."
        ) from exc
    bundle = getattr(getattr(torchaudio, "pipelines", None), "HDEMUCS_HIGH_MUSDB_PLUS", None)
    if bundle is None:
        # torchaudio가 이 번들을 뺀 버전일 수 있습니다. 조용히 넘어가면 배경음이
        # 없는 결과가 성공처럼 나갑니다.
        raise MissingDependency(
            f"이 torchaudio({getattr(__import__('torchaudio'), '__version__', '?')})에는 "
            "HDEMUCS_HIGH_MUSDB_PLUS가 없습니다. 배경음 분리를 쓰려면 이 번들이 있는 "
            "버전으로 맞추거나 다른 분리 모델을 붙여야 합니다."
        )
    return bundle


def chunk_bounds(total: int, rate: int) -> list[tuple[int, int]]:
    """한 번에 처리할 구간들. 앞뒤가 조금씩 겹칩니다.

    통째로 넣으면 3분짜리에서 메모리가 몇 GB로 뜁니다. 겹치지 않고 자르면
    경계마다 소리가 끊깁니다. 그래서 겹쳐 자르고 겹친 곳을 섞습니다.
    """
    step = max(1, int(CHUNK_SECONDS * rate))
    overlap = max(0, int(OVERLAP_SECONDS * rate))
    if total <= step:
        return [(0, total)]
    bounds: list[tuple[int, int]] = []
    start = 0
    while start < total:
        end = min(total, start + step)
        bounds.append((start, end))
        if end >= total:
            break
        start = end - overlap
    return bounds


def background_sources(names: list[str]) -> list[int]:
    """목소리가 아닌 갈래의 번호. 이 갈래들을 더해서 배경음을 만듭니다."""
    found = [index for index, name in enumerate(names) if name != "vocals"]
    if not found:
        raise MissingDependency(f"분리 결과에 목소리 말고는 없습니다: {names}")
    return found


def separate_background(source: Path, output: Path, *, device: str = "cpu") -> Separated:
    """원본에서 목소리를 빼고 나머지를 `output`(WAV)에 씁니다.

    느립니다. CPU에서 1분짜리 소리를 나누는 데 수십 초가 걸립니다. 그래서
    설정으로 켜야만 돕니다(`R4_BACKGROUND_AUDIO_ENABLED`).
    """
    import torch
    import torchaudio

    bundle = _pipeline()
    model = bundle.get_model().to(device).eval()
    wave, rate = torchaudio.load(str(source))
    if rate != bundle.sample_rate:
        wave = torchaudio.functional.resample(wave, rate, bundle.sample_rate)
        rate = bundle.sample_rate
    # 모델은 스테레오를 받습니다. 모노면 같은 소리를 두 갈래로 놓습니다.
    if wave.shape[0] == 1:
        wave = wave.repeat(2, 1)
    elif wave.shape[0] > 2:
        wave = wave[:2]

    keep = background_sources(list(model.sources))
    mixed = torch.zeros_like(wave)
    counts = torch.zeros(wave.shape[1])
    with torch.no_grad():
        for start, end in chunk_bounds(wave.shape[1], rate):
            piece = wave[:, start:end].to(device)
            # 모델은 (묶음, 갈래, 소리)로 돌려줍니다. 목소리만 빼고 더합니다.
            found = model(piece.unsqueeze(0))[0]
            part = sum(found[index] for index in keep).cpu()
            mixed[:, start:end] += part
            counts[start:end] += 1
    # 겹친 구간은 두 번 더해졌습니다. 더해진 횟수로 나눕니다.
    mixed = mixed / counts.clamp(min=1)

    output.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(output), mixed, rate)
    return Separated(background=output, sample_rate=rate, seconds=wave.shape[1] / rate)
