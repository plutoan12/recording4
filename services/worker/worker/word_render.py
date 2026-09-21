"""선택 구간 음성 정렬과 원본 화면 합성에 쓸 단어 강조 ASS."""

import json
import subprocess
from pathlib import Path

import pysubs2

from pipeline.audio_captions import map_words, pack_words
from pipeline.audio_provider import extract
from pipeline.portrait_captions import create


def write_word_captions(source, directory, spec, binary, model="small"):
    font = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not font.is_file():
        raise ValueError("단어 자막용 Noto Sans CJK 글꼴이 없습니다.")
    audio = directory / "alignment.wav"
    subprocess.run(
        [
            binary,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(spec.start),
            "-i",
            str(source),
            "-t",
            str(spec.end - spec.start),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    raw = extract(audio, spec.caption_script.strip() or None, model, spec.caption_language)
    words = map_words(raw)
    if words[-1]["end_ms"] > round((spec.end - spec.start) * 1000) + 10:
        raise ValueError("정렬된 단어 시각이 선택 구간을 넘습니다.")
    data = pack_words(words, font)
    data["alignment"] = dict(
        mode=raw["mode"],
        model=model,
        language=spec.caption_language,
        source_start_seconds=spec.start,
        timeline="clip-relative",
    )
    design, _ = create(data, font, spec.caption_effect, "pop")
    design.styles["Default"].fontname = "Noto Sans CJK KR"
    if spec.title:
        from worker.rendering import plain_ass

        design.append(
            pysubs2.SSAEvent(
                start=0,
                end=round((spec.end - spec.start) * 1000),
                text=r"{\an8\pos(540,150)\fs64}" + plain_ass(spec.title),
                layer=3,
            )
        )
    design.save(str(directory / "captions.ass"))
    (directory / "words.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
