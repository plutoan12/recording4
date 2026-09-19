from copy import deepcopy

import pytest

from pipeline.style_review import style_warnings


@pytest.mark.parametrize(
    "language,texts",
    [
        ("ko", ["준비했습니다.", "아직 진행 중이었다."]),
        ("ko", ["준비했습니다.", "확인해요."]),
        ("ja", ["準備しました。", "まだ続いていた。"]),
        ("en", ["You shall save it.", "I'm gonna wait."]),
        ("zh", ["请保存。", "这是啥？"]),
    ],
)
def test_mixed_register_is_only_a_hint(language, texts):
    rows = [{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]
    before = deepcopy(rows)
    warnings = style_warnings(rows, language)
    assert warnings[0]["kind"] == "mixed_register"
    assert warnings[0]["registers"][0]["cue_numbers"] == [1]
    assert warnings[0]["registers"][1]["cue_numbers"] == [2]
    assert rows == before


@pytest.mark.parametrize(
    "language,texts",
    [
        ("ko", ["준비했습니다.", "아직 진행 중입니다."]),
        ("ja", ["準備しました。", "まだ続いています。"]),
        ("ko", ['"녹화가 멈췄다."라고 말했습니다.', "준비했습니다."]),
        ("ja", ["「録画が止まった。」と言いました。", "準備しました。"]),
        ("en", ["Don't turn off the power.", "Please wait."]),
        (None, ["준비했습니다.", "녹화 중이었다."]),
    ],
)
def test_no_unjustified_warning(language, texts):
    assert style_warnings([{"text": t} for t in texts], language) == []
