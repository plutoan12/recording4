#!/usr/bin/env python3
"""자막 기본값이 숏폼 세로 화면에서 실제로 맞는지 렌더해서 잽니다.

libass로 한 프레임을 그린 뒤 밝은 화소의 경계를 직접 찾습니다. 폰트 메트릭
계산이 아니라 실제 렌더 결과입니다. FFmpeg와 한국어 글꼴, numpy가 필요하므로
워커 이미지 안에서 돌립니다.

    docker run --rm -v "$PWD/scripts:/work" --entrypoint python \
        recording4-worker:ci /work/measure_subtitles.py

검사 기준은 세 가지입니다.

1. 기본 줄 길이(한국어 16자)가 좌우 여백 안에 들어갈 것. 넘으면 libass가
   제멋대로 다시 줄바꿈해서 우리 줄 규칙이 화면에서 깨집니다.
2. 기본 줄 길이가 한 줄로 그려질 것. 두 줄이 되면 같은 문제입니다.
3. 영어 줄 한도를 꽉 채운 줄도 여백 안에 들어갈 것.
4. 우리가 끊은 줄이 화면에서 그대로 그려질 것. 한 줄이 넘치면 libass가 제
   마음대로 다시 줄바꿈해서 두 줄이 세 줄이 됩니다. 폭만 재면 이건 안 보입니다.
   줄을 세어야 압니다.
5. 줄이 늘어도 세로로 제자리에 있을 것. 자막은 화면 아래에 붙고 줄이 늘면
   **위로** 자랍니다. 설정한 아래 여백이 지켜지는지, 화면 밖이나 제목까지
   올라가지 않는지 봅니다.

**넘친 줄의 픽셀 값은 믿지 마세요.** 밝은 화소의 상자는 화면 가장자리에서
멈추므로, 넘치면 글자 폭이 아니라 화면 폭이 나옵니다. 그래서 넘친 줄은
숫자 대신 "넘침"으로 찍습니다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from pipeline.editing import Cue, EditSpec
from pipeline.subtitles import (
    DEFAULT_RULES,
    SubtitleRules,
    apply_rules,
    rules_for,
    text_width,
    wrap_text,
)
from worker.rendering import ffmpeg_binary, write_subtitles

# 배경(제한 범위 검정, Y=16)과 검은 외곽선을 빼고 글자만 남기는 문턱입니다.
INK = 32

# 글자가 화면 밖으로 넘쳐 폭을 잴 수 없을 때. 숫자가 아니어야 실수로 픽셀
# 값처럼 쓰이지 않습니다. 넘쳤다는 사실만으로도 "여백 안에 안 들어간다"는
# 판정에는 충분합니다.
OVERFLOW = "넘침"

# 한국어 실사용 문장. 같은 글자 반복보다 자간·받침 폭이 현실적입니다.
SAMPLE = "다람쥐 헌 쳇바퀴에 타고파 오늘도 즐겁게 달린다 정말로"

# 영어 실사용 문장. 라틴 글자는 폭이 제각각이라(i와 M이 몇 배 차이) 같은
# 글자를 반복해 재면 실제 자막과 딴판입니다.
ENGLISH_SAMPLE = "In March last year a colleague of the former minister was appointed"

# 판정용 한 줄. 문장은 어절 경계에서 끊겨 한도를 꽉 채우지 못합니다(위 문장은
# 폭 19 한도에 18.5까지). 한도를 다 쓴 줄이 들어가는지 보려면 한도만큼 채운
# 줄이 필요합니다. 알파벳 한 바퀴는 실제 문장의 글자 분포에 가깝고 공백이
# 없어 오히려 조금 넓습니다.
ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# 세로 위치를 볼 때 쓰는 글. 줄 길이만 바꾸면 같은 글이 2·3·5줄이 됩니다.
VERTICAL_SAMPLE = "다람쥐 헌 쳇바퀴에 타고파 오늘도 즐겁게"
TITLE_SAMPLE = "화면 제목"


def render_mask(spec: EditSpec, rules: SubtitleRules) -> np.ndarray | None:
    """자막을 한 프레임에 그리고 글자 화소만 True인 배열을 돌려줍니다. 실패면 None.

    FFmpeg cropdetect는 레터박스용이라 행·열 평균으로 판정합니다. 세로 1920px
    중 자막 100px만 밝으면 열 평균이 문턱을 못 넘어 폭을 못 잽니다. 그래서
    회색조 원본 프레임을 받아 밝은 화소를 직접 봅니다.
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
    return frame > INK


def measure(spec: EditSpec, rules: SubtitleRules) -> tuple[int, int] | str | None:
    """글자가 그려진 픽셀 상자 (가로, 세로)를 돌려줍니다.

    안 보이면 None, 화면 밖으로 넘쳐 잴 수 없으면 OVERFLOW입니다.
    """
    mask = render_mask(spec, rules)
    if mask is None:
        return None
    rows = np.nonzero(mask.any(axis=1))[0]
    columns = np.nonzero(mask.any(axis=0))[0]
    if not rows.size or not columns.size:
        return None
    if columns[0] == 0 or columns[-1] == spec.width - 1:
        # 글자가 프레임 밖으로 나갔습니다. 밝은 화소의 상자는 화면 가장자리에서
        # 멈추므로 여기서 숫자를 돌려주면 글자 폭이 아니라 화면 폭이 나옵니다.
        # 실제로 그렇게 나왔습니다: 영어 30자부터 42자까지 전부 1068px로 찍혀
        # 42자를 1068px이라고 적었는데, 그건 측정이 아니라 잘린 값이었습니다.
        return OVERFLOW
    return int(columns[-1] - columns[0] + 1), int(rows[-1] - rows[0] + 1)


def bands(mask: np.ndarray) -> list[tuple[int, int]]:
    """글자가 그려진 세로 구간들 (위 행, 아래 행). 글자가 없는 행으로 끊습니다."""
    ink = mask.any(axis=1)
    found: list[tuple[int, int]] = []
    top: int | None = None
    for index, lit in enumerate(ink):
        if lit and top is None:
            top = index
        elif not lit and top is not None:
            found.append((top, index - 1))
            top = None
    if top is not None:
        found.append((top, len(ink) - 1))
    return found


def drawn_lines(mask: np.ndarray) -> list[tuple[int, int]]:
    """실제로 그려진 줄들의 (가로, 세로) 픽셀.

    폭만 재면 우리가 넣은 줄바꿈이 화면에서 지켜지는지 알 수 없습니다. 한 줄이
    여백을 넘으면 libass가 제 마음대로 다시 줄바꿈해서 두 줄이 세 줄이 됩니다.
    그러면 자막이 다른 자리에서 끊기고 화면 위로 더 올라갑니다.

    외곽선과 그림자 때문에 줄 사이가 붙으면 두 줄이 한 덩어리로 보일 수
    있습니다. 그래서 **줄이 더 많이 그려진 경우만** 문제로 셉니다. 적게 나온
    것은 세는 방법의 한계일 수 있으므로 적어만 둡니다.
    """
    found: list[tuple[int, int]] = []
    for start, end in bands(mask):
        columns = np.nonzero(mask[start : end + 1].any(axis=0))[0]
        if columns.size:
            found.append((int(columns[-1] - columns[0] + 1), int(end - start + 1)))
    return found


def spec_for(text: str, font_size: int, width: int, height: int, title: str = "") -> EditSpec:
    return EditSpec(
        start=0,
        end=5,
        width=width,
        height=height,
        font_size=font_size,
        title=title,
        cues=[Cue(start=0, end=5, text=text)],
    )


def table(header, counts, make, args, rules: SubtitleRules, usable: int) -> int:
    """글자 수를 늘려 가며 렌더 폭을 찍고, 여백 안에 들어간 최대 글자 수를 돌려줍니다.

    통과/실패만 알려 주면 얼마나 줄여야 하는지 알 수 없어 표로 찍습니다.
    넘친 줄은 픽셀 값을 찍지 않습니다. 그 숫자는 글자 폭이 아니라 화면
    폭입니다.
    """
    print(f"\n{header:>14} {'렌더 폭(px)':>12} {'화면 대비':>10} {'여백 안':>8}")
    fits = 0
    for count in counts:
        text = make(count)
        box = measure(spec_for(text, args.font_size, args.width, args.height), rules)
        if box is None:
            print(f"{count:>14} {'측정 실패':>12}")
            continue
        if box is OVERFLOW:
            print(f"{count:>14} {OVERFLOW:>12} {'-':>10} {'아니오':>8}")
            continue
        inside = box[0] <= usable
        fits = max(fits, count) if inside else fits
        print(
            f"{count:>14} {box[0]:>12} {box[0] / args.width:>9.0%} "
            f"{'예' if inside else '아니오':>8}"
        )
    return fits


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

    single_line = SubtitleRules(max_chars_per_line=200, max_lines=9)
    korean_fits = table(
        "한글 글자 수", range(8, 30, 2), lambda n: "가" * n, args, single_line, usable
    )
    print(f"\n글자 크기 {args.font_size}에서 여백 안에 들어가는 한글 글자 수: {korean_fits}자까지")

    # 기본 규칙 그대로 그린 결과. 한 줄인지 두 줄인지 높이로 봅니다.
    print()
    one = measure(spec_for("가", args.font_size, args.width, args.height), DEFAULT_RULES)
    full = "가" * DEFAULT_RULES.max_chars_per_line
    filled = measure(spec_for(full, args.font_size, args.width, args.height), DEFAULT_RULES)
    sample_box = measure(spec_for(SAMPLE, args.font_size, args.width, args.height), single_line)
    if one is None or filled is None:
        print("자막이 그려지지 않았습니다. 글꼴과 FFmpeg subtitles 필터를 확인하세요.")
        return 1
    if OVERFLOW in (one, filled):
        print(
            f"기본 규칙으로 그린 자막이 화면 밖으로 나갔습니다({OVERFLOW}). 규칙이 화면보다 큽니다."
        )
        return 1

    line_height = one[1]
    print(f"한 줄 높이 {line_height}px (화면 세로의 {line_height / args.height:.0%})")
    print(f"기본 한도({DEFAULT_RULES.max_chars_per_line}자) 한 줄: {filled[0]}x{filled[1]}px")
    drawn = f"{sample_box[0]}px" if isinstance(sample_box, tuple) else str(sample_box)
    print(f"예문 '{SAMPLE}' (폭 {text_width(SAMPLE):.1f}자): {drawn}")

    # 영어는 두 가지로 잽니다. 실제 자막에 가까운 것은 문장이고, 반복 M은
    # 최악의 글자입니다. 판정은 문장으로 합니다. 라틴 글자는 폭이 제각각이라
    # (i와 M이 몇 배 차이) M 반복을 기준으로 삼으면 실제 문장에 비해 한 줄이
    # 지나치게 짧아집니다. M 표는 참고로만 찍습니다.
    english_rules = rules_for("en")
    limit = int(english_rules.max_chars_per_line * 2)
    full_line = (ALPHABET * (limit // len(ALPHABET) + 1))[:limit]
    english_box = measure(spec_for(full_line, args.font_size, args.width, args.height), single_line)
    sentence = wrap_text(ENGLISH_SAMPLE, english_rules)[0]
    sentence_box = measure(spec_for(sentence, args.font_size, args.width, args.height), single_line)
    print(f"\n영어 한 줄 한도 {limit}자(폭 {english_rules.max_chars_per_line})")
    if english_box is None:
        print("  영어 자막이 그려지지 않았습니다.")
        return 1
    print(f"  한도를 채운 줄 '{full_line}' (폭 {text_width(full_line):.1f})")
    if english_box is OVERFLOW:
        print(f"    {OVERFLOW}: 화면 밖으로 나가 폭을 잴 수 없습니다.")
    else:
        print(f"    렌더 폭 {english_box[0]}px (여백 {usable}px의 {english_box[0] / usable:.0%})")
    drawn = f"{sentence_box[0]}px" if isinstance(sentence_box, tuple) else str(sentence_box)
    print(f"  실제 문장 '{sentence}' (폭 {text_width(sentence):.1f}): {drawn}")

    # 참고: 가장 넓은 글자만 반복했을 때. 전부 대문자인 자막은 여기에 걸려
    # libass가 다시 줄바꿈할 수 있습니다.
    worst_fits = table(
        "M 반복 글자 수", range(16, 34, 2), lambda n: "M" * n, args, single_line, usable
    )
    print(f"참고: 가장 넓은 글자 M만 반복하면 {worst_fits}자까지 들어갑니다.")

    problems: list[str] = []

    # 여기까지는 "한 줄이 여백 안에 들어가는가"만 봤습니다. 정작 걱정하던 것은
    # 우리가 끊은 줄이 화면에서 그대로 그려지는가입니다. 한 줄이 넘치면 libass가
    # 제 마음대로 다시 줄바꿈해서 두 줄이 세 줄이 되고, 자막이 다른 자리에서
    # 끊기며 화면 위로 더 올라옵니다. 줄을 세어 봐야 압니다.
    print("\n우리가 끊은 줄이 화면에서 그대로 그려지는가")
    for label, text, rules in (
        ("한글 한 줄", "다람쥐 헌 쳇바퀴에", DEFAULT_RULES),
        ("한글 두 줄", "다람쥐 헌 쳇바퀴에 타고파 오늘도 즐겁게", DEFAULT_RULES),
        ("영어 두 줄", ENGLISH_SAMPLE, english_rules),
    ):
        shaped = apply_rules([Cue(start=0, end=5, text=text)], rules)
        wanted = shaped[0].text.split("\n")
        mask = render_mask(spec_for(text, args.font_size, args.width, args.height), rules)
        if mask is None:
            problems.append(f"{label}: 자막이 그려지지 않았습니다.")
            continue
        found = drawn_lines(mask)
        sizes = ", ".join(f"{w}x{h}" for w, h in found)
        print(f"  {label}: 규칙 {len(wanted)}줄 / 화면 {len(found)}줄  [{sizes}]")
        for line in wanted:
            print(f"      '{line}' (폭 {text_width(line):.1f})")
        if len(found) > len(wanted):
            problems.append(
                f"{label}: 규칙은 {len(wanted)}줄인데 화면에는 {len(found)}줄이 그려졌습니다. "
                "libass가 다시 줄바꿈했습니다. 줄 길이를 줄이거나 글자 크기를 낮추세요."
            )
        elif len(found) < len(wanted):
            # 외곽선·그림자로 줄 사이가 붙으면 한 덩어리로 보입니다. 세는
            # 방법의 한계라 문제로 세지 않고 적어만 둡니다.
            print("      (줄 사이가 붙어 보입니다. 외곽선 때문일 수 있어 문제로 세지 않습니다.)")

    # 세로 위치. 자막은 화면 **아래에 붙고** 줄이 늘면 위로 자랍니다. 그래서
    # 봐야 할 것은 두 가지입니다: 설정한 아래 여백이 지켜지는가, 줄이 늘었을 때
    # 화면 밖이나 제목까지 올라가지 않는가. write_subtitles와 같은 값을 씁니다.
    bottom_margin = int(args.height * 0.13)
    print(f"\n세로 위치 (설정한 아래 여백 {bottom_margin}px)")
    for label, text, line_limit in (
        ("1줄", "다람쥐 헌", 16),
        ("2줄", VERTICAL_SAMPLE, 16),
        ("3줄", VERTICAL_SAMPLE, 8),
        ("5줄", VERTICAL_SAMPLE, 6),
    ):
        # 시간이 모자라 나뉘지 않게 최소 표시 시간을 자막 길이와 같게 둡니다.
        # 줄 수만 바꿔 가며 세로로 얼마나 자라는지 보려는 것입니다.
        rules = SubtitleRules(max_chars_per_line=line_limit, max_lines=9, min_duration=5.0)
        mask = render_mask(spec_for(text, args.font_size, args.width, args.height), rules)
        if mask is None:
            problems.append(f"세로 위치 {label}: 자막이 그려지지 않았습니다.")
            continue
        drawn = bands(mask)
        if not drawn:
            problems.append(f"세로 위치 {label}: 자막이 그려지지 않았습니다.")
            continue
        top, bottom = drawn[0][0], drawn[-1][1]
        gap = args.height - 1 - bottom
        print(
            f"  {label}: 위 {top}px ~ 아래 {bottom}px "
            f"(높이 {bottom - top + 1}px, 화면 아래까지 {gap}px, 줄 {len(drawn)}개)"
        )
        if top <= 0 or bottom >= args.height - 1:
            problems.append(
                f"세로 위치 {label}: 자막이 화면 밖으로 잘립니다(위 {top}, 아래 {bottom})."
            )
        # 외곽선 3px과 그림자 1px이 글자 상자 밖으로 나갑니다. 그만큼 봐줍니다.
        elif gap < bottom_margin - 8:
            problems.append(
                f"세로 위치 {label}: 자막 아래가 화면에서 {gap}px 떨어져 있습니다. "
                f"설정한 여백은 {bottom_margin}px입니다."
            )

    # 제목이 있을 때 자막이 제목까지 올라오는지. 둘이 겹치면 둘 다 못 읽습니다.
    #
    # 겹침은 "구간이 몇 개인가"로 봅니다. 구간은 글자가 없는 행으로 끊으므로
    # 서로 겹친 두 글덩어리는 **한 구간**으로 붙어 버립니다. 제목 없이 그린
    # 자막의 구간 수에 제목 하나를 더한 수가 나와야 둘이 떨어져 있는 것입니다.
    many = SubtitleRules(max_chars_per_line=6, max_lines=9, min_duration=5.0)
    plain = render_mask(spec_for(VERTICAL_SAMPLE, args.font_size, args.width, args.height), many)
    titled = render_mask(
        spec_for(VERTICAL_SAMPLE, args.font_size, args.width, args.height, title=TITLE_SAMPLE),
        many,
    )
    if plain is None or titled is None:
        problems.append("제목과 함께 그린 자막을 재지 못했습니다.")
    else:
        alone, together = bands(plain), bands(titled)
        print(
            f"  제목 포함: 구간 {len(together)}개 (제목 없이 {len(alone)}개 + 제목 1개)"
            + (
                f", 제목 아래 {together[0][1]}px / 자막 위 {together[1][0]}px"
                if len(together) > 1
                else ""
            )
        )
        if len(together) < len(alone) + 1:
            problems.append(
                f"제목과 자막이 한 덩어리로 그려졌습니다(구간 {len(together)}개, "
                f"떨어져 있으면 {len(alone) + 1}개). 겹치면 둘 다 읽기 어려워집니다."
            )

    if english_box is OVERFLOW or english_box[0] > usable:
        measured = OVERFLOW if english_box is OVERFLOW else f"{english_box[0]}px"
        problems.append(
            f"영어 한 줄 한도 {limit}자가 여백 안({usable}px)에 안 들어갑니다(실측 {measured}). "
            "기본값을 줄이거나 글자 크기를 낮추세요."
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
