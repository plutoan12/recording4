"""재실행 판정에 쓰는 입력 해시.

docs/ARCHITECTURE.md "재실행 판정"을 구현합니다. 해시가 같고 상태가 succeeded인
단계 실행이 있으면 산출물을 재사용하고 유료 호출을 하지 않습니다.

공급자가 모델 버전을 공개하지 않으면(model_version이 None) 그 실행은 재사용
대상에서 제외합니다. 해시는 계산하되 reusable이 False가 되고, 재사용 판정은
이 값을 함께 확인해야 합니다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

CONTRACT_VERSION = 1
"""단계 로직의 계약 버전. 단계 구현의 입출력 의미가 바뀌면 올립니다."""


@dataclass(frozen=True, slots=True)
class StageInputs:
    """한 단계 실행의 입력 전부."""

    stage: str
    input_checksums: tuple[str, ...] = ()
    provider: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    voice_id: str | None = None
    language: str | None = None
    parameters: dict[str, object] = field(default_factory=dict)
    prompt_template_version: str | None = None
    glossary_version: str | None = None
    contract_version: int = CONTRACT_VERSION

    @property
    def is_paid(self) -> bool:
        """외부 공급자를 호출하는 단계인지."""
        return self.provider is not None

    @property
    def reusable(self) -> bool:
        """산출물 재사용이 허용되는지.

        유료 공급자 단계인데 모델 버전을 알 수 없으면 재사용하지 않습니다.
        같은 모델 ID라도 내용이 바뀌었을 수 있기 때문입니다.
        """
        return not self.is_paid or self.model_version is not None

    def canonical(self) -> dict[str, object]:
        """해시 대상이 되는 표준 형태. 키 순서와 체크섬 순서를 고정합니다."""
        return {
            "stage": self.stage,
            "input_checksums": sorted(self.input_checksums),
            "provider": self.provider,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "voice_id": self.voice_id,
            "language": self.language,
            "parameters": self.parameters,
            "prompt_template_version": self.prompt_template_version,
            "glossary_version": self.glossary_version,
            "contract_version": self.contract_version,
        }

    def digest(self) -> str:
        return compute_input_hash(self)


def compute_input_hash(inputs: StageInputs) -> str:
    """입력 해시를 16진수 문자열로 계산합니다.

    JSON 직렬화는 키를 정렬하고 공백을 없애 표현 차이가 해시를 바꾸지 않게 합니다.
    """
    payload = json.dumps(
        inputs.canonical(),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_unsupported,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unsupported(value: object) -> str:
    raise TypeError(f"입력 해시에 담을 수 없는 값입니다: {type(value).__name__}")
