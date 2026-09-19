"""소음·겹말을 얼마나 섞을지 정하는 계산. 오디오를 만지지 않습니다.

섞는 일은 FFmpeg가 하고, **얼마나 섞을지**는 여기서 정합니다. 나눠 두는 이유는
이 계산이 틀리면 재는 조건 자체가 틀리는데, FFmpeg를 돌리는 코드 안에 있으면
확인할 수가 없기 때문입니다.

SNR(신호 대 잡음비)은 **목소리가 잡음보다 몇 dB 큰가**입니다. 20dB면 잡음이
멀리 있고, 0dB면 목소리와 잡음이 같은 크기입니다. 음수면 잡음이 더 큽니다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 재는 조건. 값이 작아질수록 어렵습니다. 0dB는 잡음이 목소리와 같은 크기입니다.
NOISE_SNRS = (20.0, 10.0, 5.0, 0.0)
# 겹말은 끼어든 목소리가 대상보다 얼마나 작은지로 잡습니다. 0dB면 같은 크기라
# 사람도 알아듣기 어렵습니다.
SPEECH_SNRS = (10.0, 5.0, 0.0)


@dataclass(frozen=True)
class Condition:
    """재는 조건 하나."""

    name: str
    kind: str  # "clean" | "noise" | "speech"
    snr_db: float | None = None

    @property
    def label(self) -> str:
        if self.kind == "clean":
            return "원음"
        what = "소음" if self.kind == "noise" else "겹말"
        return f"{what} SNR {self.snr_db:+.0f}dB"


def conditions(*, with_speech: bool) -> list[Condition]:
    """재는 조건들. 겹말은 끼어들 목소리가 있을 때만 넣습니다.

    없는데 넣으면 조용히 원음을 두 번 재고 "겹말도 괜찮다"고 말하게 됩니다.
    """
    rows = [Condition("clean", "clean")]
    rows += [Condition(f"noise{snr:g}", "noise", snr) for snr in NOISE_SNRS]
    if with_speech:
        rows += [Condition(f"speech{snr:g}", "speech", snr) for snr in SPEECH_SNRS]
    return rows


def gain_for_snr(target_dbfs: float, other_dbfs: float, snr_db: float) -> float:
    """끼어드는 소리에 걸 이득(dB). 목표 SNR이 나오도록 맞춥니다.

    둘 다 같은 자로 잰 평균 음량(dBFS)이어야 합니다. 한쪽만 최댓값으로 재면
    조건이 틀어집니다.
    """
    return target_dbfs - other_dbfs - snr_db


def worse(baseline: float, measured: float) -> float:
    """원음 대비 얼마나 더 틀렸는지. 백분율 포인트입니다.

    비율로 나누지 않습니다. 원음이 0%에 가까우면 나눗셈이 무한대로 튑니다.
    """
    return measured - baseline
