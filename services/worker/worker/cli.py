"""Local-file entrypoint: python -m worker.cli --help. No database or paid API needed."""

import argparse
import json
from pathlib import Path

from pipeline.editing import Cue, EditSpec, suggest_clips
from worker.analysis import detect_scenes, transcribe
from worker.rendering import render_clip


def main():
    parser = argparse.ArgumentParser(description="recording4 로컬 영상 도구")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("source", type=Path)
    render.add_argument("spec", type=Path)
    render.add_argument("output", type=Path)
    stt = sub.add_parser("transcribe")
    stt.add_argument("source", type=Path)
    stt.add_argument("output", type=Path)
    stt.add_argument("--model", default="small")
    stt.add_argument("--language")
    scenes = sub.add_parser("scenes")
    scenes.add_argument("source", type=Path)
    scenes.add_argument("output", type=Path)
    suggest = sub.add_parser("suggest")
    suggest.add_argument("transcript", type=Path)
    suggest.add_argument("output", type=Path)
    suggest.add_argument("--duration", type=float, required=True)
    args = parser.parse_args()
    if args.command == "render":
        render_clip(args.source, args.output, EditSpec.model_validate_json(args.spec.read_text()))
        return
    if args.command == "transcribe":
        result = [
            c.model_dump()
            for c in transcribe(args.source, model=args.model, language=args.language)
        ]
    elif args.command == "scenes":
        result = detect_scenes(args.source)
    else:
        cues = [Cue.model_validate(c) for c in json.loads(args.transcript.read_text())]
        result = suggest_clips(cues, duration=args.duration)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
