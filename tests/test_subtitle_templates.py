import pysubs2
import pytest

from pipeline.editing import Cue, EditSpec, clip_cues
from pipeline.subtitle_templates import TEMPLATES, build_ass
from pipeline.subtitles import SubtitleRules, apply_rules


def spec(template, cues=None):
    return EditSpec(
        start=0,
        end=6,
        subtitle_template=template,
        cues=cues
        or [
            Cue(start=0, end=3, text="안녕하세요", speaker="A", original_text="Hello"),
            Cue(start=3, end=6, text="반갑습니다", speaker="B", original_text="Welcome"),
        ],
    )


@pytest.mark.parametrize("template", [t["id"] for t in TEMPLATES])
def test_templates_are_valid_ass_and_keep_timing(template):
    subs = pysubs2.SSAFile.from_string(build_ass(spec(template)))
    translated = [e for e in subs if e.style != "Original"]
    assert [(e.start, e.end) for e in translated] == [(0, 3000), (3000, 6000)]
    assert translated[0].plaintext == "안녕하세요"
    if template == "box":
        assert subs.styles["Default"].borderstyle == 3
    if template == "shorts":
        assert r"\fad" in translated[0].text
    if template == "speaker":
        assert (
            subs.styles[translated[0].style].primarycolor
            != subs.styles[translated[1].style].primarycolor
        )
    if template == "bilingual":
        assert [e.plaintext for e in subs if e.style == "Original"] == ["Hello", "Welcome"]


def test_metadata_survives_clipping_and_caption_splitting():
    cue = Cue(
        start=0,
        end=12,
        text="one two three four five six seven eight",
        speaker="A",
        original_text="원문",
    )
    clipped = clip_cues([cue], 2, 10)
    split = apply_rules(clipped, SubtitleRules(max_chars_per_line=6, max_lines=1))
    assert len(split) > 1
    assert all(c.speaker == "A" and c.original_text == "원문" for c in split)


def test_user_text_cannot_inject_ass_overrides():
    ass = build_ass(spec("shorts", [Cue(start=0, end=3, text=r"{\pos(0,0)}test")]))
    assert r"{\pos(0,0)}" not in ass
    assert "｛＼pos(0,0)｝test" in ass


def test_template_api_requires_auth_and_validates_names(client, auth_headers):
    assert client.get("/subtitle-templates").status_code == 401
    assert client.post("/subtitle-templates/preview", json={}).status_code == 401
    assert len(client.get("/subtitle-templates", headers=auth_headers).json()) == 5
    assert (
        client.post(
            "/subtitle-templates/preview", headers=auth_headers, json={"template": "unknown"}
        ).status_code
        == 422
    )
    result = client.post(
        "/subtitle-templates/preview", headers=auth_headers, json={"template": "bilingual"}
    )
    assert result.status_code == 200
    assert "Original" in result.json()["ass"]
