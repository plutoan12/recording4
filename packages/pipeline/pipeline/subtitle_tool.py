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
- templates 내장 템플릿 목록·내용·JSON 내보내기·글꼴 확인
- style     템플릿 모양의 ASS 파일 만들기
- burn      FFmpeg로 영상에 자막 굽기(FFmpeg 필요)
- preview   템플릿 하나를 PNG 한 장으로(FFmpeg 필요)
- sheet     내장 템플릿 전부를 한 장의 PNG 시트로(FFmpeg 필요)

글꼴: 템플릿 글꼴은 워커 이미지에 설치돼 있습니다. 로컬에서는
`scripts/fetch_fonts.py --out .fonts`로 받고 `--fonts-dir .fonts` 또는 `R4_FONTS_DIR`로
알려 줍니다. 없으면 libass가 다른 글꼴로 대체해 모양이 달라집니다.

종료 코드: 0 성공, 1 check에서 위반 발견, 2 입력·환경 오류.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
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
from pipeline.subtitle_fonts import FONT_FAMILIES
from pipeline.subtitle_motion import ANIMATION_LABELS
from pipeline.subtitle_presets import (
    PACK_LABELS,
    PRESET_README,
    MotionPreset,
    all_presets,
    load_preset,
    presets_by_pack,
    register_preset,
    resolve_preset,
    user_presets_dir,
)
from pipeline.subtitle_stickers import (
    STICKER_LABELS,
    Sticker,
    add_sticker_events,
    image_overlays,
    overlay_filter_graph,
)
from pipeline.subtitle_templates import (
    BUILTIN_TEMPLATES,
    CATEGORY_LABELS,
    SubtitleTemplate,
    reel_document,
    resolve_template,
    sheet_document,
    styled_document,
    templates_by_category,
)
from pipeline.subtitles import (
    DEFAULT_RULES,
    PACING_LABELS,
    SubtitleRules,
    apply_rules,
    check,
    pacing_rules,
    quality_report,
)

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
    group.add_argument(
        "--pacing",
        choices=tuple(PACING_LABELS),
        help=(
            "자막을 끊는 방식. shortform은 한 줄로 짧게 끊습니다. "
            "대본의 단어 시각이 있을 때만 말한 자리에서 끊고, 파일 입력은 글자 수로 나눕니다."
        ),
    )
    group.add_argument("--max-chars", type=int, help="줄당 최대 글자 폭(한글 1, 라틴 0.5)")
    group.add_argument("--max-lines", type=int, help="자막당 최대 줄 수")
    group.add_argument("--max-cps", type=float, help="초당 최대 글자 폭")
    group.add_argument("--min-duration", type=float, help="자막 최소 표시 시간(초)")
    group.add_argument("--max-duration", type=float, help="자막 최대 표시 시간(초)")


def _add_fonts_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fonts-dir",
        type=Path,
        default=None,
        help="템플릿 글꼴 디렉터리. 비우면 R4_FONTS_DIR, 그것도 없으면 시스템 글꼴만 씁니다.",
    )


def fonts_dir_from(args: argparse.Namespace) -> Path | None:
    chosen = getattr(args, "fonts_dir", None)
    if chosen is None:
        value = os.environ.get("R4_FONTS_DIR", "").strip()
        chosen = Path(value) if value else None
    if chosen is not None and not chosen.is_dir():
        raise ToolError(f"글꼴 디렉터리가 없습니다: {chosen}")
    return chosen


def subtitles_filter(filename: str, fonts: Path | None) -> str:
    """FFmpeg subtitles 필터. 글꼴 디렉터리는 콜론·따옴표를 이스케이프해 넘깁니다."""
    if fonts is None:
        return f"subtitles={filename}"
    escaped = str(fonts.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"subtitles={filename}:fontsdir='{escaped}'"


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
    _add_animation(parser)


def _add_stickers(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sticker",
        action="append",
        default=[],
        metavar="JSON",
        help=(
            '스티커 하나를 JSON으로. 예: \'{"kind":"arrow-right","x":0.7,"y":0.4}\'. '
            "여러 번 줄 수 있습니다. 종류는 `stickers list`."
        ),
    )
    parser.add_argument(
        "--stickers-dir", type=Path, help="이미지 스티커(PNG) 디렉터리. 비우면 R4_STICKERS_DIR"
    )


def stickers_from(args: argparse.Namespace) -> list[Sticker]:
    found = []
    for raw in getattr(args, "sticker", None) or []:
        try:
            found.append(Sticker.model_validate_json(raw))
        except ValueError as exc:
            raise ToolError(f"스티커 JSON이 잘못됐습니다: {exc}") from None
    return found


def stickers_dir_from(args: argparse.Namespace) -> Path | None:
    given = getattr(args, "stickers_dir", None)
    if given is None:
        value = os.environ.get("R4_STICKERS_DIR", "").strip()
        given = Path(value) if value else None
    if given is not None and not given.is_dir():
        raise ToolError(f"스티커 디렉터리가 없습니다: {given}")
    return given


def cmd_stickers(args: argparse.Namespace) -> int:
    print("내장 스티커 (kind):")
    for kind, label in STICKER_LABELS.items():
        print(f"  {kind:<16} {label}")
    print("이미지 스티커는 kind=image, image=파일이름.png (--stickers-dir 안)")
    return EXIT_OK


def _add_animation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--animation",
        choices=tuple(ANIMATION_LABELS),
        help="움직임. 템플릿 값보다 우선합니다. none이면 움직임을 뺍니다.",
    )
    parser.add_argument(
        "--animation-ms",
        type=int,
        help="움직임 시간(ms, 40~3000). 등장 시간·글자당·단어당·한 주기. 비우면 종류별 기본값",
    )
    parser.add_argument(
        "--preset",
        help=(
            "모션 프리셋 이름 또는 JSON 파일. 움직임(--animation)보다 먼저 씁니다. "
            "목록은 `presets list`."
        ),
    )


def _apply_animation(template: SubtitleTemplate, args: argparse.Namespace) -> SubtitleTemplate:
    template = _apply_preset(template, args)
    kind = getattr(args, "animation", None)
    ms = getattr(args, "animation_ms", None)
    if kind is None and ms is None:
        return template
    try:
        return template.with_animation(kind or template.animation, ms or template.animation_ms)
    except ValueError as exc:
        raise ToolError(str(exc)) from None


def _apply_preset(template: SubtitleTemplate, args: argparse.Namespace) -> SubtitleTemplate:
    """`--preset`(이름 또는 JSON 파일)을 템플릿에 붙입니다."""
    given = getattr(args, "preset", None)
    if not given:
        return template
    try:
        preset = resolve_preset(given)
        if preset is None:
            return template
        # JSON 파일로 준 프리셋도 이름으로 찾을 수 있게 등록한 뒤 붙입니다.
        register_preset(preset)
        return template.with_preset(preset.name)
    except ValueError as exc:
        raise ToolError(str(exc)) from None


def cmd_presets(args: argparse.Namespace) -> int:
    """모션 프리셋 목록·내용·JSON 내보내기·새로 만들기·검사."""
    presets = all_presets()
    if args.action == "list":
        for pack, items in presets_by_pack().items():
            print(f"[{PACK_LABELS[pack]}] {len(items)}종")
            for preset in items:
                print(f"  {preset.name:<20} {preset.label:<16} {preset.summary}")
        directory = user_presets_dir()
        print(f"\n내 프리셋 디렉터리: {directory or '(R4_PRESETS_DIR 없음)'}")
        return EXIT_OK
    if args.action == "check":
        bad = _broken_presets(presets.values())
        for name, reason in bad:
            print(f"{name}: {reason}")
        print(f"프리셋 {len(presets)}종 가운데 {len(bad)}종에 문제가 있습니다.")
        return EXIT_ERROR if bad else EXIT_OK
    if args.action == "pack":
        grouped = presets_by_pack()
        if args.pack not in grouped:
            raise ToolError(f"모르는 팩입니다: {args.pack}. 쓸 수 있는 것: {', '.join(grouped)}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("읽어보기.txt", PRESET_README)
            for preset in grouped[args.pack]:
                archive.writestr(f"{preset.name}.json", preset.to_json())
        print(
            f"{args.output}: {PACK_LABELS[args.pack]} {len(grouped[args.pack])}종을 "
            "zip으로 묶었습니다."
        )
        return EXIT_OK
    if args.action == "import":
        directory = user_presets_dir()
        if directory is None:
            raise ToolError("내 프리셋 디렉터리가 없습니다. R4_PRESETS_DIR를 만들고 가리키세요.")
        try:
            preset = load_preset(args.file)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        builtin = {name for name, item in all_presets().items() if item.pack != "user"}
        if preset.name in builtin:
            raise ToolError(f"내장 프리셋과 같은 이름입니다: {preset.name}")
        stored = preset.model_copy(update={"pack": "user"})
        _write_text(directory / f"{preset.name}.json", stored.to_json())
        print(f"{directory / (preset.name + '.json')}: 내 프리셋으로 넣었습니다.")
        return EXIT_OK
    if args.action == "new":
        preset = MotionPreset(
            name=args.name,
            label=args.label or args.name,
            pack="user",
            description="직접 만든 프리셋",
            steps=[
                {"kind": "move", "phase": "in", "direction": "up", "amount": 80, "ms": 320},
                {"kind": "fade", "phase": "in", "ms": 200},
            ],
        )
        _write_text(args.output, preset.to_json())
        print(f"{args.output}: 새 프리셋을 썼습니다. 값을 고쳐 --preset로 쓰세요.")
        return EXIT_OK
    try:
        preset = resolve_preset(args.name)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    assert preset is not None
    if args.action == "show":
        print(preset.to_json(), end="")
        return EXIT_OK
    _write_text(args.output, preset.to_json())
    print(f"{args.output}: 프리셋 {preset.name}을 JSON으로 썼습니다. 고쳐서 --preset로 쓰세요.")
    return EXIT_OK


def _broken_presets(presets) -> list[tuple[str, str]]:  # noqa: ANN001
    """실제로 명령을 만들어 보고 아무것도 나오지 않거나 오류가 나는 프리셋을 찾습니다."""
    from pipeline.subtitle_presets import PresetBox, preset_runs, preset_tags

    box = PresetBox(left=200, top=1500, right=880, bottom=1600)
    out: list[tuple[str, str]] = []
    for preset in presets:
        try:
            tags = preset_tags(
                preset,
                duration_ms=2000,
                anchor=(540, 1600),
                base_tag="\\1c&HFFFFFF&",
                box=box,
                play_size=(1080, 1920),
            )
            runs = preset_runs(
                preset,
                "가나 다라",
                duration_ms=2000,
                accent="\\1c&HFFE14D&",
                base="\\1c&HFFFFFF&",
            )
        except ValueError as exc:
            out.append((preset.name, str(exc)))
            continue
        if not tags and runs == "가나 다라":
            out.append((preset.name, "명령이 만들어지지 않습니다(동작을 확인하세요)."))
    return out


def rules_from(args: argparse.Namespace) -> SubtitleRules:
    """언어 기본값 위에 명시한 값만 덮습니다. 검증은 SubtitleRules가 합니다."""
    pacing = getattr(args, "pacing", None)
    try:
        base = pacing_rules(pacing, getattr(args, "language", None), DEFAULT_RULES)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
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


def cmd_quality(args: argparse.Namespace) -> int:
    """자막 품질을 숫자로 요약합니다. 규칙을 바꾸기 전후를 견주는 데 씁니다."""
    cues, notes, decoded = read_cues(args.file, args.encoding)
    _report_read(args.file, notes, decoded, cues)
    rules = rules_from(args)
    shaped = apply_rules(cues, rules) if args.shape else cues
    report = quality_report(shaped, rules)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return EXIT_OK
    print(f"자막 {report['count']}개 (규칙 위반 {report['violation_ratio'] * 100:.0f}%)")
    for key, label, unit in (
        ("duration", "표시 시간", "초"),
        ("width", "글자 폭", "자"),
        ("cps", "읽기 속도", "자/초"),
        ("gap", "자막 사이", "초"),
    ):
        values = report[key]
        print(
            f"  {label:<6} 최소 {values['min']:>6.2f} · 가운데 {values['median']:>6.2f}"
            f" · 평균 {values['mean']:>6.2f} · 최대 {values['max']:>6.2f} {unit}"
        )
    print(f"  화면에 떠 있는 시간 비율 {report['coverage'] * 100:.0f}%")
    for kind, count in sorted(report["violations"].items()):
        print(f"  위반 {kind}: {count}건")
    return EXIT_OK


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


def _fontconfig_for(fonts: Path) -> str:
    """fc-match가 --fonts-dir도 보게 하는 임시 fontconfig 설정 파일 경로."""
    config = Path(tempfile.gettempdir()) / "r4-fontconfig.xml"
    config.write_text(
        "<?xml version='1.0'?><!DOCTYPE fontconfig SYSTEM 'fonts.dtd'><fontconfig>"
        "<include ignore_missing='yes'>/etc/fonts/fonts.conf</include>"
        f"<dir>{fonts.resolve()}</dir></fontconfig>",
        encoding="utf-8",
    )
    return str(config)


def font_matches(family: str) -> str | None:
    """fc-match가 이 이름에 고른 글꼴의 family. fontconfig가 없으면 None."""
    binary = shutil.which("fc-match")
    if not binary:
        return None
    # fontconfig 패턴은 하이픈을 이름과 크기의 구분자로 읽습니다("S-Core Dream" →
    # 이름 "S"). `:family=` 꼴로 주면 이름을 그대로 봅니다.
    completed = subprocess.run(
        [binary, "--format", "%{family}", f":family={family}"], capture_output=True, text=True
    )
    if completed.returncode:
        return None
    return completed.stdout.strip()


def cmd_templates(args: argparse.Namespace) -> int:
    if args.action == "list":
        width = max(len(name) for name in BUILTIN_TEMPLATES)
        for category, templates in templates_by_category().items():
            print(f"[{CATEGORY_LABELS[category]}]")
            for template in templates:
                print(f"  {template.name:<{width}}  {template.label:<10} {template.description}")
        return EXIT_OK
    if args.action == "check":
        # 내장 템플릿의 글꼴이 이 컴퓨터(또는 --fonts-dir)에서 실제로 찾아지는지 봅니다.
        # libass는 못 찾으면 조용히 대체하므로 여기서 먼저 잡습니다.
        fonts = fonts_dir_from(args)
        if fonts is not None:
            os.environ["FONTCONFIG_FILE"] = _fontconfig_for(fonts)
        problems = 0
        for family in sorted({t.font_name for t in BUILTIN_TEMPLATES.values()}):
            listed = family in FONT_FAMILIES
            matched = font_matches(family)
            # fc-match는 family 이름을 쉼표로 여러 개 줍니다(영문·한글·전체 이름).
            names = [] if matched is None else [n.strip() for n in matched.split(",")]
            ok = listed and (matched is None or family in names)
            problems += not ok
            state = "확인 불가(fontconfig 없음)" if matched is None else (names or ["?"])[0]
            note = "" if listed else " (목록에 없음)"
            print(f"{'OK ' if ok else 'NG '} {family:<22} → {state}{note}")
        print(f"글꼴 문제 {problems}건")
        return EXIT_VIOLATIONS if problems else EXIT_OK
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
        template = resolve_template(args.template)
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    return _apply_animation(template, args)


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
    stickers: list[Sticker] | None = None,
) -> str:
    """서버 렌더와 같은 순서(규칙 → 템플릿)로 ASS 글자를 만듭니다. 벡터 스티커도 넣습니다."""
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
    add_sticker_events(document, stickers or [], width=width, height=height, duration=duration)
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
        stickers=stickers_from(args),
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
    fonts = fonts_dir_from(args)
    stickers = stickers_from(args)
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
        stickers=stickers,
    )
    try:
        overlays = image_overlays(
            stickers,
            stickers_dir_from(args),
            width=width,
            height=height,
            duration=duration or max(c.end for c in cues),
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    base_chain = (
        f"scale={width}:{height},setsar=1,{subtitles_filter('captions.ass', fonts)},format=yuv420p"
    )
    if overlays:
        inputs, graph, out = overlay_filter_graph(base_chain, overlays)
        filter_args = [*inputs, "-filter_complex", graph, "-map", f"[{out}]", "-map", "0:a?"]
    else:
        filter_args = ["-vf", base_chain]
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
            *filter_args,
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


def render_frame(
    ass_text: str, output: Path, *, width: int, height: int, fonts: Path | None, background: str
) -> None:
    """ASS 글자 하나를 단색 배경 위 PNG 한 장으로 그립니다. FFmpeg(libass)가 필요합니다."""
    ffmpeg = _binary("ffmpeg", "R4_FFMPEG_BINARY")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r4-preview-") as directory:
        temp = Path(directory)
        (temp / "sheet.ass").write_text(ass_text, encoding="utf-8")
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={background}:s={width}x{height}",
            "-vf",
            subtitles_filter("sheet.ass", fonts),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(temp / "frame.png"),
        ]
        try:
            completed = subprocess.run(command, cwd=temp, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise ToolError("미리보기 렌더가 5분 제한을 넘었습니다.") from None
        if completed.returncode:
            raise ToolError("FFmpeg 렌더 실패: libass(subtitles 필터)와 글꼴을 확인하세요.")
        shutil.copyfile(temp / "frame.png", output)


CLIP_SUFFIXES = (".mp4", ".gif")
CLIP_FPS = 30
GIF_FPS = 15


def render_clip(
    ass_text: str,
    output: Path,
    *,
    width: int,
    height: int,
    seconds: float,
    fonts: Path | None,
    background: str,
) -> None:
    """ASS 글자를 단색 배경 위 짧은 영상(MP4 또는 GIF)으로 그립니다. 움직임 확인용입니다."""
    if output.suffix.lower() not in CLIP_SUFFIXES:
        raise ToolError("영상 출력은 .mp4 또는 .gif여야 합니다.")
    if not 0 < seconds <= 600:
        raise ToolError("영상 길이는 0초 초과 600초 이하여야 합니다.")
    ffmpeg = _binary("ffmpeg", "R4_FFMPEG_BINARY")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r4-motion-") as directory:
        temp = Path(directory)
        (temp / "motion.ass").write_text(ass_text, encoding="utf-8")
        subtitles = subtitles_filter("motion.ass", fonts)
        source = f"color=c={background}:s={width}x{height}:r={CLIP_FPS}:d={seconds:g}"
        if output.suffix.lower() == ".gif":
            # GIF는 팔레트를 먼저 뽑아야 색이 뭉개지지 않습니다.
            codec = [
                "-filter_complex",
                f"[0:v]{subtitles},fps={GIF_FPS},split[a][b];[a]palettegen=stats_mode=diff[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=3",
            ]
        else:
            codec = [
                "-vf",
                f"{subtitles},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
            ]
        result = temp / f"result{output.suffix.lower()}"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            *codec,
            str(result),
        ]
        try:
            completed = subprocess.run(command, cwd=temp, capture_output=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise ToolError("영상 렌더가 10분 제한을 넘었습니다.") from None
        if completed.returncode:
            raise ToolError("FFmpeg 렌더 실패: libass(subtitles 필터)·libx264와 글꼴을 확인하세요.")
        shutil.copyfile(result, output)


def _background(value: str) -> str:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise ToolError("배경색은 #RRGGBB 형식이어야 합니다.")
    return value


def cmd_preview(args: argparse.Namespace) -> int:
    template = _template_from(args)
    fonts = fonts_dir_from(args)
    text = args.text or template.sample or template.label
    background = _background(args.background)
    suffix = args.output.suffix.lower()
    if suffix not in (".png", *CLIP_SUFFIXES):
        raise ToolError("미리보기 출력은 .png(정지 화면) 또는 .mp4/.gif(영상)여야 합니다.")
    as_clip = suffix in CLIP_SUFFIXES
    seconds = args.seconds if as_clip else 1
    if not 0 < seconds <= 600:
        raise ToolError("영상 길이는 0초 초과 600초 이하여야 합니다.")
    cues = [Cue(start=0, end=seconds, text=text)]
    ass_text = build_document(
        cues,
        template,
        width=args.width,
        height=args.height,
        duration=seconds,
        title=args.title,
        font_size=args.font_size,
        rules=None if args.no_rules else rules_from(args),
        stickers=stickers_from(args),
    )
    if as_clip:
        render_clip(
            ass_text,
            args.output,
            width=args.width,
            height=args.height,
            seconds=seconds,
            fonts=fonts,
            background=background,
        )
        print(
            f"{args.output}: 템플릿 {template.name}({template.label}, 움직임 "
            f"{template.animation_label}) {seconds:g}초 영상을 썼습니다."
        )
        return EXIT_OK
    render_frame(
        ass_text,
        args.output,
        width=args.width,
        height=args.height,
        fonts=fonts,
        background=background,
    )
    print(f"{args.output}: 템플릿 {template.name}({template.label}) 미리보기를 썼습니다.")
    return EXIT_OK


def _chosen_templates(args: argparse.Namespace) -> list[SubtitleTemplate]:
    """`--templates`(이름·JSON) 또는 `--category`로 고른 템플릿. 비우면 전부."""
    if args.templates:
        try:
            return [resolve_template(name) for name in args.templates]
        except ValueError as exc:
            raise ToolError(str(exc)) from None
    grouped = templates_by_category()
    if args.category:
        unknown = [c for c in args.category if c not in grouped]
        if unknown:
            raise ToolError(
                f"모르는 카테고리입니다: {', '.join(unknown)}. 쓸 수 있는 것: {', '.join(grouped)}"
            )
        return [t for c in args.category for t in grouped[c]]
    return [t for templates in grouped.values() for t in templates]


def _preset_reel_templates(args: argparse.Namespace) -> list[SubtitleTemplate]:
    """프리셋 팩을 보여 줄 때 쓰는 템플릿 목록(템플릿 하나 + 프리셋마다 한 벌)."""
    grouped = presets_by_pack()
    packs = list(grouped) if args.preset_pack == "all" else [args.preset_pack]
    chosen = [preset for pack in packs for preset in grouped.get(pack, [])]
    if not chosen:
        raise ToolError(f"프리셋이 없습니다: {args.preset_pack}")
    try:
        base = resolve_template(args.templates[0] if args.templates else "default")
        return [base.with_preset(preset.name) for preset in chosen]
    except ValueError as exc:
        raise ToolError(str(exc)) from None


def cmd_reel(args: argparse.Namespace) -> int:
    fonts = fonts_dir_from(args)
    if getattr(args, "preset_pack", None):
        chosen = _preset_reel_templates(args)
    else:
        chosen = [_apply_animation(t, args) for t in _chosen_templates(args)]
    if args.font_size is not None and not 20 <= args.font_size <= 120:
        raise ToolError("글자 크기는 20~120이어야 합니다.")
    try:
        document, seconds = reel_document(
            chosen,
            width=args.width,
            height=args.height,
            seconds_each=args.seconds,
            gap=args.gap,
            text=args.text,
            font_size=args.font_size,
            captions=not args.no_captions,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    if args.ass:
        _write_text(args.ass, document.to_string("ass"))
    render_clip(
        document.to_string("ass"),
        args.output,
        width=args.width,
        height=args.height,
        seconds=seconds,
        fonts=fonts,
        background=_background(args.background),
    )
    what = "프리셋" if getattr(args, "preset_pack", None) else "템플릿"
    print(f"{args.output}: {what} {len(chosen)}종을 {seconds:g}초 영상으로 썼습니다.")
    return EXIT_OK


def cmd_sheet(args: argparse.Namespace) -> int:
    fonts = fonts_dir_from(args)
    chosen = _chosen_templates(args)
    try:
        document, height = sheet_document(
            chosen,
            width=args.width,
            columns=args.columns,
            text=args.text,
            title=args.title,
            layout=args.layout,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from None
    if args.ass:
        _write_text(args.ass, document.to_string("ass"))
    render_frame(
        document.to_string("ass"),
        args.output,
        width=args.width,
        height=height,
        fonts=fonts,
        background=_background(args.background),
    )
    print(f"{args.output}: 템플릿 {len(chosen)}종을 {args.width}x{height} 시트로 썼습니다.")
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

    quality = sub.add_parser(
        "quality", help="자막 품질 요약(장수·표시 시간·읽기 속도·규칙 위반 비율)"
    )
    quality.add_argument("file", type=Path)
    quality.add_argument(
        "--shape", action="store_true", help="표시 규칙을 적용한 뒤의 값을 봅니다(전후 비교)."
    )
    quality.add_argument("--json", action="store_true", help="JSON으로 출력")
    _add_encoding(quality)
    _add_rules(quality)
    quality.set_defaults(run=cmd_quality)

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

    templates = sub.add_parser("templates", help="내장 템플릿 목록·내용·JSON 내보내기·글꼴 확인")
    action = templates.add_subparsers(dest="action", required=True)
    action.add_parser("list", help="내장 템플릿 목록(카테고리별)")
    check_fonts = action.add_parser("check", help="내장 템플릿의 글꼴이 실제로 찾아지는지 확인")
    _add_fonts_dir(check_fonts)
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
    _add_stickers(style)
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
    _add_stickers(burn)
    _add_fonts_dir(burn)
    _add_encoding(burn)
    _add_rules(burn)
    burn.set_defaults(run=cmd_burn)

    stickers = sub.add_parser("stickers", help="스티커 종류 목록")
    stickers.add_subparsers(dest="action", required=True).add_parser(
        "list", help="내장 스티커 목록"
    )
    stickers.set_defaults(run=cmd_stickers)

    preview = sub.add_parser(
        "preview", help="템플릿 하나를 PNG 한 장 또는 .mp4/.gif 짧은 영상으로 (FFmpeg 필요)"
    )
    preview.add_argument("output", type=Path, help=".png는 정지 화면, .mp4/.gif는 움직임 영상")
    preview.add_argument("--text", help="예문. 비우면 템플릿의 예문")
    preview.add_argument("--seconds", type=float, default=3.0, help="영상 출력의 길이(초). 기본 3")
    preview.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    preview.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    preview.add_argument("--background", default="#141414", help="배경색 #RRGGBB")
    _add_template(preview)
    _add_stickers(preview)
    _add_fonts_dir(preview)
    _add_rules(preview)
    preview.set_defaults(run=cmd_preview)

    sheet = sub.add_parser("sheet", help="내장 템플릿 전부를 한 장의 PNG 시트로 (FFmpeg 필요)")
    sheet.add_argument("output", type=Path)
    sheet.add_argument(
        "--templates", nargs="*", help="넣을 템플릿 이름 또는 JSON 파일. 비우면 전부"
    )
    sheet.add_argument("--category", nargs="*", help="넣을 카테고리. 비우면 전부")
    sheet.add_argument("--text", help="모든 템플릿에 같은 예문을 씁니다. 비우면 템플릿별 예문")
    sheet.add_argument("--title", default="자막 템플릿", help="시트 제목")
    sheet.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    sheet.add_argument("--columns", type=int, default=2, help="grid 배치의 열 수")
    sheet.add_argument(
        "--layout",
        choices=("flow", "grid"),
        default="flow",
        help="flow는 글자 폭을 재서 빽빽하게(기본), grid는 같은 크기 칸에 하나씩",
    )
    sheet.add_argument("--background", default="#141414", help="배경색 #RRGGBB")
    sheet.add_argument("--ass", type=Path, help="시트 ASS 파일도 함께 저장")
    _add_fonts_dir(sheet)
    sheet.set_defaults(run=cmd_sheet)

    reel = sub.add_parser(
        "reel", help="템플릿을 차례로 보여 주는 .mp4/.gif 영상 (움직임 확인용, FFmpeg 필요)"
    )
    reel.add_argument("output", type=Path)
    reel.add_argument("--templates", nargs="*", help="넣을 템플릿 이름 또는 JSON 파일. 비우면 전부")
    reel.add_argument("--category", nargs="*", help="넣을 카테고리. 비우면 전부")
    reel.add_argument("--text", help="모든 템플릿에 같은 예문을 씁니다. 비우면 템플릿별 예문")
    reel.add_argument("--seconds", type=float, default=2.5, help="템플릿당 시간(초). 기본 2.5")
    reel.add_argument("--gap", type=float, default=0.3, help="템플릿 사이 빈 시간(초). 기본 0.3")
    reel.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    reel.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    reel.add_argument("--font-size", type=int, help="글자 크기. 템플릿 값보다 우선합니다.")
    reel.add_argument("--background", default="#141414", help="배경색 #RRGGBB")
    reel.add_argument("--no-captions", action="store_true", help="화면 위 템플릿 이름을 뺍니다.")
    reel.add_argument(
        "--preset-pack",
        choices=("basic", "short", "user", "all"),
        help="템플릿 대신 모션 프리셋 팩을 차례로 보여 줍니다(--templates의 첫 템플릿에 붙임).",
    )
    reel.add_argument("--ass", type=Path, help="영상 ASS 파일도 함께 저장")
    _add_animation(reel)
    _add_fonts_dir(reel)
    reel.set_defaults(run=cmd_reel)

    presets = sub.add_parser("presets", help="모션 프리셋 목록·내용·JSON 내보내기·새로 만들기·검사")
    preset_action = presets.add_subparsers(dest="action", required=True)
    preset_action.add_parser("list", help="프리셋 목록(팩별)")
    preset_action.add_parser("check", help="프리셋이 실제로 ASS 명령을 만드는지 확인")
    show_preset = preset_action.add_parser("show", help="프리셋 내용을 JSON으로 출력")
    show_preset.add_argument("name", help="프리셋 이름 또는 JSON 파일")
    export_preset = preset_action.add_parser(
        "export", help="프리셋을 JSON 파일로 저장 (고쳐서 --preset로 사용)"
    )
    export_preset.add_argument("name", help="프리셋 이름 또는 JSON 파일")
    export_preset.add_argument("output", type=Path)
    pack_preset = preset_action.add_parser(
        "pack", help="팩 하나를 zip으로 묶기 (프리셋 JSON + 읽어보기)"
    )
    pack_preset.add_argument("pack", help="basic, short, kinetic, user")
    pack_preset.add_argument("output", type=Path)
    import_preset = preset_action.add_parser(
        "import", help="프리셋 JSON을 내 프리셋(R4_PRESETS_DIR)으로 넣기"
    )
    import_preset.add_argument("file", type=Path)
    new_preset = preset_action.add_parser("new", help="새 프리셋 JSON 뼈대 만들기")
    new_preset.add_argument("output", type=Path)
    new_preset.add_argument("--name", required=True, help="영문 소문자·숫자·하이픈")
    new_preset.add_argument("--label", default="", help="화면에 보이는 이름. 비우면 --name")
    presets.set_defaults(run=cmd_presets)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except ToolError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except BrokenPipeError:
        # `r4-subtitles templates list | head`처럼 읽는 쪽이 먼저 닫은 경우. 오류가 아닙니다.
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
