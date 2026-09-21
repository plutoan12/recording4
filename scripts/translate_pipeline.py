#!/usr/bin/env python3
"""자막 파일 하나로 번역 경로를 끝까지 돌립니다: 묶음 → 용어집 → 기계 번역 → (보정) → QA → SRT.

워커의 `translate:N` 단계와 같은 조각(pipeline.batching · glossary · translation_jobs ·
translation_qa, worker.providers)을 씁니다. DB 대신 용어집은 JSON 파일, 번역 기억은
JSON 캐시 파일입니다. 서버 없이 한 파일을 검수하거나 CI에서 경로를 확인할 때 씁니다.

    python3 scripts/translate_pipeline.py --input docs/samples/ko.srt --source ko --target en \
        --glossary docs/samples/glossary-kpop.json --provider identity --output /tmp/out.srt

`--provider identity`는 번역기를 부르지 않고 원문을 그대로 돌려줍니다(무료). 묶음·용어집
보호·복원·QA·SRT 쓰기가 도는지만 봅니다. QA에는 당연히 "원문과 같습니다"가 찍힙니다.
google · deepl · huggingface · claude는 `--allow-paid` 없이는 부르지 않습니다(huggingface는
로컬이지만 모델을 내려받으므로 같은 스위치로 막습니다). `--refine`은 Claude 보정입니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

from pipeline.batching import scene_batches
from pipeline.editing import Cue
from pipeline.glossary import apply_terms, protect, restore
from pipeline.languages import LANGUAGES, is_supported
from pipeline.subtitle_files import dump_subtitles, parse_subtitles
from pipeline.translation_jobs import build_job
from pipeline.translation_qa import as_dicts, review

Translate = Callable[[list[str], str, str | None], list[str]]


def identity(texts: list[str], target: str, source: str | None) -> list[str]:
    return list(texts)


def make_translator(provider: str, *, allow_paid: bool, project: str | None, model: str | None):
    """공급자 이름 → 함수. 유료·모델 내려받기는 --allow-paid 뒤에만."""
    if provider == "identity":
        return identity
    if not allow_paid:
        raise SystemExit(f"--provider {provider}는 --allow-paid가 있어야 부릅니다.")
    from worker import providers as p

    if provider == "google":
        if not project:
            raise SystemExit("--project가 필요합니다(Google Cloud 프로젝트).")
        return p.GoogleTranslator(project, allow_paid=True).translate
    if provider == "deepl":
        import os

        import httpx

        key = os.environ.get("R4_DEEPL_API_KEY") or os.environ.get("DEEPL_API_KEY")
        if not key:
            raise SystemExit("R4_DEEPL_API_KEY 환경 변수가 필요합니다.")
        client = httpx.Client()
        return p.DeepLTranslator(key, client=client, allow_paid=True).translate
    if provider == "huggingface":
        return p.HuggingFaceTranslator(model or p.HuggingFaceTranslator.DEFAULT_MODEL).translate
    if provider == "claude":
        adapter = p.ClaudeTranslator(allow_paid=True, model=model or p.TRANSLATE_MODEL)
        return lambda texts, target, source: adapter.translate(
            build_job(texts, source=source, target=target)
        )
    raise SystemExit(f"모르는 공급자: {provider}")


class FileMemory:
    """JSON 파일 번역 기억. 키는 워커와 같은 뜻(출발·목표·공급자·용어집·원문 해시)입니다."""

    def __init__(self, path: Path | None, suffix: str):
        self.path, self.suffix = path, suffix
        self.rows: dict[str, str] = {}
        if path and path.exists():
            self.rows = json.loads(path.read_text(encoding="utf-8"))

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.suffix}\n{text}".encode()).hexdigest()

    def get(self, text: str) -> str | None:
        return self.rows.get(self.key(text))

    def put(self, text: str, translated: str) -> None:
        self.rows[self.key(text)] = translated

    def save(self) -> None:
        if self.path:
            self.path.write_text(
                json.dumps(self.rows, ensure_ascii=False, indent=1), encoding="utf-8"
            )


def translate_cues(
    cues: list[Cue],
    *,
    source: str | None,
    target: str,
    entries: dict[str, str | None],
    translate: Translate,
    memory: FileMemory,
    refine: Callable[[list[str], list[str], list[str], list[str]], list[str]] | None = None,
    max_lines: int = 100,
    context_lines: int = 3,
) -> tuple[list[Cue], dict]:
    """워커 translate 단계와 같은 순서. (번역 자막, 통계)를 돌려줍니다."""
    rows = [c.model_dump() for c in cues]
    translated: list[str] = []
    stats = {"batches": 0, "sent": 0, "cached": 0, "lost_placeholders": 0}
    terms = {term: (value or term) for term, value in entries.items()}
    for batch in scene_batches(rows, max_lines=max_lines):
        stats["batches"] += 1
        texts = [c["text"] for c in batch]
        known = {t: memory.get(t) for t in texts}
        missing = list(dict.fromkeys(t for t in texts if known[t] is None))
        stats["cached"] += len(texts) - len(missing)
        if missing:
            protected = protect(missing, entries)
            output = translate(protected.texts, target, source)
            restored, lost = restore(output, protected)
            stats["lost_placeholders"] += len(lost)
            stats["sent"] += len(missing)
            final = [apply_terms(t, terms) for t in restored]
            if refine is not None:
                offset = len(translated)
                before = [c["text"] for c in rows[max(0, offset - context_lines) : offset]]
                after_start = offset + len(batch)
                after = [c["text"] for c in rows[after_start : after_start + context_lines]]
                final = [apply_terms(t, terms) for t in refine(missing, final, before, after)]
            for text, result in zip(missing, final, strict=True):
                known[text] = result
                memory.put(text, result)
        translated.extend(known[t] for t in texts)
    memory.save()
    out = [
        Cue(start=c.start, end=c.end, text=t or " ") for c, t in zip(cues, translated, strict=True)
    ]
    return out, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, required=True, help="SRT/VTT/ASS 자막 파일")
    parser.add_argument(
        "--source", default=None, help="출발 언어(없으면 자동 감지, 로컬 모델은 필수)"
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--glossary", type=Path, default=None, help="{원문: 목표표기|null} JSON")
    parser.add_argument(
        "--provider",
        default="identity",
        choices=["identity", "google", "deepl", "huggingface", "claude"],
    )
    parser.add_argument("--model", default=None, help="huggingface·claude 모델 이름")
    parser.add_argument("--project", default=None, help="Google Cloud 프로젝트")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--refine", action="store_true", help="Claude 문맥·말투 보정(유료)")
    parser.add_argument("--cache", type=Path, default=None, help="번역 기억 JSON 파일")
    parser.add_argument("--output", type=Path, default=None, help="번역 자막을 쓸 파일(.srt/.vtt)")
    parser.add_argument("--qa-json", type=Path, default=None, help="QA 결과를 쓸 JSON")
    parser.add_argument("--max-batch-lines", type=int, default=100)
    args = parser.parse_args(argv)

    if args.target not in LANGUAGES or (args.source and args.source not in LANGUAGES):
        print(f"지원 언어: {', '.join(LANGUAGES)}")
        return 2
    if not is_supported(args.source, args.target):
        print(f"지원하지 않는 방향입니다: {args.source or '자동'} → {args.target}")
        return 2
    cues, dropped = parse_subtitles(args.input.read_text(encoding="utf-8"))
    if not cues:
        print("자막을 읽지 못했습니다.")
        return 2
    entries = json.loads(args.glossary.read_text(encoding="utf-8")) if args.glossary else {}
    translate = make_translator(
        args.provider, allow_paid=args.allow_paid, project=args.project, model=args.model
    )
    refine = None
    if args.refine:
        if not args.allow_paid:
            raise SystemExit("--refine은 --allow-paid가 있어야 합니다.")
        from worker.providers import ClaudeTranslator

        adapter = ClaudeTranslator(allow_paid=True)

        def refine(texts, drafts, before, after):  # noqa: ANN001
            job = build_job(
                texts,
                source=args.source,
                target=args.target,
                before=before,
                after=after,
                entries=entries,
            )
            return adapter.translate(job, drafts=drafts)

    suffix = "|".join(
        [
            args.source or "auto",
            args.target,
            args.provider,
            args.model or "",
            hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()[:12],
            "refine" if args.refine else "",
        ]
    )
    memory = FileMemory(args.cache, suffix)
    translated, stats = translate_cues(
        cues,
        source=args.source,
        target=args.target,
        entries=entries,
        translate=translate,
        memory=memory,
        refine=refine,
        max_lines=args.max_batch_lines,
    )
    issues = review(
        [c.text for c in cues],
        [c.text for c in translated],
        source=args.source,
        target=args.target,
        entries=entries,
        timings=[(c.start, c.end) for c in cues],
    )
    print(
        f"{args.input.name}: 자막 {len(cues)}개, 묶음 {stats['batches']}개, "
        f"공급자에 보낸 문장 {stats['sent']}개, 기억에서 {stats['cached']}개, "
        f"사라진 자리표시자 {stats['lost_placeholders']}개"
    )
    if dropped:
        print("읽으며 뺀 것: " + "; ".join(dropped))
    for issue in issues:
        print(f"  자막 {issue.index + 1} [{issue.kind}] {issue.detail}")
    if not issues:
        print("  QA 문제 없음")
    if args.output:
        fmt = "vtt" if args.output.suffix.lower() == ".vtt" else "srt"
        args.output.write_text(dump_subtitles(translated, fmt), encoding="utf-8")
        print(f"자막을 썼습니다: {args.output}")
    if args.qa_json:
        args.qa_json.write_text(
            json.dumps({"stats": stats, "issues": as_dicts(issues)}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    if args.provider == "identity":
        print("identity 공급자라 번역은 하지 않았습니다. 경로가 도는지만 확인한 것입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
