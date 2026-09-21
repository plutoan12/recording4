"""용어집. 번역이 꼭 써야 할 표기를 번역 전에 원문에 박아 넣습니다.

채널 이름, 제품명, 사람 이름처럼 **매번 같게 나와야 하는 말**이 문장마다
다르게 번역되는 것을 막습니다. 뜻이 아니라 표기를 고정하는 장치입니다.

## 왜 이 방식인가

Google 번역은 `text/plain`으로 보낸 글에서 **일부 구간만 건너뛰게 할 수
없습니다.** 건드리지 말 구간을 표시하려면 `text/html`로 보내고 그 구간을
`translate="no"`로 감싸야 합니다. 그래서 여기서는 용어 자리를 아예 **목표
언어 표기로 바꿔 놓고** 그 부분만 번역하지 말라고 표시합니다.

    "녹화4로 편집했습니다."
      → '<span translate="no">Recording 4</span>로 편집했습니다.'
      → '<span translate="no">Recording 4</span> was used for editing.'
      → 'Recording 4 was used for editing.'

용어가 하나도 걸리지 않은 문장은 **지금까지와 똑같이** `text/plain`으로
보냅니다. HTML로 바꾸는 것은 용어가 실제로 걸린 문장뿐입니다.

Google 자체 용어집(`glossaryConfig`)은 더 낫습니다. 어미 변화까지 Google이
처리하고 추가 요금도 없습니다. 다만 용어 파일을 **Cloud Storage**에 두고
`global`이 아닌 지역에 용어집 리소스를 만들어야 합니다. 이 저장소의 객체
저장소는 S3 호환(MinIO)이라 그 경로가 준비되어 있지 않습니다. 그래서 여기
방식을 기본으로 두고, 리소스 이름이 설정되어 있으면 그쪽을 씁니다
(`worker.providers.GoogleTranslator`).

## 아는 한계

- 넣는 표기는 **글자 그대로**입니다. 목표 언어의 어미·관사·복수형에 맞춰
  변형하지 않습니다. `Recording 4`는 어디서나 `Recording 4`입니다.
- 번역기가 보기에 그 자리는 번역할 수 없는 덩어리라 **주변 어순이 어색해질
  수 있습니다.** 용어를 많이 넣을수록 심해집니다.
- 찾기는 **대소문자를 가립니다.** `Recording`과 `recording`을 모두 바꾸려면
  둘 다 적으세요. 한국어 원문에서는 문제가 되지 않습니다.
- 겹치는 용어는 **긴 쪽이 이깁니다**(`녹화4`가 `녹화`보다 먼저).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache
from html import escape, unescape

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TERMS = 500
MAX_SOURCE = 80
MAX_TARGET = 120

# 번역 결과에서 걷어낼 표시. 원문의 꺾쇠는 보낼 때 개체 참조로 바꾸므로
# 여기 걸리는 것은 우리가 넣은 표시(와 번역기가 더한 표시)뿐입니다.
_TAG = re.compile(r"<[^>]*>")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class GlossaryError(ValueError):
    pass


class Glossary(BaseModel):
    """한 방향(원문 언어 → 목표 언어)의 용어 목록.

    `entries`는 `{원문 표기: 번역문에 넣을 표기}`입니다. 관리 API의
    `glossaries` 테이블과 같은 모양이라 그대로 주고받습니다.
    """

    model_config = ConfigDict(extra="forbid")

    source_language: str = Field(pattern=r"^[a-z]{2,3}$")
    target_language: str = Field(pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,8})?$")
    version: int = Field(default=1, ge=1)
    entries: dict[str, str] = Field(default_factory=dict)

    @field_validator("entries")
    @classmethod
    def usable(cls, entries: dict[str, str]) -> dict[str, str]:
        if len(entries) > MAX_TERMS:
            raise ValueError(f"용어는 {MAX_TERMS}개까지 넣을 수 있습니다.")
        for source, target in entries.items():
            for value, limit, label in (
                (source, MAX_SOURCE, "원문 표기"),
                (target, MAX_TARGET, "번역 표기"),
            ):
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{label}가 비어 있습니다.")
                if value != value.strip():
                    raise ValueError(f"{label} 앞뒤의 공백을 지우세요: {value!r}")
                if len(value) > limit:
                    raise ValueError(f"{label}는 {limit}자까지입니다: {value[:20]}…")
                if _CONTROL.search(value):
                    raise ValueError(f"{label}에 줄바꿈이나 제어 문자를 넣을 수 없습니다.")
        return entries

    @property
    def sources(self) -> tuple[str, ...]:
        """찾을 원문 표기. 긴 것부터입니다."""
        return tuple(sorted(self.entries, key=len, reverse=True))


@lru_cache(maxsize=64)
def _pattern(sources: tuple[str, ...]) -> re.Pattern[str]:
    """용어를 찾는 정규식. 긴 표기가 먼저 걸리도록 그 순서로 잇습니다."""
    return re.compile("|".join(re.escape(source) for source in sources))


def protect(text: str, glossary: Glossary | None) -> tuple[str, tuple[str, ...]]:
    """용어를 넣은 HTML과, 번역문에 남아야 할 표기를 돌려줍니다.

    걸린 용어가 없으면 **원문을 그대로** 돌려줍니다. 이때 두 번째 값이 비어
    있으므로 부르는 쪽은 그 문장을 `text/plain`으로 보내면 됩니다.
    """
    if glossary is None or not glossary.entries:
        return text, ()
    pieces: list[str] = []
    terms: list[str] = []
    cursor = 0
    for found in _pattern(glossary.sources).finditer(text):
        target = glossary.entries[found.group(0)]
        pieces.append(escape(text[cursor : found.start()], quote=False))
        pieces.append(f'<span translate="no">{escape(target, quote=False)}</span>')
        terms.append(target)
        cursor = found.end()
    if not terms:
        return text, ()
    pieces.append(escape(text[cursor:], quote=False))
    return "".join(pieces), tuple(terms)


def restore(translated: str) -> str:
    """번역된 HTML을 다시 평문으로. 표시와 개체 참조를 걷어냅니다."""
    return unescape(_TAG.sub("", translated)).strip()


def missing(translated: str, terms: Sequence[str]) -> list[str]:
    """번역문에서 사라진 용어. 같은 용어가 두 번 들어갔으면 두 번 셉니다.

    번역기가 표시를 지우거나 안쪽 글자를 건드리면 여기에 걸립니다. 걸렸다고
    번역을 버리지는 않습니다. **용어가 빠진 번역이 깨진 번역보다 낫습니다.**
    세어 두었다가 사람에게 보여 주는 것이 이 함수의 몫입니다.
    """
    left = translated
    gone: list[str] = []
    for term in terms:
        index = left.find(term)
        if index < 0:
            gone.append(term)
        else:
            left = left[:index] + left[index + len(term) :]
    return gone
