"""외부 공개 문서를 참고해 직접 구현한 ASS 모션 자막 템플릿."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
import pysubs2

from pipeline.interchange import read_subtitles, serialize
from pipeline.template_factory import wrap_text

PRESETS = {
    "interview": dict(
        label="INTERVIEW",
        background="101F28",
        accent="7DE0CC",
        color="FFFFFF",
        x=210,
        y=820,
        size=62,
        align=4,
        width=1400,
        motion="slide",
    ),
    "news": dict(
        label="NEWS / BRIEF",
        background="101E3B",
        accent="F25464",
        color="FFFFFF",
        x=230,
        y=857,
        size=56,
        align=4,
        width=1430,
        motion="slide",
    ),
    "cinema": dict(
        label="CINEMATIC",
        background="14181D",
        accent="D6BB80",
        color="FFF7E4",
        x=960,
        y=830,
        size=58,
        align=5,
        width=1550,
        motion="fade",
    ),
    "pop": dict(
        label="KEY POINT",
        background="49208A",
        accent="DBFF79",
        color="DBFF79",
        x=960,
        y=560,
        size=106,
        align=5,
        width=1550,
        motion="pop",
    ),
    "chapter": dict(
        label="CHAPTER / 01",
        background="EEE8DF",
        accent="E45736",
        color="22252A",
        x=200,
        y=550,
        size=78,
        align=4,
        width=1490,
        motion="slide",
    ),
}
# 기존 렌더러와 OFL 글꼴을 재사용하는 두 번째 자체 제작 시리즈.
NEW_PRESETS = {
    "paper": dict(
        label="PAPER / NOTES",
        background="E8E1D3",
        accent="BD4F35",
        color="292D34",
        x=340,
        y=560,
        size=68,
        align=4,
        width=1220,
        motion="rise",
    ),
    "neon": dict(
        label="AFTER HOURS",
        background="111022",
        accent="50F2E5",
        color="FFFFFF",
        x=960,
        y=560,
        size=84,
        align=5,
        width=1400,
        motion="pop",
    ),
    "quote": dict(
        label="IN THEIR WORDS",
        background="193F37",
        accent="E6C889",
        color="FFF5E2",
        x=400,
        y=555,
        size=70,
        align=4,
        width=1150,
        motion="fade",
    ),
    "terminal": dict(
        label="FIELD LOG / 004",
        background="111A18",
        accent="A6F59B",
        color="D4F8CE",
        x=340,
        y=560,
        size=64,
        align=4,
        width=1240,
        motion="wipe",
    ),
    "split": dict(
        label="TWO SIDES",
        background="E7EDFA",
        accent="2E4DE6",
        color="1D2C69",
        x=760,
        y=555,
        size=66,
        align=4,
        width=920,
        motion="slide",
    ),
    "card": dict(
        label="A LITTLE UPDATE",
        background="F3DEE7",
        accent="AC426D",
        color="3C2532",
        x=960,
        y=570,
        size=70,
        align=5,
        width=1280,
        motion="rise",
    ),
}
PRESETS.update(NEW_PRESETS)

TYPE_PRESETS = {
    "typewriter": dict(
        label="WORDS / IN PROGRESS",
        background="F1EFE6",
        accent="D44329",
        color="242529",
        x=300,
        y=550,
        size=76,
        align=4,
        width=1300,
        motion="letters",
    ),
    "punch": dict(
        label="MAKE IT COUNT",
        background="FFD73E",
        accent="282517",
        color="161610",
        x=960,
        y=550,
        size=90,
        align=5,
        width=1320,
        motion="punch",
    ),
    "cascade": dict(
        label="LINE BY LINE",
        background="1830A0",
        accent="ADF5DE",
        color="FFFFFF",
        x=340,
        y=540,
        size=84,
        align=4,
        width=1220,
        motion="lines",
    ),
    "stamp": dict(
        label="SAY IT / LOUD",
        background="F3E8D8",
        accent="CF392C",
        color="CF392C",
        x=960,
        y=545,
        size=86,
        align=5,
        width=1300,
        motion="stamp",
    ),
}
PRESETS.update(TYPE_PRESETS)


def animated_text(text, motion, duration):
    """Layout keeps the full text width while alpha reveals characters or lines."""
    if motion not in {"letters", "lines", "punch"}:
        return literal(text)
    window = min(900, duration // 3)
    if motion == "punch":
        first, separator, rest = text.partition(" ")
        return (
            r"{\fscx120\fscy120}"
            + literal(first)
            + r"{\fscx100\fscy100}"
            + literal(separator + rest)
        )
    parts = list(text) if motion == "letters" else text.splitlines()
    output = []
    for i, part in enumerate(parts):
        delay = window * i // max(1, len(parts) - 1)
        output.append(r"{\alpha&HFF&\t(" + f"{delay},{delay+1}" + r",\alpha&H00&)}" + literal(part))
    return ("" if motion == "letters" else r"\N").join(output)


SOURCES = [
    dict(
        url="https://mixkit.co/free-after-effects-templates/lower-thirds/",
        use="이름표·뉴스 배너 유형 참고. 템플릿 파일/코드/미디어는 복사하지 않음.",
    ),
    dict(
        url="https://mixkit.co/free-premiere-pro-templates/titles/",
        use="타이틀 유형 참고. 구체적인 레이아웃과 코드는 자체 구현.",
    ),
    dict(
        url="https://m1.material.io/motion/duration-easing.html",
        use="짧은 등장/퇴장과 거리별 시간 조정 원칙 참고.",
    ),
    dict(
        url="https://aegisub.org/docs/latest/ass_tags/",
        use="ASS move, fad, t, 벡터 drawing 공식 문법을 구현에 사용.",
    ),
    dict(
        url="https://github.com/google/fonts/tree/main/ofl/notosanskr",
        use="Noto Sans KR 원본 폰트 사용. SIL OFL 1.1과 저작권 고지 동봉.",
    ),
]


def bgr(rgb):
    return rgb[4:6] + rgb[2:4] + rgb[0:2]


def literal(text):
    # 사용자 대사에서 ASS 태그를 실행하지 않음. 대체 사실은 report에 명시.
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", r"\N")


def create(subs, name):
    p = PRESETS[name]
    cues = sorted(
        [e for e in subs if not e.is_comment and not e.is_drawing and e.plaintext.strip()],
        key=lambda e: e.start,
    )
    if not cues:
        raise ValueError("표시할 자막이 없습니다.")
    if any(b.start < a.end for a, b in zip(cues, cues[1:], strict=False)):
        raise ValueError("모션 템플릿은 겹치지 않는 자막을 사용하세요.")
    duration = max(e.end for e in cues) + 500
    result = pysubs2.SSAFile()
    result.info.update(PlayResX="1920", PlayResY="1080", WrapStyle="2", ScaledBorderAndShadow="yes")
    result.styles["Default"] = pysubs2.SSAStyle(
        fontname="Noto Sans KR", fontsize=p["size"], outline=0, shadow=0, bold=True
    )

    def event(text, start=0, end=duration, layer=0):
        result.append(pysubs2.SSAEvent(start=start, end=end, text=text, layer=layer))

    def box(x, y, w, h, color, start=0, end=duration, fade=False):
        tags = rf"\an7\pos({x},{y})\p1\bord0\shad0\c&H{bgr(color)}&"
        if fade:
            ms = min(160, (end - start) // 4)
            tags += rf"\fad({ms},{ms})"
        event("{" + tags + "}" + f"m 0 0 l {w} 0 l {w} {h} l 0 {h}", start, end)

    def label(text, x, y, color, size=28):
        event(
            r"{\an7\pos(" + f"{x},{y}" + r")\fs" + str(size) + r"\c&H" + bgr(color) + "&}" + text,
            layer=1,
        )

    # 직접 제작한 장식 요소. 기존 이미지 또는 외부 유료 템플릿 불필요.
    label(p["label"], 160, 115, p["accent"])
    label("RECORDING4  /  MOTION TYPE", 160, 990, p["accent"], 20)
    box(160, 175, 90, 5, p["accent"])
    if name == "interview":
        box(1300, 200, 450, 450, "183642")
        box(1370, 270, 310, 310, "20505A")
    elif name == "news":
        for x in range(180, 1800, 180):
            box(x, 250, 2, 400, "1D3454")
        for y in range(250, 651, 100):
            box(180, y, 1620, 2, "1D3454")
    elif name == "cinema":
        box(0, 0, 1920, 75, "080A0D")
        box(0, 930, 1920, 150, "080A0D")
        box(825, 420, 270, 2, p["accent"])
        label("STORIES IN MOTION", 770, 460, p["accent"], 28)
    elif name == "pop":
        box(1480, 200, 160, 160, "6438A3")
        box(240, 770, 90, 90, "6438A3")
    elif name == "chapter":
        label("01", 1390, 250, "D7CFC3", 240)
        box(160, 400, 10, 300, p["accent"])
    elif name == "paper":
        box(265, 320, 1400, 480, "D2C7B4")
        box(245, 300, 1400, 480, "FFF9ED")
        for y in range(410, 750, 85):
            box(290, y, 1310, 2, "E5DFD2")
        box(310, 330, 3, 400, "E7A79B")
        label("NOTES TO REMEMBER", 340, 340, p["accent"], 24)
    elif name == "neon":
        for x, y, w, h in [
            (240, 330, 1440, 4),
            (240, 750, 1440, 4),
            (240, 330, 4, 420),
            (1676, 330, 4, 420),
        ]:
            box(x, y, w, h, p["accent"])
        box(1450, 240, 180, 10, "D865F4")
        box(290, 825, 180, 10, "D865F4")
    elif name == "quote":
        label("“", 235, 280, p["accent"], 260)
        box(400, 735, 1100, 2, "668477")
        label("A MOMENT WORTH KEEPING", 400, 775, p["accent"], 22)
    elif name == "terminal":
        box(250, 290, 1420, 510, "20312B")
        box(252, 350, 1416, 448, "16231E")
        label("LOG  /  CAPTIONS.TXT", 300, 305, p["accent"], 24)
        label(">", 290, 525, p["accent"], 50)
        label("STATUS: READY", 300, 730, "739A78", 22)
    elif name == "split":
        box(160, 300, 490, 500, p["accent"])
        label("POINT", 215, 355, "C9D4FF", 30)
        label("01", 205, 435, "FFFFFF", 200)
        box(705, 340, 4, 400, "B7C4EE")
    elif name == "card":
        box(285, 360, 1370, 415, "DBB7C7")
        box(265, 340, 1370, 415, "FFF8FB")
        box(325, 405, 60, 60, p["accent"])
        label("TODAY / 오늘의 한마디", 425, 417, p["accent"], 28)
    elif name == "typewriter":
        box(250, 310, 1420, 460, "FFFFFF")
        box(300, 720, 1300, 3, "D5D3C9")
        label("DRAFT 003", 300, 350, p["accent"], 25)
        box(1550, 350, 45, 10, p["accent"])
    elif name == "punch":
        box(160, 265, 1600, 8, p["accent"])
        box(160, 815, 1600, 8, p["accent"])
        label("BIG WORDS. CLEAR MESSAGE.", 610, 730, p["accent"], 28)
    elif name == "cascade":
        for y, w in [(350, 220), (390, 150), (430, 80)]:
            box(340, y, w, 8, p["accent"])
        box(300, 480, 5, 250, p["accent"])
        label("ONE THOUGHT AT A TIME", 340, 790, p["accent"], 25)
    elif name == "stamp":
        box(230, 300, 1460, 8, p["accent"])
        box(230, 785, 1460, 8, p["accent"])
        box(230, 300, 8, 493, p["accent"])
        box(1682, 300, 8, 493, p["accent"])
        label("APPROVED / YOUR NEXT IDEA", 670, 715, p["accent"], 28)
    for cue in cues:
        text = wrap_text(cue.plaintext, p["width"], p["size"])
        if len(text.splitlines()) > 2:
            raise ValueError(f"{name}: 두 줄을 넘습니다. 긴 대사를 나눠 주세요.")
        ms = min(240, (cue.end - cue.start) // 4)
        if name == "interview":
            box(160, 700, 1510, 240, "203A46", cue.start, cue.end, True)
            box(160, 700, 12, 240, p["accent"], cue.start, cue.end, True)
        elif name == "news":
            box(160, 725, 320, 55, p["accent"], cue.start, cue.end, True)
            box(160, 790, 1600, 150, "203660", cue.start, cue.end, True)
        tags = rf'\an{p["align"]}\c&H{bgr(p["color"])}&\fad({ms},{ms})'
        if p["motion"] == "slide":
            tags += rf'\move({p["x"]-45},{p["y"]},{p["x"]},{p["y"]},0,{ms})'
        elif p["motion"] == "rise":
            tags += rf'\move({p["x"]},{p["y"]+32},{p["x"]},{p["y"]},0,{ms})'
        else:
            tags += rf'\pos({p["x"]},{p["y"]})'
        if p["motion"] == "pop":
            tags += rf"\fscx88\fscy88\t(0,{ms},0.6,\fscx100\fscy100)"
        if p["motion"] == "wipe":
            tags += rf"\clip(0,0,0,1080)\t(0,{ms},\clip(0,0,1920,1080))"
        if p["motion"] == "punch":
            tags += rf"\fscx75\fscy75\t(0,{ms},\fscx112\fscy112)"
            tags += rf"\t({ms},{ms*2},\fscx100\fscy100)"
        if p["motion"] == "stamp":
            tags += rf"\frz-6\fscx150\fscy150\t(0,{ms},\frz0\fscx100\fscy100)"
        if name == "neon":
            tags += r"\bord2\blur3\3c&H" + bgr(p["accent"]) + "&"
        event(
            "{" + tags + "}" + animated_text(text, p["motion"], cue.end - cue.start),
            cue.start,
            cue.end,
            2,
        )
    return result, duration


def build(source, output, fonts, names, render=True, encoding=None):
    if output.exists():
        raise ValueError("새 출력 폴더를 지정하세요. 기존 결과는 덮어쓰지 않습니다.")
    for filename in ("NotoSansKR.ttf", "OFL.txt"):
        if not (fonts / filename).is_file():
            raise ValueError(f"필요한 글꼴/라이선스: {fonts/filename}")
    subs, notes = read_subtitles(source, encoding)
    designed = [(name, *create(subs, name)) for name in names]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".motion-", dir=output.parent) as tmp:
        root = Path(tmp) / "result"
        root.mkdir()
        shutil.copytree(fonts, root / "fonts")
        (root / "sources.json").write_text(
            json.dumps(SOURCES, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "presets.json").write_text(json.dumps({n: PRESETS[n] for n in names}, indent=2))
        for name, design, duration in designed:
            folder = root / name
            folder.mkdir()
            (folder / "editable.ass").write_text(design.to_string("ass"), encoding="utf-8")
            (folder / "captions.srt").write_text(serialize(subs, "srt")[0], encoding="utf-8")
            if render:
                cmd = [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-n",
                    "-f",
                    "lavfi",
                    "-i",
                    f'color=c=0x{PRESETS[name]["background"]}:s=1920x1080:r=30',
                    "-vf",
                    "ass=editable.ass:fontsdir=../fonts",
                    "-t",
                    str(duration / 1000),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "preview.mp4",
                ]
                subprocess.run(cmd, cwd=folder, check=True, capture_output=True, text=True)
        report = {
            "presets": names,
            "rendered": render,
            "notes": notes,
            "font_sha256": hashlib.sha256((fonts / "NotoSansKR.ttf").read_bytes()).hexdigest(),
            "limits": [
                "외부 템플릿 파일을 변환한 것이 아닌 자체 구현 디자인입니다.",
                "MP4는 무음 합성 영상, ASS는 편집 가능한 자막/벡터/모션입니다.",
                "MOGRT/CapCut/Fusion 네이티브 프로젝트는 포함하지 않습니다.",
                "SRT에는 스타일/모션이 없습니다. ASS의 표시도 렌더러 지원에 따릅니다.",
                "대사의 중괄호와 역슬래시는 ASS 명령 해석 방지를 위해 전각으로 바꿉니다.",
            ],
        }
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        root.rename(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description="자체 제작 모션 자막 15종")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fonts", type=Path, default=Path(".runtime/external-fonts"))
    parser.add_argument("--preset", choices=[*PRESETS, "all"], default="all")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--encoding")
    args = parser.parse_args(argv)
    try:
        build(
            args.input,
            args.output,
            args.fonts,
            list(PRESETS) if args.preset == "all" else [args.preset],
            not args.no_render,
            args.encoding,
        )
    except subprocess.CalledProcessError as exc:
        parser.exit(2, "렌더 실패: " + exc.stderr[-1000:] + "\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"제작 실패: {exc}\n")
    print(f"생성 완료: {args.output}")


if __name__ == "__main__":
    main()
