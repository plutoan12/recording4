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
# 위 겹말은 처음부터 끝까지 겹친 최악의 경우입니다. 실제 겹말은 잠깐입니다.
# 부분 겹말은 가운데 이 비율만큼만 끼어듭니다. 겹치지 않은 앞뒤가 있어야
# 화자별 전사가 무엇을 살리는지 보입니다.
PARTIAL_FRACTION = 1.0 / 3.0
PARTIAL_SNRS = (0.0,)


@dataclass(frozen=True)
class Condition:
    """재는 조건 하나."""

    name: str
    kind: str  # "clean" | "noise" | "speech" | "partial"
    snr_db: float | None = None

    @property
    def label(self) -> str:
        if self.kind == "clean":
            return "원음"
        what = {"noise": "소음", "speech": "겹말", "partial": "부분 겹말"}[self.kind]
        return f"{what} SNR {self.snr_db:+.0f}dB"

    @property
    def has_other_voice(self) -> bool:
        return self.kind in ("speech", "partial")


def conditions(*, with_speech: bool) -> list[Condition]:
    """재는 조건들. 겹말은 끼어들 목소리가 있을 때만 넣습니다.

    없는데 넣으면 조용히 원음을 두 번 재고 "겹말도 괜찮다"고 말하게 됩니다.
    """
    rows = [Condition("clean", "clean")]
    rows += [Condition(f"noise{snr:g}", "noise", snr) for snr in NOISE_SNRS]
    if with_speech:
        rows += [Condition(f"speech{snr:g}", "speech", snr) for snr in SPEECH_SNRS]
        rows += [Condition(f"partial{snr:g}", "partial", snr) for snr in PARTIAL_SNRS]
    return rows


def partial_window(seconds: float, fraction: float = PARTIAL_FRACTION) -> tuple[float, float]:
    """부분 겹말이 끼어드는 시각. 가운데에 둡니다. 앞뒤가 남아야 합니다."""
    length = seconds * fraction
    start = (seconds - length) / 2
    return (round(start, 3), round(start + length, 3))


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


# 2026-09-19 CI 실측(whisper small, zeroth-korean 낭독 3문장). **품질 목표가
# 아니라 회귀 감시용**입니다. 조건마다 값이 크게 달라 하나의 상한으로는 재지
# 못합니다. 겹말 0dB의 116%는 원문보다 많은 글자를 뱉었다는 뜻입니다. 끼어든
# 사람의 말을 받아쓰고 있습니다.
#
# **소음 값은 씨앗을 고정하기 전에 잰 것입니다.** 같은 코드에서 두 번 돌렸더니
# 소음 0dB가 23.1% → 20.9%, 5dB가 17.2% → 14.2%로 움직였습니다. 잡음이 매번
# 달랐기 때문입니다. 지금은 씨앗을 박아 두었으니(verify_robust.NOISE_SEED) 첫
# 고정 실행의 값으로 이 표를 갱신해야 합니다. 겹말 값은 파일이 고정이라 두 번
# 모두 같았습니다(29.1 / 92.5 / 116.4).
MEASURED_CER = {
    "clean": 0.104,
    "noise20": 0.112,
    "noise10": 0.127,
    "noise5": 0.172,
    "noise0": 0.231,
    "speech10": 0.291,
    "speech5": 0.925,
    "speech0": 1.164,
}
# 실측에 얹는 여유(백분율 포인트). 표본이 세 문장뿐이라 데이터셋 행이 바뀌면
# 값이 움직입니다. 비율로 곱하면 무너진 조건에서 상한이 무의미해집니다
# (116%의 두 배는 232%입니다). 모델이나 언어 설정이 어긋나는 수준의 회귀는
# 이 선을 훌쩍 넘습니다.
HEADROOM = 0.10


def limit_for(name: str) -> float | None:
    """이 조건의 회귀 감시 상한. 잰 적 없는 조건은 None입니다.

    재 보지 않은 조건에 상한을 지어내지 않습니다.
    """
    measured = MEASURED_CER.get(name)
    return None if measured is None else measured + HEADROOM
