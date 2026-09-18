"""Immutable job options; credentials remain in server configuration."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pipeline.editing import Cue, EditSpec


class WorkflowOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    audio_mode: Literal["original", "dub"] = "dub"
    source_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    voice_id: str | None = Field(default=None, max_length=128)
    lipsync: bool = False
    clip: EditSpec | None = None
    transcript: list[Cue] | None = Field(default=None, max_length=5000)
    translated_cues: list[Cue] | None = Field(default=None, max_length=5000)
    budget_usd: Decimal = Field(default=Decimal("0"), ge=0, le=10000, decimal_places=4)

    @model_validator(mode="after")
    def consistent(self):
        if self.audio_mode == "original" and self.lipsync:
            raise ValueError("립싱크는 더빙 작업에만 사용할 수 있습니다.")
        return self
