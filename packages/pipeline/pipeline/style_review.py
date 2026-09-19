"""Read-only register hints. Never rewrite dialogue or treat hints as confirmed errors."""

from __future__ import annotations

import re

_QUOTES = re.compile(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』')
_RULES = {
    "ko": (
        ("합니다체", r"(?:습니다|입니다|합니다|됩니다|십시오|습니까)$"),
        ("해요체", r"(?:해요|어요|아요|예요|이에요|세요|죠|거든요|나요|까요)$"),
        (
            "비격식·서술체",
            r"(?:했다|됐다|되었다|있다|없다|한다|된다|이었다|였다|었다|았다|는다|이다)$",
        ),
    ),
    "ja": (
        ("です・ます체", r"(?:です|でした|ます|ました|ません|ください|でしょう)$"),
        ("보통체", r"(?:だった|である|ていた|でいた|ではない|だ)$"),
    ),
    "en": (
        ("격식 표현", r"\b(?:therefore|furthermore|hereby|shall)\b"),
        ("구어 표현", r"\b(?:gonna|wanna|ain't|gotta)\b"),
    ),
    "zh": (
        ("정중한 표현", r"(?:您|请|請)"),
        ("구어 표현", r"(?:咱|啥|咋|甭)"),
    ),
}


def style_warnings(cues: list[dict], language: str | None) -> list[dict]:
    """Flag observed register mixtures; an empty list is not a quality certificate.

    Quoted speech is excluded. Speaker changes and intentional differences require
    comparison with the source; these hints never block approval or modify text.
    """
    rules = _RULES.get((language or "").split("-")[0].lower(), ())
    found: dict[str, list[int]] = {}
    for index, cue in enumerate(cues):
        text = _QUOTES.sub("", cue.get("text", ""))
        for sentence in re.split(r"(?<=[.!?。！？])\s*|\n+", text):
            sentence = sentence.strip().rstrip(".!?。！？… ")
            for label, pattern in rules:
                if re.search(pattern, sentence, flags=re.I):
                    if index + 1 not in found.setdefault(label, []):
                        found[label].append(index + 1)
                    # Korean/Japanese suffix categories are exclusive per sentence.
                    if (language or "").split("-")[0] in ("ko", "ja"):
                        break
    if len(found) < 2:
        return []
    return [
        {
            "kind": "mixed_register",
            "message": (
                "서로 다른 문체 표현이 감지됐습니다. " "화자 차이나 원문의 의도인지 확인하세요."
            ),
            "registers": [
                {"label": label, "cue_numbers": indices} for label, indices in found.items()
            ],
        }
    ]
