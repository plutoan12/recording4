"""자막을 SRT·WebVTT 파일 글자로 만듭니다.

순수 계산만 둡니다. 파일을 읽거나 쓰지 않고 문자열만 돌려줍니다. 파일 형식
변환은 이미 쓰고 있는 pysubs2가 맡습니다(근거는 docs/TECH_DECISIONS.md).

내보내는 자막은 영상에 굽는 자막과 같습니다. 구간 밖 자막을 빼고, 시각을 출력
시작 기준으로 옮기고(`clip_cues`), 같은 표시 규칙으로 줄바꿈·분할합니다
(`apply_rules`). 출력 구간은 경로마다 다릅니다. 숏폼 편집본은 편집본의
시작·끝이고, 번역·더빙 작업은 0부터 출력 길이까지입니다.

화면 제목은 자막이 아니라 화면 구성이라 넣지 않습니다. SRT와 WebVTT에는 위치
지정이 없어 제목을 넣으면 첫 자막과 시간이 겹칩니다.
"""

from __future__ import annotations

from typing import Literal, get_args

import pysubs2

from pipeline.editing import Cue, EditSpec, clip_cues
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules

SubtitleFormat = Literal["srt", "vtt"]

FORMATS: tuple[SubtitleFormat, ...] = get_args(SubtitleFormat)

MEDIA_TYPES: dict[SubtitleFormat, str] = {
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
}


def plain_ass(text: str) -> str:
    """pysubs2 이벤트 글자를 안전하게 만듭니다.

    pysubs2는 이벤트 글자를 ASS 표기로 읽습니다. 중괄호를 그대로 두면 사용자
    자막이 재생기 명령으로 해석되고, SRT·VTT로 옮길 때는 그 부분이 통째로
    사라집니다. 전각 문자로 바꿔 글자를 잃지 않게 합니다. 줄바꿈만 ASS 표기로
    남기고, 파일로 쓸 때 각 형식의 줄바꿈으로 돌아갑니다.
    """
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", r"\N")


def output_cues(
    cues: list[Cue], start: float, end: float, rules: SubtitleRules = DEFAULT_RULES
) -> list[Cue]:
    """영상에 굽는 것과 같은 자막. 시각은 출력 시작을 0초로 둡니다."""
    return apply_rules(clip_cues(cues, start, end), rules)


def subtitle_file(
    cues: list[Cue],
    start: float,
    end: float,
    subtitle_format: SubtitleFormat,
    rules: SubtitleRules = DEFAULT_RULES,
) -> str:
    """출력 구간의 자막을 SRT 또는 WebVTT 글자로 돌려줍니다. 자막이 없으면 빈 글자입니다."""
    if subtitle_format not in MEDIA_TYPES:
        raise ValueError(f"지원하지 않는 자막 형식입니다: {subtitle_format}")
    shaped = output_cues(cues, start, end, rules)
    if not shaped:
        return ""
    subs = pysubs2.SSAFile()
    for cue in shaped:
        subs.append(
            pysubs2.SSAEvent(
                start=round(cue.start * 1000),
                end=round(cue.end * 1000),
                text=plain_ass(cue.text),
            )
        )
    return subs.to_string(subtitle_format)


def clip_subtitle_file(
    spec: EditSpec, subtitle_format: SubtitleFormat, rules: SubtitleRules = DEFAULT_RULES
) -> str:
    """숏폼 편집본 자막. 출력 구간은 편집본의 시작·끝입니다."""
    return subtitle_file(spec.cues, spec.start, spec.end, subtitle_format, rules)
