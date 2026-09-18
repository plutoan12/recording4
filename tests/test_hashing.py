"""입력 해시 테스트. 설정이 바뀌면 해시가 달라져야 재사용되지 않습니다."""

from __future__ import annotations

import pytest

from pipeline.hashing import StageInputs, compute_input_hash


def base(**overrides) -> StageInputs:  # noqa: ANN003
    defaults = dict(
        stage="dub",
        input_checksums=("sha256:aaa",),
        provider="elevenlabs",
        model_id="model-x",
        model_version="2026-01-01",
        voice_id="voice-1",
        language="en",
        parameters={"speed": 1.0},
        prompt_template_version="p1",
        glossary_version="g1",
    )
    defaults.update(overrides)
    return StageInputs(**defaults)


def test_same_inputs_produce_same_hash() -> None:
    assert base().digest() == base().digest()


def test_checksum_order_does_not_change_hash() -> None:
    a = base(input_checksums=("sha256:a", "sha256:b"))
    b = base(input_checksums=("sha256:b", "sha256:a"))
    assert a.digest() == b.digest()


@pytest.mark.parametrize(
    "field",
    [
        "provider",
        "model_id",
        "model_version",
        "voice_id",
        "language",
        "prompt_template_version",
        "glossary_version",
    ],
)
def test_changing_any_identity_field_changes_hash(field: str) -> None:
    """공급자·모델·음성·프롬프트·용어집 중 하나만 바뀌어도 다른 실행입니다."""
    assert base().digest() != base(**{field: "changed"}).digest()


def test_changing_parameters_changes_hash() -> None:
    assert base().digest() != base(parameters={"speed": 1.05}).digest()


def test_changing_contract_version_changes_hash() -> None:
    assert base().digest() != base(contract_version=99).digest()


def test_changing_input_checksum_changes_hash() -> None:
    assert base().digest() != base(input_checksums=("sha256:other",)).digest()


def test_paid_stage_without_model_version_is_not_reusable() -> None:
    """모델 버전을 공개하지 않는 공급자는 재사용 대상에서 제외합니다."""
    inputs = base(model_version=None)
    assert inputs.is_paid
    assert not inputs.reusable
    assert inputs.digest()  # 해시는 계산됩니다.


def test_local_stage_without_provider_is_reusable() -> None:
    inputs = StageInputs(stage="mux", input_checksums=("sha256:a",))
    assert not inputs.is_paid
    assert inputs.reusable


def test_unserializable_parameter_is_rejected() -> None:
    with pytest.raises(TypeError):
        compute_input_hash(base(parameters={"when": object()}))
