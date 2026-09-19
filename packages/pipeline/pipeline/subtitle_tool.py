"""자막 파일·템플릿 명령줄 도구. `python -m pipeline.subtitle_tool --help` 또는 `r4-subtitles`.

DB·큐·유료 API 없이 파일만 다룹니다. 서버의 편집기와 같은 코드를 씁니다.
읽기는 `pipeline.subtitle_files`(인코딩 판별·SRT/VTT/ASS 읽기), 표시 규칙은
`pipeline.subtitles`, 모양은 `pipeline.subtitle_templates`입니다. 그래서 여기서
확인한 결과가 서버 렌더와 같습니다.

명령:

- info      파일 요약(인코딩·개수·구간·규칙 위반 수)
- check     표시 규칙 위반 보고. 위반이 있으면 종료 코드 1
- convert   SRT·VTT·ASS를 SRT 또는 VTT로. 글자와 시각은 그대로
- shape     줄바꿈·분할 규칙을 적용해 저장
- shift     시각을 앞뒤로 옮김
- cut       구간만 남기고 구간 시작을 0초로
- templates 내장 템플릿 목록·내용·JSON 내보내기
- style     템플릿 모양의 ASS 파일 만들기
- burn      FFmpeg로 영상에 자막 굽기(FFmpeg 필요)

종료 코드: 0 성공, 1 check에서 위반 발견, 2 입력·환경 오류.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pipeline.editing import Cue, clip_cues
from pipeline.subtitle_files import (
    FORMATS,
    Decoded,
    SubtitleFormat,
    UnknownEncoding,
    decode_subtitles,
    dump_subtitles,
    parse_subtitles,
)
from pipeline.subtitle_templates import (
    BUILTIN_TEMPLATES,
    SubtitleTemplate,
    resolve_template,
    styled_document,
)
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, apply_rules, check, rules_for

EXIT_OK = 0
EXIT_VIOLATIONS = 1
EXIT_ERROR = 2

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1080, 1920
"""style·burn의 기본 화면. 숏폼 세로 화면이며 서버 렌더 기본값과 같습니다."""


class ToolError(Exception):
    """사람에게 보여 줄 오류. 스택 대신 한 줄 메시지와 종료 코드 2로 끝납니다."""


# ---------------------------------------------------------------- 공통 인자


def _add_encoding(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--encoding", help="입력 파일 인코딩. 비우면 BOM → UTF-8 → 판별기 순으로 정합니다."
    )


def _add_output_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=FORMATS,
        help="출력 형식. 비우면 출력 파일 확장자(.srt/.vtt)로 정합니다.",
    )


def _add_rules(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("표시 규칙", "비우면 언어 기본값(한국어 지침)입니다.")
    group.add_argument("--language", help="목표 언어(ko, en 등). 언어별 기본 규칙을 고릅니다.")
    group.add_argument("--max-chars", type=int, help="줄당 최대 글자 폭(한글 1, 라틴 0.5)")
    group.add_argument("--max-lines", type=int, help="자막당 최대 줄 수")
    group.add_argument("--max-cps", type=float, help="초당 최대 글자 폭")
    group.add_argument("--min-duration", type=float, help="자막 최소 표시 시간(초)")
    group.add_argument("--max-duration", type=float, help="자막 최대 표시 시간(초)")


def _add_template(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--template",
        default="default",
        help="내장 템플릿 이름 또는 템플릿 JSON 파일 경로. 기본 default",
    )
    parser.add_argument("--title", default="", help="화면 제목. 자막 반대쪽 끝에 놓입니다.")
    parser.add_argument("--font-size", type=int, help="글자 크기. 템플릿 값보다 우선합니다.")
    parser.add_argument(
        "--no-rules", action="store_true", help="줄바꿈·분할 규칙을 적용하지 않고 그대로 씁니다."
    )


def rules_from(args: argparse.Namespace) -> SubtitleRules:
    """언어 기본값 위에 명시한 값만 덮습니다. 검증은 SubtitleRules가 합니다."""
    base = rules_for(getattr(args, "language", None), DEFAULT_RULES)
    overrides = {
        field: value
        for field, value in (
            ("max_chars_per_line", getattr(args, "max_chars", None)),
            ("max_lines", getattr(args, "max_lines", None)),
            ("max_cps", getattr(args, "max_cps", None)),
            ("min_duration", getattr(args, "min_duration", None)),
            ("max_duration", getattr(args, "max_duration", None)),
        )
        if value is not None
    }
    try:
        return dataclasses.replace(base, **overrides) if overrides else base
    except ValueError as exc:
        raise ToolError(f"표시 규칙이 올바르지 않습니다: {exc}") from None


# ---------------------------------------------------------------- 읽기·쓰기


def read_cues(path: Path, encoding: str | None = None) -> tuple[list[Cue], list[str], Decoded]:
    """파일을 자막으로 읽습니다. (자막, 뺀 것 설명, 어떻게 읽었는지)를 돌려줍니다."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolError(f"파일을 읽지 못했습니다: {path} ({exc.strerror})") from None
    try:
        decoded = decode_subtitles(data, encoding)
    except UnknownEncoding as exc:
        lines = [str(exc)]
        for choice in exc.choices:
            lines.append(f"  --encoding {choice.encoding:<10} → {choice.preview}")
        if not exc.choices:
            lines.append("  자막으로 읽히는 인코딩 후보가 없습니다. 파일 형식을 확인하세요.")
        raise ToolError("\n".join(lines)) from None
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    try:
        cues, notes = parse_subtitles(decoded.text)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return cues, notes, decoded


def output_format(path: Path, explicit: str | None) -> SubtitleFormat:
    if explicit:
        return explicit  # type: ignore[return-value]
    suffix = path.suffix.lower().lstrip(".")
    if suffix in FORMATS:
        return suffix  # type: ignore[return-value]
    if suffix == "ass":
        raise ToolError("ASS 파일은 템플릿 모양이 필요합니다. style 명령을 쓰세요.")
    raise ToolError(f"출력 형식을 알 수 없습니다: {path.name}. --format srt|vtt를 주세요.")


def write_cues(path: Path, cues: list[Cue], subtitle_format: SubtitleFormat) -> None:
    if not cues:
        raise ToolError("남는 자막이 없어 파일을 쓰지 않았습니다.")
    _write_text(path, dump_subtitles(cues, subtitle_format))


def _write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"파일을 쓰지 못했습니다: {path} ({exc.strerror})") from None


def _report_read(path: Path, notes: list[str], decoded: Decoded, cues: list[Cue]) -> None:
    detected = " (자동 판별, 글자를 확인하세요)" if decoded.detected else ""
    print(f"{path.name}: 자막 {len(cues)}개, 인코딩 {decoded.encoding}{detected}", file=sys.stderr)
    for note in notes:
        print(f"  뺌: {note}", file=sys.stderr)


# ---------------------------------------------------------------- 명령


def cmd_info(args: argparse.Namespace) -> int:
    cues, notes, decoded = read_cues(args.file, args.encoding)
    rules = rules_from(args)
    violations = check(cues, rules)
    print(f"파일: {args.file}")
    print(f"인코딩: {decoded.encoding}{' (자동 판별)' if decoded.detected else ''}")
    print(f"자막: {len(cues)}개, {cues[0].start:.3f}~{cues[-1].end:.3f}초")
    print(f"총 글자: {sum(len(c.text) for c in cues)}자")
    if notes:
        print(f"뺀 자막: {len(notes)}개")
        for note in notes:
            print(f"  {note}")
    kinds: dict[str, int] = {}
    for v in violations:
        kinds[v.kind] = kinds.get(v.kind, 0) + 1
    summary = ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items()))
    print(
        f"규칙 위반: {len(violations)}건"
        + (f" ({summary}). check 명령으로 확인" if summary else "")
    )
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    cues, notes, decoded = read_cues(args.file, args.encoding)
    _report_read(args.file, notes, decoded, cues)
    violations = check(cues, rules_from(args))
    if args.json:
        print(
            json.dumps(
                [{"index": v.index, "kind": v.kind, "detail": v.detail} for v in violations],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for v in violations:
            print(f"{v.index + 1}번 [{v.kind}] {v.detail}")
        print(f"위반 {len(violations)}건 / 자막 {len(cues)}개")
    return EXIT_VIOLATIONS if violations else EXIT_OK


def cmd_convert(args: argparse.Namespace) -> int:
    cues, notes, decoded = read_cues(args.input, args.encoding)
    _report_read(args.input, notes, decoded, cues)
    write_cues(args.output, cues, output_format(args.output, args.format))
    print(f"{args.output}: 자막 {len(cues)}개를 썼습니다.")
    return EXIT_OK


def cmd_shape(args: argparse.Namespace) -> int:
    cues, notes, decoded = read_cues(args.input, args.encoding)
    _report_read(args.input, notes, decoded, cues)
    shaped = apply_rules(cues, rules_from(args))
    write_cues(args.output, shaped, output_format(args.output, args.format))
    print(f"{args.output}: 자막 {len(cues)}개 → {len(shaped)}개로 다듬어 썼습니다.")
    return EXIT_OK


def shift_cues(cues: list[Cue], offset: float) -> tuple[list[Cue], int, int]:
    """시각을 옮깁니다. 0초 앞으로 나간 자막은 자르고, 다 나간 자막은 뺍니다.

    (옮긴 자막, 잘린 개수, 뺀 개수)를 돌려줍니다. 글자는 버리지 않습니다.
    """
    moved: list[Cue] = []
    clamped = dropped = 0
    for cue in cues:
        start, end = cue.start + offset, cue.end + offset
        if end <= 0:
            dropped += 1
            continue
        if start < 0:
            clamped += 1
            start = 0.0
        moved.append(Cue(start=start, end=end, text=cue.text))
    return moved, clamped, dropped


def cmd_shift(args: argparse.Namespace) -> int:
    cues, notes, decoded = read_cues(args.input, args.encoding)
    _report_read(args.input, notes, decoded, cues)
    moved, clamped, dropped = shift_cues(cues, args.offset)
    write_cues(args.output, moved, output_format(args.output, args.format))
    direction = "뒤로" if args.offset >= 0 else "앞으로"
    print(
        f"{args.output}: {abs(args.offset):.3f}초 {direction} 옮겨 자막 {len(moved)}개를 썼습니다."
    )
    if clamped:
        print(f"  0초에서 잘린 자막 {clamped}개")
    if dropped:
        print(f"  0초 앞으로 완전히 나가 뺀 자막 {dropped}개")
    return EXIT_OK


def cmd_cut(args: argparse.Namespace) -> int:
    if args.end <= args.start or args.start < 0:
        raise ToolError("구간은 0 이상이고 끝이 시작보다 뒤여야 합니다.")
    cues, notes, decoded = read_cues(args.input, args.encoding)
    _report_read(args.input, notes, decoded, cues)
    kept = clip_cues(cues, args.start, args.end)
    write_cues(args.output, kept, output_format(args.output, args.format))
    print(
        f"{args.output}: {args.start:.3f}~{args.end:.3f}초 구간의 자막 {len(kept)}개를 썼습니다."
        " 시각은 구간 시작이 0초입니다."
    )
    return EXIT_OK


def cmd_templates(args: argparse.Namespace) -> int:
    if args.action == "list":
        width = max(len(name) for name in BUILTIN_TEMPLATES)
        for template in BUILTIN_TEMPLATES.values():
            print(f"{template.name:<{width}}  {template.label:<8} {template.description}")
        return EXIT_OK
    try:
        template = resolve_template(args.name)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    if args.action == "show":
        print(template.to_json(), end="")
        return EXIT_OK
    _write_text(args.output, template.to_json())
    print(
        f"{args.output}: 템플릿 {template.name}을 JSON으로 썼습니다. 값을 고쳐 --template로 쓰세요."
    )
    return EXIT_OK


def _template_from(args: argparse.Namespace) -> SubtitleTemplate:
    try:
        return resolve_template(args.template)
    except ValueError as exc:
        raise ToolError(str(exc)) from None


def build_document(
    cues: list[Cue],
    template: SubtitleTemplate,
    *,
    width: int,
    height: int,
    duration: float | None,
    title: str,
    font_size: int | None,
    rules: SubtitleRules | None,
) -> str:
    """서버 렌더와 같은 순서(규칙 → 템플릿)로 ASS 글자를 만듭니다."""
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ToolError("화면 크기는 2 이상의 짝수여야 합니다.")
    if font_size is not None and not 20 <= font_size <= 120:
        raise ToolError("글자 크기는 20~120이어야 합니다.")
    shaped = apply_rules(cues, rules) if rules else cues
    if duration is None:
        duration = max(cue.end for cue in shaped)
    document = styled_document(
        shaped,
        template,
        width=width,
        height=height,
        duration=duration,
        title=title,
        font_size=font_size,
    )
    return document.to_string("ass")


def cmd_style(args: argparse.Namespace) -> int:
    template = _template_from(args)
    cues, notes, decoded = read_cues(args.input, args.encoding)
    _report_read(args.input, notes, decoded, cues)
    text = build_document(
        cues,
        template,
        width=args.width,
        height=args.height,
        duration=args.duration,
        title=args.title,
        font_size=args.font_size,
        rules=None if args.no_rules else rules_from(args),
    )
    _write_text(args.output, text)
    print(f"{args.output}: 템플릿 {template.name}({template.label})로 ASS를 썼습니다.")
    return EXIT_OK


# ---------------------------------------------------------------- FFmpeg


def _binary(name: str, env: str) -> str:
    found = os.environ.get(env) or shutil.which(name)
    if not found:
        raise ToolError(f"{name}이(가) 없습니다. 설치하거나 {env}로 경로를 주세요.")
    return found


def probe_video(video: Path) -> tuple[int, int, float]:
    """ffprobe로 (가로, 세로, 길이)를 읽습니다."""
    command = [
        _binary("ffprobe", "R4_FFPROBE_BINARY"),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        str(video),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"ffprobe 실행 실패: {type(exc).__name__}") from None
    if completed.returncode:
        raise ToolError("ffprobe가 영상을 읽지 못했습니다. 파일을 확인하세요.")
    try:
        info = json.loads(completed.stdout)
        stream = info["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(info["format"]["duration"])
    except (ValueError, KeyError, IndexError, TypeError):
        raise ToolError("ffprobe 결과에서 해상도·길이를 읽지 못했습니다.") from None
    return width, height, duration


def cmd_burn(args: argparse.Namespace) -> int:
    template = _template_from(args)
    if not args.video.is_file():
        raise ToolError(f"영상 파일이 없습니다: {args.video}")
    if args.video.resolve() == args.output.resolve():
        raise ToolError("출력 경로는 입력 영상과 달라야 합니다.")
    ffmpeg = _binary("ffmpeg", "R4_FFMPEG_BINARY")
    cues, notes, decoded = read_cues(args.subtitles, args.encoding)
    _report_read(args.subtitles, notes, decoded, cues)
    width, height, duration = args.width, args.height, None
    if not (width and height):
        width, height, duration = probe_video(args.video)
        width, height = width - width % 2, height - height % 2
    text = build_document(
        cues,
        template,
        width=width,
        height=height,
        duration=duration,
        title=args.title,
        font_size=args.font_size,
        rules=None if args.no_rules else rules_from(args),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r4-burn-") as directory:
        temp = Path(directory)
        (temp / "captions.ass").write_text(text, encoding="utf-8")
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(args.video.resolve()),
            "-vf",
            f"scale={width}:{height},setsar=1,subtitles=captions.ass,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(temp / "result.mp4"),
        ]
        try:
            completed = subprocess.run(command, cwd=temp, capture_output=True, timeout=3600)
        except subprocess.TimeoutExpired:
            raise ToolError("영상 합성이 1시간 제한을 넘었습니다.") from None
        if completed.returncode:
            raise ToolError(
                "FFmpeg 합성 실패: 설치된 코덱·subtitles 필터·글꼴·입력 영상을 확인하세요."
            )
        shutil.copyfile(temp / "result.mp4", args.output)
    print(
        f"{args.output}: 템플릿 {template.name}({template.label})로 "
        f"{width}x{height} 영상에 구웠습니다."
    )
    return EXIT_OK


# ---------------------------------------------------------------- 진입점


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="r4-subtitles",
        description="자막 파일과 자막 템플릿 도구. 서버 렌더와 같은 규칙·모양을 씁니다.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="파일 요약")
    info.add_argument("file", type=Path)
    _add_encoding(info)
    _add_rules(info)
    info.set_defaults(run=cmd_info)

    chk = sub.add_parser("check", help="표시 규칙 위반 보고. 위반이 있으면 종료 코드 1")
    chk.add_argument("file", type=Path)
    chk.add_argument("--json", action="store_true", help="JSON으로 출력")
    _add_encoding(chk)
    _add_rules(chk)
    chk.set_defaults(run=cmd_check)

    conv = sub.add_parser("convert", help="SRT·VTT·ASS를 SRT 또는 VTT로 (글자·시각 그대로)")
    conv.add_argument("input", type=Path)
    conv.add_argument("output", type=Path)
    _add_encoding(conv)
    _add_output_format(conv)
    conv.set_defaults(run=cmd_convert)

    shape = sub.add_parser("shape", help="줄바꿈·분할 규칙을 적용해 저장")
    shape.add_argument("input", type=Path)
    shape.add_argument("output", type=Path)
    _add_encoding(shape)
    _add_output_format(shape)
    _add_rules(shape)
    shape.set_defaults(run=cmd_shape)

    shift = sub.add_parser("shift", help="시각을 옮김")
    shift.add_argument("input", type=Path)
    shift.add_argument("output", type=Path)
    shift.add_argument("--offset", type=float, required=True, help="초. 양수면 뒤로, 음수면 앞으로")
    _add_encoding(shift)
    _add_output_format(shift)
    shift.set_defaults(run=cmd_shift)

    cut = sub.add_parser("cut", help="구간만 남기고 구간 시작을 0초로")
    cut.add_argument("input", type=Path)
    cut.add_argument("output", type=Path)
    cut.add_argument("--start", type=float, required=True)
    cut.add_argument("--end", type=float, required=True)
    _add_encoding(cut)
    _add_output_format(cut)
    cut.set_defaults(run=cmd_cut)

    templates = sub.add_parser("templates", help="내장 템플릿 목록·내용·JSON 내보내기")
    action = templates.add_subparsers(dest="action", required=True)
    action.add_parser("list", help="내장 템플릿 목록")
    show = action.add_parser("show", help="템플릿 내용을 JSON으로 출력")
    show.add_argument("name", help="내장 이름 또는 JSON 파일")
    export = action.add_parser(
        "export", help="템플릿을 JSON 파일로 저장 (고쳐서 --template로 사용)"
    )
    export.add_argument("name", help="내장 이름 또는 JSON 파일")
    export.add_argument("output", type=Path)
    templates.set_defaults(run=cmd_templates)

    style = sub.add_parser("style", help="템플릿 모양의 ASS 파일 만들기")
    style.add_argument("input", type=Path)
    style.add_argument("output", type=Path)
    style.add_argument("--width", type=int, default=DEFAULT_WIDTH, help=f"기본 {DEFAULT_WIDTH}")
    style.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help=f"기본 {DEFAULT_HEIGHT}")
    style.add_argument(
        "--duration", type=float, help="영상 길이(초). 제목 표시 시간. 비우면 마지막 자막 끝"
    )
    _add_template(style)
    _add_encoding(style)
    _add_rules(style)
    style.set_defaults(run=cmd_style)

    burn = sub.add_parser("burn", help="FFmpeg로 영상에 자막 굽기")
    burn.add_argument("video", type=Path)
    burn.add_argument("subtitles", type=Path)
    burn.add_argument("output", type=Path)
    burn.add_argument("--width", type=int, help="비우면 ffprobe로 영상에서 읽습니다.")
    burn.add_argument("--height", type=int, help="비우면 ffprobe로 영상에서 읽습니다.")
    _add_template(burn)
    _add_encoding(burn)
    _add_rules(burn)
    burn.set_defaults(run=cmd_burn)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except ToolError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
