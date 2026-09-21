"""GitHub 저장소에서 하는 자막 검수. 여기에는 네트워크가 없습니다.

경로와 브랜치 이름, 용어집 TSV 읽고 쓰기, 그리고 **돌아온 자막이 우리가 보낸 것과
같은 자막인지** 보는 검사만 있습니다. GitHub 호출은 `worker.github`입니다.

돌아온 파일은 남이 고친 글입니다. 그대로 믿지 않습니다:

- 자막 **개수**가 다르면 작업에 넣을 수 없습니다. 어느 줄이 어느 줄인지 알 수 없습니다.
- **시각**이 바뀌었으면 문제로 보고합니다. 시각은 원본 음성이 정합니다.
- 빈 줄도 보고합니다.

자동으로 고치지 않습니다. 사람이 화면에서 보고 새 버전을 만듭니다.
"""

from __future__ import annotations

from collections.abc import Sequence

from pipeline.editing import Cue

# 돌아온 파일의 크기 상한. 자막 5,000개도 1MB를 넘지 않습니다.
MAX_FILE_BYTES = 2_000_000
# 작업에 넣을 수 있는 자막 수. `pipeline.workflow.WorkflowOptions.translated_cues`와 같습니다.
MAX_CUES = 5000
# 시각이 같다고 보는 차이. SRT는 밀리초까지만 적으므로 왕복하면 1ms 안에서 흔들립니다.
TIME_TOLERANCE = 0.0015

GLOSSARY_HEADER = "# 원문<탭>목표 표기. 목표 표기를 비우면 원문을 그대로 둡니다."


def branch_for(job_id: str) -> str:
    """작업 하나에 브랜치 하나. 다시 내보내면 같은 브랜치에 덧씁니다."""
    return f"subtitle-review/{job_id}"


def subtitle_path(job_id: str, language: str) -> str:
    return f"subtitles/{job_id}/{language}.srt"


def glossary_path(source: str | None, target: str) -> str:
    return f"glossary/{source or 'auto'}-{target}.tsv"


def glossary_tsv(entries: dict[str, str | None]) -> str:
    """용어집을 한 줄에 하나씩. 순서를 고정해 다시 내보내도 쓸데없는 커밋이 안 생깁니다."""
    lines = [GLOSSARY_HEADER]
    for term in sorted(entries):
        target = entries[term] or ""
        lines.append(f"{term}\t{target}" if target else term)
    return "\n".join(lines) + "\n"


def parse_glossary_tsv(text: str) -> dict[str, str | None]:
    """`원문<탭>목표` 줄을 읽습니다. `#`로 시작하는 줄과 빈 줄은 건너뜁니다.

    목표가 비면 None입니다(원문 그대로 지킴). 같은 원문이 여러 번 나오면 마지막이
    이깁니다. 사람이 손으로 고치는 파일이라 CRLF와 앞뒤 공백을 견딥니다.
    """
    entries: dict[str, str | None] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        term, _, target = line.partition("\t")
        term, target = term.strip(), target.strip()
        if term:
            entries[term] = target or None
    return entries


def compare(original: Sequence[Cue], edited: Sequence[Cue]) -> list[str]:
    """보낸 자막과 돌아온 자막을 견줍니다. 사람이 읽는 문제 목록을 돌려줍니다.

    비어 있으면 그대로 써도 되는 번역입니다. 개수가 다르면 나머지 검사는 뜻이
    없으므로 거기서 멈춥니다.
    """
    if len(edited) != len(original):
        return [
            f"자막 개수가 다릅니다: 보낸 것 {len(original)}개, 돌아온 것 {len(edited)}개. "
            "줄을 합치거나 나누지 마세요."
        ]
    problems: list[str] = []
    for index, (before, after) in enumerate(zip(original, edited, strict=True), start=1):
        if (
            abs(before.start - after.start) > TIME_TOLERANCE
            or abs(before.end - after.end) > TIME_TOLERANCE
        ):
            problems.append(
                f"자막 {index}: 시각이 바뀌었습니다 "
                f"({before.start:.3f}~{before.end:.3f} → {after.start:.3f}~{after.end:.3f}). "
                "시각은 원본 음성이 정합니다."
            )
        if not after.text.strip():
            problems.append(f"자막 {index}: 비어 있습니다.")
    return problems


def pull_request_body(subtitle: str, glossary: str, language: str) -> str:
    """번역가가 읽는 안내. 지켜야 하는 것을 PR 본문에 적어 둡니다."""
    return f"""자막 검수용 PR입니다. 목표 언어: **{language}**

고칠 파일은 `{subtitle}`입니다.

- **시각(타임코드)을 고치지 마세요.** 시각은 원본 음성이 정합니다.
- **줄을 합치거나 나누지 마세요.** 자막 개수가 달라지면 작업에 넣을 수 없습니다.
- 고칠 것은 각 자막의 **글자**입니다.
- 인명·그룹명·곡명·브랜드명 표기는 `{glossary}`를 따릅니다. 표기를 바꾸려면 그 파일을 고치세요.

다 고치면 이 브랜치에 그대로 두세요. 관리화면에서 **가져오기**를 누르면 이 브랜치의
파일을 읽어 위 규칙을 검사합니다. 병합은 검사를 통과한 뒤에 사람이 합니다.
"""
