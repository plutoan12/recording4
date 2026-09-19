"""자막을 SRT·WebVTT 파일 글자로 만듭니다.

순수 계산만 둡니다. 파일을 읽거나 쓰지 않고 문자열만 돌려줍니다. 파일 형식
변환은 이미 쓰고 있는 pysubs2가 맡습니다(근거는 docs/TECH_DECISIONS.md).

밖에서 만든 자막 파일을 읽어 대본으로 들이는 일도 여기서 합니다(`decode_subtitles`로
글자를 찾고 `parse_subtitles`로 자막을 읽습니다).

내보내는 자막은 영상에 굽는 자막과 같습니다. 구간 밖 자막을 빼고, 시각을 출력
시작 기준으로 옮기고(`clip_cues`), 같은 표시 규칙으로 줄바꿈·분할합니다
(`apply_rules`). 출력 구간은 경로마다 다릅니다. 숏폼 편집본은 편집본의
시작·끝이고, 번역·더빙 작업은 0부터 출력 길이까지입니다.

화면 제목은 자막이 아니라 화면 구성이라 넣지 않습니다. SRT와 WebVTT에는 위치
지정이 없어 제목을 넣으면 첫 자막과 시간이 겹칩니다.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Literal, get_args

import pysubs2
from charset_normalizer import from_bytes

from pipeline.editing import Cue, EditSpec, clip_cues
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules, normalize

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


def dump_subtitles(cues: list[Cue], subtitle_format: SubtitleFormat = "srt") -> str:
    """자막을 **규칙 없이** 그대로 파일 글자로 씁니다.

    `subtitle_file()`과 달리 줄바꿈·분할을 하지 않습니다. 밖의 도구에 넘겼다가
    돌려받는 경로(싱크 보정)에 씁니다. 규칙을 적용해 보내면 자막 개수가 달라져
    돌아온 시각을 원래 자막에 도로 맞출 수 없습니다.
    """
    subs = pysubs2.SSAFile()
    for cue in cues:
        subs.append(
            pysubs2.SSAEvent(
                start=round(cue.start * 1000),
                end=round(cue.end * 1000),
                text=plain_ass(cue.text),
            )
        )
    return subs.to_string(subtitle_format)


MAX_IMPORT_CHARS = 2000
"""자막 하나의 글자 수 상한. `pipeline.editing.Cue`가 받는 값과 같습니다."""


def parse_subtitles(text: str) -> tuple[list[Cue], list[str]]:
    """자막 파일 글자를 대본 자막으로 읽습니다. (자막, 뺀 것에 대한 설명)을 돌려줍니다.

    SRT·WebVTT·ASS를 형식 표시 없이 읽습니다(pysubs2 자동 판별). 꾸밈 표기는
    벗기고 글자만 남깁니다. 재생기가 넣은 기울임·색·위치 지정은 대본이 아니며,
    우리 표시 규칙이 화면 모양을 따로 정합니다.

    줄바꿈은 공백으로 합칩니다. 파일의 줄바꿈은 그 도구가 그 화면에 맞춰 끊은
    결과라 우리 화면에는 맞지 않습니다. 렌더가 우리 규칙으로 다시 끊습니다.

    **뺀 자막은 조용히 버리지 않고 무엇을 왜 뺐는지 함께 돌려줍니다.** 부르는
    쪽이 사람에게 보여 줍니다.
    """
    try:
        parsed = pysubs2.SSAFile.from_string(text)
    except Exception as exc:  # noqa: BLE001 - pysubs2의 여러 실패를 한 말로 바꿉니다.
        raise ValueError(f"자막 파일을 읽지 못했습니다: {type(exc).__name__}") from None

    cues: list[Cue] = []
    notes: list[str] = []
    for index, event in enumerate(parsed, start=1):
        if event.is_comment or event.is_drawing:
            continue
        body = normalize(event.plaintext)
        start, end = event.start / 1000, event.end / 1000
        if not body:
            notes.append(f"{index}번: 글자가 없어 뺐습니다.")
        elif end <= start or start < 0:
            notes.append(f"{index}번: 시간이 올바르지 않아 뺐습니다({start:.3f}~{end:.3f}초).")
        elif len(body) > MAX_IMPORT_CHARS:
            notes.append(f"{index}번: {len(body)}자로 한도({MAX_IMPORT_CHARS}자)를 넘어 뺐습니다.")
        else:
            cues.append(Cue(start=start, end=end, text=body))
    if not cues:
        raise ValueError("읽을 수 있는 자막이 없습니다. 파일을 확인하세요.")
    return sorted(cues, key=lambda c: c.start), notes


# 들일 때 시험해 보는 인코딩. 한국어 자막에 흔한 CP949를 UTF-8 다음에 둡니다.
# CP949는 EUC-KR을 포함하므로 EUC-KR은 따로 두지 않습니다(결과가 같습니다).
IMPORT_ENCODINGS = ("utf-8", "cp949", "shift_jis", "gb18030", "cp1252")

PREVIEW_CHARS = 40


@dataclass(frozen=True, slots=True)
class EncodingChoice:
    """후보 인코딩과, 그것으로 읽었을 때 첫 자막이 어떻게 보이는지."""

    encoding: str
    preview: str


@dataclass(frozen=True, slots=True)
class Decoded:
    """읽은 글자와, 무엇으로 어떻게 읽었는지."""

    text: str
    encoding: str
    detected: bool  # True면 판별기가 고른 것입니다. 사람이 확인해야 합니다.


class UnknownEncoding(ValueError):
    """인코딩을 알 수 없습니다. 추측하지 않고 후보를 들어 사람에게 넘깁니다."""

    def __init__(self, choices: list[EncodingChoice]) -> None:
        super().__init__("자막 파일의 인코딩을 알 수 없습니다. 글자가 제대로 보이는 것을 고르세요.")
        self.choices = choices


def _bom_encoding(data: bytes) -> str | None:
    """파일이 스스로 밝힌 인코딩. 표시가 있으면 추측할 필요가 없습니다."""
    for bom, name in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if data.startswith(bom):
            return name
    return None


def _preview(text: str) -> str | None:
    """그 인코딩으로 읽은 첫 자막. 자막으로 읽히지 않으면 후보로 내놓지 않습니다."""
    try:
        cues, _ = parse_subtitles(text)
    except ValueError:
        return None
    return cues[0].text[:PREVIEW_CHARS]


def encoding_choices(data: bytes) -> list[EncodingChoice]:
    """고를 만한 인코딩과, 그것으로 읽었을 때 첫 자막이 어떻게 보이는지.

    자막으로 읽히지 않는 후보는 내놓지 않습니다. 고를 수 없는 선택지입니다.
    판별기가 골랐을 때도 이 목록을 함께 보여 주어, 글자가 깨졌으면 사람이 다른
    인코딩으로 되돌릴 수 있게 합니다.
    """
    choices: list[EncodingChoice] = []
    seen: set[str] = set()
    for candidate in IMPORT_ENCODINGS:
        try:
            text = data.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
        preview = _preview(text)
        # 같은 글자가 나오는 후보는 한 번만 보여 줍니다(CP949와 EUC-KR 등).
        if preview is None or preview in seen:
            continue
        seen.add(preview)
        choices.append(EncodingChoice(candidate, preview))
    return choices


def detect_encoding(data: bytes) -> str | None:
    """판별기가 고른 인코딩. 고르지 못하면 None입니다.

    판별은 추측입니다. 여기서는 이름만 돌려주고, 그 이름으로 읽은 글자가 실제로
    자막으로 읽히는지는 부르는 쪽이 확인합니다.
    """
    best = from_bytes(data).best()
    return best.encoding if best else None


def decode_subtitles(data: bytes, encoding: str | None = None) -> Decoded:
    """자막 파일 바이트를 글자로 바꿉니다.

    순서는 이렇습니다. 인코딩을 정해 주면 그것으로만 읽습니다. 안 주면 파일이
    밝힌 표시(BOM) → UTF-8 → 판별기(charset-normalizer) 순으로 봅니다.

    **판별기 결과는 그대로 믿지 않습니다.** 그 인코딩으로 읽은 글자가 자막으로
    읽히는지 확인합니다. 다만 이 확인은 시간 줄 같은 뼈대만 봅니다. 한국어 자막을
    cp1252로 읽으면 글자는 깨져도 파일 모양은 멀쩡해서 걸러지지 않습니다. 그래서
    판별로 읽었다는 사실(`detected=True`)을 함께 돌려줍니다. 잘못 고른 인코딩은
    조용히 저장됐다가 영상에 그대로 구워지므로, 사람이 글자를 보고 되돌릴 수
    있어야 합니다.

    판별기까지 실패하면 후보마다 첫 자막이 어떻게 보이는지 붙여 `UnknownEncoding`
    으로 올립니다. 이름(CP949·EUC-KR)만 보고는 고를 수 없어도 자기 자막 글자는
    알아봅니다.
    """
    if encoding:
        try:
            return Decoded(data.decode(encoding), encoding, detected=False)
        except (UnicodeDecodeError, LookupError) as exc:
            raise ValueError(f"{encoding}으로 읽지 못했습니다: {type(exc).__name__}") from None
    marked = _bom_encoding(data)
    if marked:
        return Decoded(data.decode(marked), marked, detected=False)
    try:
        return Decoded(data.decode("utf-8"), "utf-8", detected=False)
    except UnicodeDecodeError:
        pass
    guess = detect_encoding(data)
    if guess:
        try:
            text = data.decode(guess)
        except (UnicodeDecodeError, LookupError):
            text = ""
        # 자막으로 읽히지 않으면 판별이 틀린 것입니다. 그대로 쓰지 않습니다.
        if text and _preview(text) is not None:
            return Decoded(text, guess, detected=True)
    raise UnknownEncoding(encoding_choices(data))
