"""scripts/translate_pipeline.py: 파일 하나로 도는 번역 경로. 공급자는 대역입니다."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "r4translate_pipeline", ROOT / "scripts/translate_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identity_run_writes_srt_and_qa_without_calling_anyone(script, tmp_path, capsys):
    out, qa, cache = tmp_path / "out.srt", tmp_path / "qa.json", tmp_path / "tm.json"
    args = [
        "--input", str(ROOT / "docs/samples/ko.srt"), "--source", "ko", "--target", "en",
        "--glossary", str(ROOT / "docs/samples/glossary-kpop.json"),
        "--output", str(out), "--qa-json", str(qa), "--cache", str(cache),
    ]  # fmt: skip
    assert script.main(args) == 0
    first = capsys.readouterr().out
    assert "묶음 2개" in first and "공급자에 보낸 문장 4개" in first
    assert out.read_text(encoding="utf-8").count("-->") == 4
    report = json.loads(qa.read_text(encoding="utf-8"))
    assert report["stats"]["lost_placeholders"] == 0
    assert any(i["kind"] == "untranslated" for i in report["issues"])
    # 두 번째 실행은 전부 기억에서 옵니다.
    assert script.main(args) == 0
    assert "공급자에 보낸 문장 0개, 기억에서 4개" in capsys.readouterr().out


def test_paid_providers_need_the_switch(script):
    with pytest.raises(SystemExit):
        script.make_translator("deepl", allow_paid=False, project=None, model=None)
    with pytest.raises(SystemExit):
        script.make_translator("huggingface", allow_paid=False, project=None, model=None)


def test_unsupported_direction_exits_before_reading_providers(script):
    assert (
        script.main(
            ["--input", str(ROOT / "docs/samples/ko.srt"), "--source", "es", "--target", "ko"]
        )
        == 2
    )


def test_translate_cues_protects_terms_and_refines_with_context(script):
    from pipeline.editing import Cue

    seen, refined = [], []

    def translate(texts, target, source):
        seen.extend(texts)
        return [t + " (en)" for t in texts]

    def refine(texts, drafts, before, after):
        refined.append((list(drafts), list(before), list(after)))
        return [d.replace("(en)", "(polished)") for d in drafts]

    cues = [
        Cue(start=0, end=1, text="앞 문장"),
        Cue(start=1, end=2, text="뉴진스 노래 2곡"),
        Cue(start=2, end=3, text="뒤 문장"),
    ]
    out, stats = script.translate_cues(
        cues,
        source="ko",
        target="en",
        entries={"뉴진스": "NewJeans"},
        translate=translate,
        memory=script.FileMemory(None, "t"),
        refine=refine,
        max_lines=1,
    )
    assert all("뉴진스" not in t and "2곡" not in t for t in seen)
    assert out[1].text == "NewJeans 노래 2곡 (polished)"
    assert refined[1] == (["NewJeans 노래 2곡 (en)"], ["앞 문장"], ["뒤 문장"])
    assert stats == {"batches": 3, "sent": 3, "cached": 0, "lost_placeholders": 0}
