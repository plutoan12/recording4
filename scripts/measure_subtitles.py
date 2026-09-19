#!/usr/bin/env python3
"""자막 기본값이 숏폼 세로 화면에서 실제로 맞는지 렌더해서 잽니다.

libass로 한 프레임을 그린 뒤 밝은 화소의 경계를 직접 찾습니다. 폰트 메트릭
계산이 아니라 실제 렌더 결과입니다. FFmpeg와 한국어 글꼴, numpy가 필요하므로
워커 이미지 안에서 돌립니다.

    docker run --rm -v "$PWD/scripts:/work" --entrypoint python \
        recording4-worker:ci /work/measure_subtitles.py

검사 기준은 두 가지입니다.

1. 기본 줄 길이(16자)가 좌우 여백 안에 들어갈 것. 넘으면 libass가 제멋대로
   다시 줄바꿈해서 우리 줄 규칙이 화면에서 깨집니다.
2. 기본 줄 길이가 한 줄로 그려질 것. 두 줄이 되면 같은 문제입니다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from pipeline.editing import Cue, EditSpec
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, rules_for, text_width
from worker.rendering import ffmpeg_binary, write_subtitles

# 배경(제한 범위 검정, Y=16)과 검은 외곽선을 빼고 글자만 남기는 문턱입니다.
INK = 32

# 한국어 실사용 문장. 같은 글자 반복보다 자간·받침 폭이 현실적입니다.
SAMPLE = "다람쥐 헌 쳇바퀴에 타고파 오늘도 즐겁게 달린다 정말로"


def measure(text: str, spec: EditSpec, rules: SubtitleRules) -> tuple[int, int] | None:
    """글자가 그려진 픽셀 상자 (가로, 세로)를 돌려줍니다. 안 보이면 None.

    FFmpeg cropdetect는 레터박스용이라 행·열 평균으로 판정합니다. 세로 1920px
    중 자막 100px만 밝으면 열 평균이 문턱을 못 넘어 폭을 못 잽니다. 그래서
    회색조 원본 프레임을 받아 밝은 화소의 경계를 직접 찾습니다.
    """
    with tempfile.TemporaryDirectory(prefix="r4-measure-") as directory:
        temp = Path(directory)
        write_subtitles(temp / "captions.ass", spec, rules)
        command = [
            ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={spec.width}x{spec.height}:d=1",
            "-vf",
            "subtitles=captions.ass,format=gray",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
        done = subprocess.run(command, cwd=temp, capture_output=True, timeout=120)
    expected = spec.width * spec.height
    if done.returncode or len(done.stdout) < expected:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-4:]
        print(f"  (FFmpeg 종료 코드 {done.returncode}, {len(done.stdout)}바이트)")
        for line in tail:
            print(f"  {line}")
        return None
    frame = np.frombuffer(done.stdout[:expected], dtype=np.uint8).reshape(spec.height, spec.width)
    mask = frame > INK
    rows = np.nonzero(mask.any(axis=1))[0]
    columns = np.nonzero(mask.any(axis=0))[0]
    if not rows.size or not columns.size:
        return None
    return int(columns[-1] - columns[0] + 1), int(rows[-1] - rows[0] + 1)


def spec_for(text: str, font_size: int, width: int, height: int) -> EditSpec:
    return EditSpec(
        start=0,
        end=5,
        width=width,
        height=height,
        font_size=font_size,
        cues=[Cue(start=0, end=5, text=text)],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-size", type=int, default=64)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    args = parser.parse_args()

    # write_subtitles가 쓰는 좌우 여백과 같은 값입니다.
    margin = 50
    usable = args.width - margin * 2
    print(f"화면 {args.width}x{args.height}, 글자 크기 {args.font_size}, 좌우 여백 {margin}px")
    print(f"글자가 쓸 수 있는 가로 폭 {usable}px\n")

    # 줄 길이별 실제 렌더 폭. 규칙이 다시 줄바꿈하지 않도록 한도를 넉넉히 둡니다.
    print(f"{'한글 글자 수':>12} {'렌더 폭(px)':>12} {'화면 대비':>10} {'여백 안':>8}")
    single_line = SubtitleRules(max_chars_per_line=200, max_lines=9)
    fits = 0
    for count in (8, 10, 12, 14, 16, 18, 20):
        text = "가" * count
        box = measure(text, spec_for(text, args.font_size, args.width, args.height), single_line)
        if box is None:
            print(f"{count:>12} {'측정 실패':>12}")
            continue
        pixels, _ = box
        inside = pixels <= usable
        fits = max(fits, count) if inside else fits
        print(
            f"{count:>12} {pixels:>12} {pixels / args.width:>9.0%} "
            f"{'예' if inside else '아니오':>8}"
        )
    print(f"\n글자 크기 {args.font_size}에서 여백 안에 들어가는 한글 글자 수: {fits}자까지")

    # 기본 규칙 그대로 그린 결과. 한 줄인지 두 줄인지 높이로 봅니다.
    print()
    one = measure("가", spec_for("가", args.font_size, args.width, args.height), DEFAULT_RULES)
    full = "가" * DEFAULT_RULES.max_chars_per_line
    filled = measure(full, spec_for(full, args.font_size, args.width, args.height), DEFAULT_RULES)
    sample_box = measure(
        SAMPLE, spec_for(SAMPLE, args.font_size, args.width, args.height), single_line
    )
    if one is None or filled is None or sample_box is None:
        print("자막이 그려지지 않았습니다. 글꼴과 FFmpeg subtitles 필터를 확인하세요.")
        return 1

    line_height = one[1]
    print(f"한 줄 높이 {line_height}px (화면 세로의 {line_height / args.height:.0%})")
    print(f"기본 한도({DEFAULT_RULES.max_chars_per_line}자) 한 줄: {filled[0]}x{filled[1]}px")
    print(f"예문 '{SAMPLE}' (폭 {text_width(SAMPLE):.1f}자): {sample_box[0]}px")

    # 영어 자막은 지침이 달라 줄이 더 깁니다(42자). 폭으로는 21이라 한글
    # 16자보다 큽니다. 같은 화면에 들어가는지 직접 재야 합니다.
    english_rules = rules_for("en")
    english = "M" * int(english_rules.max_chars_per_line * 2)
    english_box = measure(
        english, spec_for(english, args.font_size, args.width, args.height), single_line
    )
    if english_box is None:
        print("영어 자막이 그려지지 않았습니다.")
        return 1
    print(
        f"영어 한도({len(english)}자, 폭 {text_width(english):.1f}) 한 줄: "
        f"{english_box[0]}x{english_box[1]}px ({english_box[0] / args.width:.0%})"
    )

    problems = []
    if english_box[0] > usable:
        problems.append(
            f"영어 줄 길이 {len(english)}자가 {english_box[0]}px로 여백 안({usable}px)을 "
            "넘습니다. 영어 기본값을 줄이거나 글자 크기를 낮춰야 합니다."
        )
    if filled[0] > usable:
        problems.append(
            f"기본 줄 길이 {DEFAULT_RULES.max_chars_per_line}자가 {filled[0]}px로 "
            f"여백 안({usable}px)을 넘습니다. libass가 다시 줄바꿈합니다."
        )
    # 두 줄이면 높이가 대략 두 배가 됩니다. 1.5배를 경계로 봅니다.
    if filled[1] > line_height * 1.5:
        problems.append(
            f"기본 줄 길이가 한 줄로 안 들어갑니다(높이 {filled[1]}px, 한 줄 {line_height}px)."
        )
    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n기본 줄 길이가 숏폼 화면의 여백 안에 한 줄로 들어갑니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
