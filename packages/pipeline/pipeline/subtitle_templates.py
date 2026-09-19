"""Shared ASS generation for the browser preview and FFmpeg output."""

import pysubs2

from pipeline.editing import Cue, clip_cues
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules

TEMPLATES = [
    {"id": "classic", "name": "기본 번역형", "description": "흰 글씨와 검은 외곽선"},
    {"id": "box", "name": "검은 배경형", "description": "반투명 검은 배경으로 가독성 강조"},
    {"id": "shorts", "name": "숏폼 강조형", "description": "노란 굵은 글씨와 문장 등장 효과"},
    {
        "id": "speaker",
        "name": "화자별 색상형",
        "description": "같은 화자는 같은 색상. 화자 정보가 없으면 흰색",
    },
    {
        "id": "bilingual",
        "name": "원문·번역 병기형",
        "description": "원문을 번역 위에 표시. 원문이 없으면 번역만 표시",
    },
]


def plain_ass(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", r"\N")


def build_ass(spec, rules: SubtitleRules = DEFAULT_RULES) -> str:
    template = getattr(spec, "subtitle_template", "classic")
    if template not in {t["id"] for t in TEMPLATES}:
        raise ValueError("지원하지 않는 자막 템플릿입니다.")
    subs = pysubs2.SSAFile()
    subs.info.update(PlayResX=str(spec.width), PlayResY=str(spec.height), WrapStyle="0")
    style = pysubs2.SSAStyle(
        fontname="Noto Sans CJK KR",
        fontsize=spec.font_size,
        outline=3,
        shadow=1,
        marginl=50,
        marginr=50,
        marginv=int(spec.height * 0.13),
    )
    if template == "box":
        style.borderstyle = 3
        style.outline = 8
        style.outlinecolor = pysubs2.Color(0, 0, 0, 70)
        style.shadow = 0
    elif template == "shorts":
        style.bold = True
        style.primarycolor = pysubs2.Color(255, 225, 65)
        style.outline = 4
    subs.styles["Default"] = style
    cues = clip_cues(spec.cues, spec.start, spec.end)
    palette = [(100, 220, 255), (255, 210, 95), (225, 150, 255), (130, 240, 160)]
    speakers = list(dict.fromkeys(c.speaker for c in cues if c.speaker))
    mapping = {speaker: f"Speaker{i}" for i, speaker in enumerate(speakers)}
    for i, speaker in enumerate(speakers):
        speaker_style = style.copy()
        speaker_style.primarycolor = pysubs2.Color(*palette[i % len(palette)])
        subs.styles[mapping[speaker]] = speaker_style
    for cue in apply_rules(cues, rules):
        effect = (
            r"{\fad(100,80)\fscx90\fscy90\t(0,120,\fscx100\fscy100)}"
            if template == "shorts"
            else ""
        )
        subs.append(
            pysubs2.SSAEvent(
                start=round(cue.start * 1000),
                end=round(cue.end * 1000),
                text=effect + plain_ass(cue.text),
                style=mapping.get(cue.speaker, "Default") if template == "speaker" else "Default",
            )
        )
    if template == "bilingual":
        secondary = style.copy()
        secondary.fontsize = spec.font_size * 0.75
        secondary.marginv = int(spec.height * 0.27)
        secondary.primarycolor = pysubs2.Color(190, 220, 255)
        subs.styles["Original"] = secondary
        originals = [
            Cue(start=c.start, end=c.end, text=c.original_text) for c in cues if c.original_text
        ]
        for cue in apply_rules(originals, rules):
            subs.append(
                pysubs2.SSAEvent(
                    start=round(cue.start * 1000),
                    end=round(cue.end * 1000),
                    text=plain_ass(cue.text),
                    style="Original",
                )
            )
    if spec.title:
        title = style.copy()
        title.alignment = pysubs2.Alignment.TOP_CENTER
        title.marginv = int(spec.height * 0.08)
        subs.styles["Title"] = title
        subs.append(
            pysubs2.SSAEvent(
                start=0,
                end=round((spec.end - spec.start) * 1000),
                text=plain_ass(spec.title),
                style="Title",
            )
        )
    return subs.to_string("ass")
