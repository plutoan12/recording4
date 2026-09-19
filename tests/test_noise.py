"""소음·겹말을 얼마나 섞을지 정하는 계산. 전사는 돌리지 않습니다.

이 계산이 틀리면 **재는 조건 자체가 틀립니다.** "SNR 0dB에서 CER 40%"라고
적어 놓고 실제로는 -10dB를 잰 것일 수 있습니다. 그래서 따로 고정합니다.

섞기가 실제로 그 SNR을 만드는지는 FFmpeg로 한 번 확인합니다(아래 마지막).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from pipeline.noise import (
    NOISE_SNRS,
    PARTIAL_SNRS,
    SPEECH_SNRS,
    conditions,
    gain_for_snr,
    partial_window,
    worse,
)


def test_equal_loudness_needs_no_gain_at_zero_snr() -> None:
    """같은 크기 두 소리를 0dB로 섞으면 손댈 것이 없습니다."""
    assert gain_for_snr(-20.0, -20.0, 0.0) == 0.0


def test_a_louder_target_pushes_the_interferer_down() -> None:
    """목소리가 20dB 커야 하면 잡음을 그만큼 내립니다."""
    assert gain_for_snr(-20.0, -20.0, 20.0) == -20.0


def test_a_quiet_interferer_gets_pushed_up() -> None:
    """잡음이 원래 작으면 올려야 목표 SNR이 됩니다."""
    assert gain_for_snr(-20.0, -50.0, 10.0) == pytest.approx(20.0)


def test_a_negative_snr_makes_the_interferer_louder() -> None:
    """잡음이 목소리보다 큰 조건도 만들 수 있어야 합니다."""
    assert gain_for_snr(-20.0, -20.0, -6.0) == 6.0


def test_the_conditions_start_from_the_clean_sample() -> None:
    """원음이 첫 줄이어야 나머지를 견줄 기준이 생깁니다."""
    rows = conditions(with_speech=True)
    assert rows[0].kind == "clean" and rows[0].label == "원음"


def test_overlapping_speech_is_skipped_when_there_is_no_second_voice() -> None:
    """목소리가 없는데 겹말을 재는 척하면 원음을 두 번 재게 됩니다."""
    rows = conditions(with_speech=False)
    assert not [row for row in rows if row.kind == "speech"]
    assert len(rows) == 1 + len(NOISE_SNRS)


def test_every_condition_is_listed_when_a_second_voice_exists() -> None:
    rows = conditions(with_speech=True)
    assert len(rows) == 1 + len(NOISE_SNRS) + len(SPEECH_SNRS) + len(PARTIAL_SNRS)
    assert [row.name for row in rows].count("clean") == 1
    # 이름이 겹치면 만든 파일을 서로 덮어씁니다.
    assert len({row.name for row in rows}) == len(rows)


def test_the_label_says_which_kind_and_how_loud() -> None:
    rows = {row.name: row.label for row in conditions(with_speech=True)}
    assert rows["noise0"] == "소음 SNR +0dB"
    assert rows["speech5"] == "겹말 SNR +5dB"


def test_getting_worse_is_measured_in_points_not_ratio() -> None:
    """원음이 0%에 가까우면 비율은 무한대로 튑니다."""
    assert worse(0.10, 0.35) == pytest.approx(0.25)
    assert worse(0.0, 0.40) == pytest.approx(0.40)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg 없음")
def test_the_mix_really_lands_on_the_requested_snr() -> None:
    """계산이 맞아도 섞기가 틀리면 소용없습니다. 실제로 섞어서 다시 잽니다."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from verify_robust import loudness, mixed

    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        speech, noise = work / "a.wav", work / "b.wav"
        for path, source in (
            (speech, "sine=frequency=300:duration=3:sample_rate=16000"),
            (noise, "anoisesrc=color=pink:duration=3:sample_rate=16000"),
        ):
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", source,
                 "-ac", "1", "-c:a", "pcm_s16le", str(path)],
                check=True, timeout=120,
            )  # fmt: skip

        loud_speech, loud_noise = loudness(speech), loudness(noise)
        # 잡음만 목표 크기로 줄여서 정말 그 크기가 되는지 봅니다. 섞은 소리로
        # 재면 두 소리가 더해져 SNR을 직접 읽을 수 없습니다.
        gain = gain_for_snr(loud_speech, loud_noise, 10.0)
        quieter = work / "q.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(noise),
             "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", str(quieter)],
            check=True, timeout=120,
        )  # fmt: skip
        assert loudness(quieter) == pytest.approx(loud_speech - 10.0, abs=0.5)

        # 섞은 소리는 목소리보다 커지되 크게 달라지지 않아야 합니다
        # (normalize=0이라 대상 음량이 그대로입니다).
        together = mixed(speech, noise, gain, work / "m.wav")
        assert loud_speech <= loudness(together) <= loud_speech + 1.5


def test_the_limits_come_from_a_real_measurement() -> None:
    """지어낸 선은 통과하는 것 말고 아무 뜻이 없습니다. 실측에서 옵니다.

    아직 안 잰 조건은 여기 이름을 적어 둡니다. 그 조건은 상한이 없어야 하고
    (보고만 함), 잰 뒤에는 이 목록에서 빼고 MEASURED_CER에 넣어야 합니다.
    """
    from pipeline.noise import HEADROOM, MEASURED_CER, limit_for

    not_measured_yet = {"partial0"}
    for row in conditions(with_speech=True):
        if row.name in not_measured_yet:
            assert limit_for(row.name) is None, f"{row.name}은 잰 적 없는데 상한이 있습니다."
            continue
        assert row.name in MEASURED_CER, f"{row.name}을 재지 않았습니다."
        assert limit_for(row.name) == pytest.approx(MEASURED_CER[row.name] + HEADROOM)


def test_the_partial_window_sits_in_the_middle_and_leaves_both_sides() -> None:
    """앞뒤가 남아야 화자별 전사가 무엇을 살리는지 보입니다."""
    begin, end = partial_window(30.0)
    assert begin == pytest.approx(10.0) and end == pytest.approx(20.0)
    assert begin > 0 and end < 30.0


def test_an_unmeasured_condition_gets_no_invented_limit() -> None:
    from pipeline.noise import limit_for

    assert limit_for("noise99") is None


def test_the_limits_get_harder_as_the_condition_gets_harder() -> None:
    """쉬운 조건의 상한이 어려운 조건보다 높으면 순서가 뒤집힌 것입니다."""
    from pipeline.noise import MEASURED_CER

    order = ["clean", "noise20", "noise10", "noise5", "noise0", "speech10", "speech5", "speech0"]
    values = [MEASURED_CER[name] for name in order]
    assert values == sorted(values)
