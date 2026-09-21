"""번역 묶음 하나를 번역기에 보내는 모양(job). 구조는 llm-subs를 따랐습니다.

참고: https://github.com/azratul/llm-subs (translate_subs/ai/job_protocol.py, blocks.py,
memory/rules.py). GPL-3.0이라 코드는 옮기지 않고 구조만 같게 했습니다:
번호가 붙은 줄 목록 + 앞뒤 문맥 줄 + 이 묶음에 필요한 규칙만. 답은 번호 → 번역문.

문맥 줄은 **읽으라고만** 주고 번역하지 않습니다. 규칙은 이 묶음 원문에 실제로
나오는 용어만 넣어, 용어집이 커져도 프롬프트가 같이 커지지 않게 합니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pipeline.glossary import prompt_block, terms_in_text
from pipeline.languages import LANGUAGES

DEFAULT_CONTEXT_LINES = 3

# llm-subs의 style guide 기본값(honorifics keep, names keep_original, tone natural)을
# 우리 쓰임(K-pop 자막)에 맞춘 것입니다.
STYLE_RULES: tuple[str, ...] = (
    "Keep honorifics if the source uses them.",
    "Keep proper names (people, groups, songs, brands) unchanged unless the glossary says so.",
    "Keep every number exactly as written in the source.",
    "Use the register and politeness level natural for the target language.",
)


@dataclass(frozen=True)
class JobLine:
    id: int
    text: str


@dataclass
class TranslationJob:
    source: str | None
    target: str
    translate: list[JobLine]
    context_before: list[JobLine] = field(default_factory=list)
    context_after: list[JobLine] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[int]:
        return [line.id for line in self.translate]

    def prompt(self, *, drafts: Sequence[str] | None = None) -> str:
        """번역기에 보내는 본문. 번호는 이 묶음 안 순서(0부터)입니다.

        `drafts`가 있으면 보정 요청입니다: 줄마다 원문과 초안을 함께 보냅니다.
        """
        if drafts is not None and len(drafts) != len(self.translate):
            raise ValueError("초안 수가 줄 수와 다릅니다.")
        parts = []
        if self.rules:
            parts.append("Rules:\n" + "\n".join(f"- {rule}" for rule in self.rules))
        if self.context_before:
            parts.append(
                "[CONTEXT before — do not translate]\n"
                + "\n".join(line.text for line in self.context_before)
            )
        if drafts is None:
            parts.append(
                f"Translate these {len(self.translate)} lines "
                f"{self.source_label()} → {self.target_label()}:\n"
                + "\n".join(f"#{line.id}\t{line.text}" for line in self.translate)
            )
        else:
            parts.append(
                f"Polish these {len(self.translate)} draft translations "
                f"{self.source_label()} → {self.target_label()} (#id<tab>source<tab>draft):\n"
                + "\n".join(
                    f"#{line.id}\t{line.text}\t{draft}"
                    for line, draft in zip(self.translate, drafts, strict=True)
                )
            )
        if self.context_after:
            parts.append(
                "[CONTEXT after — do not translate]\n"
                + "\n".join(line.text for line in self.context_after)
            )
        return "\n\n".join(parts)

    def source_label(self) -> str:
        return LANGUAGES.get(self.source or "", self.source or "auto-detected language")

    def target_label(self) -> str:
        return LANGUAGES.get(self.target, self.target)


def build_job(
    texts: Sequence[str],
    *,
    source: str | None,
    target: str,
    before: Sequence[str] = (),
    after: Sequence[str] = (),
    entries: dict[str, str | None] | None = None,
    context_lines: int = DEFAULT_CONTEXT_LINES,
) -> TranslationJob:
    """묶음 하나. 용어 규칙은 이 묶음 원문에 나오는 것만 붙입니다."""
    job = TranslationJob(
        source=source,
        target=target,
        translate=[JobLine(i, text) for i, text in enumerate(texts)],
        context_before=[JobLine(-1, t) for t in list(before)[-context_lines:]]
        if context_lines
        else [],
        context_after=[JobLine(-1, t) for t in list(after)[:context_lines]]
        if context_lines
        else [],
        rules=list(STYLE_RULES),
    )
    terms = terms_in_text(entries or {}, "\n".join(texts))
    if terms:
        job.rules.append(prompt_block(terms))
    return job
