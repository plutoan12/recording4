import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_analysis_gain import analysis_gain  # noqa: E402


def test_gain_preserves_timing_relative_amplitudes_and_source():
    audio = np.array([0.0, 0.02, -0.01, 0.005])
    original = audio.copy()
    out, evidence = analysis_gain(audio)
    np.testing.assert_array_equal(audio, original)
    np.testing.assert_allclose(out, audio * 10)
    assert len(out) == len(audio)
    assert evidence["gain_db"] == 20
    assert evidence["denoising"] is False


def test_peak_limit_and_no_attenuation():
    out, _ = analysis_gain(np.array([0.3, -0.1]))
    assert np.max(np.abs(out)) == pytest.approx(10 ** (-1 / 20))
    loud = np.array([1.0, -0.99])
    np.testing.assert_array_equal(analysis_gain(loud)[0], loud)
    silent = np.zeros(80)
    np.testing.assert_array_equal(analysis_gain(silent)[0], silent)


@pytest.mark.parametrize("audio", [[], [[0.1]], [np.nan], [np.inf], [1.1]])
def test_invalid_pcm_rejected(audio):
    with pytest.raises(ValueError):
        analysis_gain(audio)


def test_cli_preserves_source_and_records_encoded_peak(tmp_path, monkeypatch):
    import json

    import prepare_analysis_gain as module

    sf = pytest.importorskip("soundfile")
    source, output = tmp_path / "source.wav", tmp_path / "copy.wav"
    sf.write(source, np.array([0, 0.123, -0.12] * 10), 16000, subtype="PCM_16")
    before = source.read_bytes()
    monkeypatch.setattr(sys, "argv", ["gain", "--audio", str(source), "--output", str(output)])
    module.main()
    encoded, rate = sf.read(output)
    metadata = json.loads(output.with_suffix(".gain.json").read_text())
    assert source.read_bytes() == before
    assert len(encoded) == 30 and rate == 16000
    assert metadata["peak_after"] == float(np.max(np.abs(encoded)))
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit):
        module.main()
