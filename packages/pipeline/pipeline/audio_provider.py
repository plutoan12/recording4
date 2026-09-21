"""기존 워커 이미지 안에서 실행하는 로컬 음성 타이밍 공급자."""

import argparse
import json
from pathlib import Path


def extract(audio, script=None, model="small", language="ko"):
    if script is not None:
        import stable_whisper

        engine = stable_whisper.load_faster_whisper(model, device="cpu", compute_type="int8")
        result = engine.align(str(audio), script, language=language)
        if result is None:
            raise ValueError("음성과 대본을 정렬하지 못했습니다.")
        segments = result.segments
        mode = "forced_alignment"
    else:
        from faster_whisper import WhisperModel

        engine = WhisperModel(model, device="cpu", compute_type="int8", local_files_only=True)
        segments, _ = engine.transcribe(
            str(audio), language=language, vad_filter=True, word_timestamps=True
        )
        segments = list(segments)
        mode = "transcription"
    words = [
        dict(text=w.word, start=w.start, end=w.end)
        for s in segments
        for w in (s.words or [])
        if w.word.strip()
    ]
    return dict(
        mode=mode,
        model=model,
        language=language,
        text=script if script is not None else "".join(w["text"] for w in words),
        words=words,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ko")
    args = parser.parse_args()
    text = args.script.read_text(encoding="utf-8") if args.script else None
    result = extract(args.audio, text, args.model, args.language)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
