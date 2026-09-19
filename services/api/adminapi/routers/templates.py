"""Authenticated template catalogue and side-effect-free ASS sample preview."""

from types import SimpleNamespace

from fastapi import APIRouter
from pydantic import BaseModel, Field

from adminapi.deps import CurrentUser
from pipeline.editing import Cue, SubtitleTemplate
from pipeline.subtitle_templates import TEMPLATES, build_ass

router = APIRouter(prefix="/subtitle-templates", tags=["subtitle-templates"])


class PreviewRequest(BaseModel):
    template: SubtitleTemplate = "classic"
    font_size: int = Field(default=64, ge=20, le=120)


@router.get("")
def catalogue(user: CurrentUser):
    return TEMPLATES


@router.post("/preview")
def preview(payload: PreviewRequest, user: CurrentUser):
    spec = SimpleNamespace(
        width=1080,
        height=1920,
        start=0,
        end=6,
        title="",
        font_size=payload.font_size,
        subtitle_template=payload.template,
        cues=[
            Cue(
                start=0,
                end=3,
                text="안녕하세요. 자막을 골라 보세요.",
                speaker="A",
                original_text="Hello. Choose a caption style.",
            ),
            Cue(
                start=3,
                end=6,
                text="원래 음성은 그대로 유지합니다.",
                speaker="B",
                original_text="The original audio stays unchanged.",
            ),
        ],
    )
    return {"ass": build_ass(spec), "duration": 6, "width": 1080, "height": 1920}
