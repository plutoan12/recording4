"""자막 파일·템플릿 명령줄 도구. 파일만 다루며 FFmpeg 없이 도는 부분을 확인합니다."""

import json
import os
import shutil
from pathlib import Path

import pysubs2
import pytest

from pipeline.editing import Cue
from pipeline.subtitle_tool import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_VIOLATIONS,
    ToolError,
    build_parser,
    main,
    output_format,
    rules_from,
    shift_cues,
)
from pipeline.subtitles import DEFAULT_RULES, LANGUAGE_RULES, text_width

LONG = (
    "안녕하세요. 자막 파일과 자막 템플릿 도구를 시험합니다. "
    "이 문장은 일부러 길게 써서 분할되게 합니다."
)
SRT = f"1\n00:00:01,000 --> 00:00:04,000\n{LONG}\n\n2\n00:00:05,000 --> 00:00:06,000\n짧은 자막\n"


@pytest.fixture
def srt(tmp_path: Path) -> Path:
    path = tmp_path / "sample.srt"
    path.write_text(SRT, encoding="utf-8")
    return path


def test_info_summarises_the_file(srt, capsys):
    assert main(["info", str(srt)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "인코딩: utf-8" in out and "자막: 2개, 1.000~6.000초" in out
    assert "규칙 위반: 2건" in out


def test_check_reports_violations_and_exits_nonzero(srt, capsys):
    assert main(["check", str(srt)]) == EXIT_VIOLATIONS
    out = capsys.readouterr().out
    assert "1번 [lines]" in out and "1번 [cps]" in out and "위반 2건 / 자막 2개" in out
    assert main(["check", str(srt), "--json"]) == EXIT_VIOLATIONS
    report = json.loads(capsys.readouterr().out)
    assert {v["kind"] for v in report} == {"lines", "cps"} and report[0]["index"] == 0
    # 규칙을 느슨하게 주면 통과합니다.
    assert main(["check", str(srt), "--max-chars", "60", "--max-cps", "30"]) == EXIT_OK


def test_convert_keeps_text_and_times_and_picks_format_from_extension(srt, tmp_path, capsys):
    out = tmp_path / "out.vtt"
    assert main(["convert", str(srt), str(out)]) == EXIT_OK
    text = out.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT") and "00:00:01.000 --> 00:00:04.000" in text and LONG in text
    err = capsys.readouterr().err
    assert "자막 2개, 인코딩 utf-8" in err
    # 확장자를 알 수 없으면 --format이 필요하고, ASS는 style 명령으로 안내합니다.
    assert main(["convert", str(srt), str(tmp_path / "out.txt")]) == EXIT_ERROR
    assert main(["convert", str(srt), str(tmp_path / "out.ass")]) == EXIT_ERROR
    assert "style 명령" in capsys.readouterr().err
    assert main(["convert", str(srt), str(tmp_path / "out.txt"), "--format", "srt"]) == EXIT_OK


def test_convert_reads_cp949_by_detection_and_honours_explicit_encoding(tmp_path, capsys):
    path = tmp_path / "legacy.srt"
    path.write_bytes(SRT.encode("cp949"))
    out = tmp_path / "out.srt"
    assert main(["convert", str(path), str(out)]) == EXIT_OK
    assert LONG in out.read_text(encoding="utf-8")
    assert "자동 판별" in capsys.readouterr().err
    assert main(["convert", str(path), str(out), "--encoding", "cp949"]) == EXIT_OK
    assert "자동 판별" not in capsys.readouterr().err


def test_shape_applies_the_same_rules_as_the_server(srt, tmp_path):
    out = tmp_path / "shaped.srt"
    assert main(["shape", str(srt), str(out)]) == EXIT_OK
    events = pysubs2.load(str(out))
    # 긴 자막은 나뉘고, 나뉜 자막은 줄바꿈이 들어 있으며 글자는 하나도 사라지지 않습니다.
    assert len(events) == 3
    assert all(r"\N" in e.text for e in events[:2])
    joined = " ".join(e.plaintext.replace("\n", " ") for e in events[:2])
    assert joined == LONG
    assert events[0].start == 1000 and events[1].end == 4000


def test_shift_moves_times_and_reports_clamped_and_dropped(srt, tmp_path, capsys):
    out = tmp_path / "shifted.srt"
    assert main(["shift", str(srt), str(out), "--offset", "-2"]) == EXIT_OK
    events = pysubs2.load(str(out))
    assert (events[0].start, events[0].end) == (0, 2000) and events[1].start == 3000
    assert "0초에서 잘린 자막 1개" in capsys.readouterr().out
    assert main(["shift", str(srt), str(out), "--offset", "-5"]) == EXIT_OK
    assert "뺀 자막 1개" in capsys.readouterr().out
    # 모두 앞으로 나가면 파일을 쓰지 않습니다.
    assert main(["shift", str(srt), str(out), "--offset", "-10"]) == EXIT_ERROR


def test_shift_cues_never_loses_text():
    cues = [Cue(start=0, end=1, text="a"), Cue(start=2, end=4, text="b")]
    moved, clamped, dropped = shift_cues(cues, -2.5)
    assert [c.text for c in moved] == ["b"] and (clamped, dropped) == (1, 1)
    assert (moved[0].start, moved[0].end) == (0, 1.5)
    forward, _, _ = shift_cues(cues, 3)
    assert [(c.start, c.end) for c in forward] == [(3, 4), (5, 7)]


def test_cut_keeps_the_range_and_rebases_to_zero(srt, tmp_path, capsys):
    out = tmp_path / "cut.srt"
    assert main(["cut", str(srt), str(out), "--start", "2", "--end", "5.5"]) == EXIT_OK
    events = pysubs2.load(str(out))
    assert [(e.start, e.end) for e in events] == [(0, 2000), (3000, 3500)]
    assert main(["cut", str(srt), str(out), "--start", "5", "--end", "2"]) == EXIT_ERROR
    assert "구간" in capsys.readouterr().err


def test_templates_list_show_and_export(tmp_path, capsys):
    assert main(["templates", "list"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("[기본]") and "  default" in out and "예능 노랑" in out
    assert "[픽셀]" in out and "pixel-heart" in out
    assert main(["templates", "show", "box"]) == EXIT_OK
    shown = json.loads(capsys.readouterr().out)
    assert shown["name"] == "box" and shown["border_style"] == "box"
    exported = tmp_path / "box.json"
    assert main(["templates", "export", "box", str(exported)]) == EXIT_OK
    assert json.loads(exported.read_text(encoding="utf-8")) == shown
    assert main(["templates", "show", "nope"]) == EXIT_ERROR
    assert "모르는 자막 템플릿" in capsys.readouterr().err


def test_style_writes_an_ass_file_from_a_builtin_or_a_json_template(srt, tmp_path, capsys):
    out = tmp_path / "styled.ass"
    assert main(["style", str(srt), str(out), "--template", "yellow", "--title", "제목"]) == EXIT_OK
    subs = pysubs2.load(str(out))
    assert subs.info["PlayResX"] == "1080" and subs.info["PlayResY"] == "1920"
    assert subs.styles["Default"].bold and subs.styles["Default"].primarycolor.r == 255
    title = [e for e in subs.events if e.style == "Title"]
    assert len(title) == 1 and title[0].end == 6000 and title[0].plaintext == "제목"
    # 규칙이 적용돼 자막이 나뉩니다. --no-rules면 그대로입니다.
    assert len([e for e in subs.events if e.style == "Default"]) == 3
    assert main(["style", str(srt), str(out), "--no-rules"]) == EXIT_OK
    assert len(pysubs2.load(str(out)).events) == 2

    custom = tmp_path / "mine.json"
    assert main(["templates", "export", "minimal", str(custom)]) == EXIT_OK
    data = json.loads(custom.read_text(encoding="utf-8"))
    data.update(name="mine", font_size=48, position="top")
    custom.write_text(json.dumps(data), encoding="utf-8")
    args = ["style", str(srt), str(out), "--template", str(custom), "--width", "1920"]
    assert main([*args, "--height", "1080", "--font-size", "30", "--duration", "12"]) == EXIT_OK
    style = pysubs2.load(str(out)).styles["Default"]
    assert style.fontsize == 30 and style.alignment == pysubs2.Alignment.TOP_CENTER
    assert style.marginv == int(1080 * data["margin_vertical_ratio"])
    capsys.readouterr()
    assert main([*args, "--height", "1081"]) == EXIT_ERROR
    assert "짝수" in capsys.readouterr().err
    assert main([*args, "--height", "1080", "--font-size", "10"]) == EXIT_ERROR


def test_missing_or_unreadable_input_is_a_clean_error(tmp_path, capsys):
    assert main(["info", str(tmp_path / "none.srt")]) == EXIT_ERROR
    assert "읽지 못했습니다" in capsys.readouterr().err
    garbage = tmp_path / "garbage.srt"
    garbage.write_bytes(b"\xff\xfe\xfd not a subtitle at all")
    assert main(["info", str(garbage)]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "오류:" in err


def test_burn_needs_ffmpeg_and_checks_paths(srt, tmp_path, monkeypatch, capsys):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"not really a video")
    monkeypatch.setenv("R4_FFMPEG_BINARY", "")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert main(["burn", str(video), str(srt), str(tmp_path / "out.mp4")]) == EXIT_ERROR
    assert "ffmpeg" in capsys.readouterr().err
    missing = tmp_path / "no.mp4"
    assert main(["burn", str(missing), str(srt), str(tmp_path / "out.mp4")]) == EXIT_ERROR
    assert main(["burn", str(video), str(srt), str(video)]) == EXIT_ERROR


def test_rules_from_uses_language_defaults_then_overrides():
    parser = build_parser()
    assert rules_from(parser.parse_args(["check", "x"])) == DEFAULT_RULES
    assert rules_from(parser.parse_args(["check", "x", "--language", "en"])) == LANGUAGE_RULES["en"]
    rules = rules_from(parser.parse_args(["check", "x", "--language", "en", "--max-lines", "3"]))
    assert rules.max_lines == 3 and rules.max_cps == LANGUAGE_RULES["en"].max_cps
    with pytest.raises(ToolError):
        rules_from(parser.parse_args(["check", "x", "--max-lines", "0"]))


def test_output_format_detection():
    assert output_format(Path("a.SRT"), None) == "srt"
    assert output_format(Path("a.txt"), "vtt") == "vtt"
    with pytest.raises(ToolError):
        output_format(Path("a.txt"), None)


def ffmpeg_available() -> bool:
    return bool(os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg"))


def test_templates_check_reports_fonts_without_crashing(tmp_path, capsys):
    """fontconfig가 없으면 확인 불가, 있으면 이 컴퓨터의 글꼴로 판정합니다. 종료 코드만 봅니다."""
    code = main(["templates", "check"])
    out = capsys.readouterr().out
    assert code in (EXIT_OK, EXIT_VIOLATIONS)
    assert "Noto Sans CJK KR" in out and "글꼴 문제" in out
    assert main(["templates", "check", "--fonts-dir", str(tmp_path / "none")]) == EXIT_ERROR


def test_sheet_and_preview_render_a_png_when_ffmpeg_exists(tmp_path, capsys):
    if not ffmpeg_available():
        pytest.skip("FFmpeg required; CI installs it")
    out = tmp_path / "sheet.png"
    ass = tmp_path / "sheet.ass"
    assert main(["sheet", str(out), "--category", "pixel", "neon", "--ass", str(ass)]) == EXIT_OK
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    text = ass.read_text(encoding="utf-8")
    assert "Galmuri11 Regular" in text and "\\blur" in text
    assert "12종" in capsys.readouterr().out
    single = tmp_path / "one.png"
    assert (
        main(["preview", str(single), "--template", "yellow", "--text", "예문", "--height", "320"])
        == EXIT_OK
    )
    assert single.read_bytes()[:4] == b"\x89PNG"
    assert main(["sheet", str(out), "--category", "nope"]) == EXIT_ERROR
    assert main(["sheet", str(out), "--templates", "nope"]) == EXIT_ERROR
    assert main(["preview", str(single), "--background", "red"]) == EXIT_ERROR


def test_sheet_arguments_are_validated_before_ffmpeg_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("R4_FFMPEG_BINARY", "")
    monkeypatch.setattr("shutil.which", lambda name: None)
    # 인자 오류는 FFmpeg가 없어도 먼저 잡힙니다.
    assert main(["sheet", str(tmp_path / "s.png"), "--category", "nope"]) == EXIT_ERROR
    # 인자가 맞으면 FFmpeg 부재가 오류입니다.
    assert main(["sheet", str(tmp_path / "s.png"), "--category", "pixel"]) == EXIT_ERROR


def test_animation_option_overrides_the_template(srt, tmp_path, capsys):
    out = tmp_path / "moving.ass"
    assert (
        main(["style", str(srt), str(out), "--template", "yellow", "--animation", "pop"]) == EXIT_OK
    )
    assert "\\fscx40" in out.read_text(encoding="utf-8")
    assert (
        main(["style", str(srt), str(out), "--template", "pop-jalnan", "--animation", "none"])
        == EXIT_OK
    )
    assert "\\t(" not in out.read_text(encoding="utf-8")
    assert main(["style", str(srt), str(out), "--animation-ms", "10"]) == EXIT_ERROR
    assert "움직임" in capsys.readouterr().err
    # 영상 출력 인자는 FFmpeg를 부르기 전에 확인합니다.
    assert main(["preview", str(tmp_path / "a.webm"), "--seconds", "2"]) == EXIT_ERROR
    assert main(["preview", str(tmp_path / "a.mp4"), "--seconds", "0"]) == EXIT_ERROR
    assert main(["reel", str(tmp_path / "a.mp4"), "--category", "nope"]) == EXIT_ERROR
    assert main(["reel", str(tmp_path / "a.mp4"), "--seconds", "0"]) == EXIT_ERROR


def test_preview_and_reel_render_clips_when_ffmpeg_exists(tmp_path, capsys):
    if not ffmpeg_available():
        pytest.skip("FFmpeg required; CI installs it")
    clip = tmp_path / "pop.mp4"
    args = ["--template", "pop-jalnan", "--width", "320", "--height", "180", "--seconds", "1"]
    assert main(["preview", str(clip), *args]) == EXIT_OK
    assert clip.stat().st_size > 0 and "1초 영상" in capsys.readouterr().out
    gif = tmp_path / "reel.gif"
    ass = tmp_path / "reel.ass"
    assert (
        main(
            [
                "reel",
                str(gif),
                "--templates",
                "karaoke-yellow",
                "fade-film",
                "--width",
                "320",
                "--height",
                "180",
                "--seconds",
                "1",
                "--gap",
                "0",
                "--ass",
                str(ass),
            ]
        )
        == EXIT_OK
    )
    assert gif.read_bytes()[:6] in (b"GIF89a", b"GIF87a")
    assert "Caption" in ass.read_text(encoding="utf-8") and "2종을 2초" in capsys.readouterr().out


def test_stickers_list_and_style_with_stickers(srt, tmp_path, capsys):
    assert main(["stickers", "list"]) == EXIT_OK
    assert "arrow-right" in capsys.readouterr().out
    out = tmp_path / "s.ass"
    sticker = '{"kind":"star","x":0.8,"y":0.2,"size":120,"start":0,"end":1.5,"animation":"pop"}'
    assert main(["style", str(srt), str(out), "--sticker", sticker]) == EXIT_OK
    text = out.read_text(encoding="utf-8")
    assert "Style: Sticker" in text and "\\p1" in text and "\\fscx40" in text
    assert main(["style", str(srt), str(out), "--sticker", '{"kind":"nope"}']) == EXIT_ERROR
    assert "스티커" in capsys.readouterr().err
    # 이미지 스티커는 디렉터리가 있어야 굽습니다(FFmpeg 전에 잡힙니다).
    assert main(["burn", str(srt), str(srt), str(tmp_path / "o.mp4")]) == EXIT_ERROR


def test_presets_list_show_export_and_make_a_new_one(tmp_path, capsys, monkeypatch):
    assert main(["presets", "list"]) == EXIT_OK
    listed = capsys.readouterr().out
    assert "[기본 팩]" in listed and "[숏폼 팩]" in listed
    assert "from-below" in listed and "아래 등장" in listed
    assert "R4_PRESETS_DIR 없음" in listed

    assert main(["presets", "show", "blur-zoom"]) == EXIT_OK
    shown = json.loads(capsys.readouterr().out)
    assert shown["label"] == "블러 + 줌" and shown["steps"][0]["kind"] == "blur"

    mine = tmp_path / "mine.json"
    assert main(["presets", "export", "from-below", str(mine)]) == EXIT_OK
    assert json.loads(mine.read_text(encoding="utf-8"))["name"] == "from-below"

    fresh = tmp_path / "fresh.json"
    assert (
        main(["presets", "new", str(fresh), "--name", "my-move", "--label", "내 움직임"]) == EXIT_OK
    )
    made = json.loads(fresh.read_text(encoding="utf-8"))
    assert made["pack"] == "user" and made["steps"][0]["direction"] == "up"

    # 디렉터리에 넣으면 목록에 함께 나오고 이름으로 쓸 수 있습니다.
    monkeypatch.setenv("R4_PRESETS_DIR", str(tmp_path))
    assert main(["presets", "list"]) == EXIT_OK
    assert "my-move" in capsys.readouterr().out
    assert main(["presets", "check"]) == EXIT_OK
    assert "문제가 있습니다" in capsys.readouterr().out
    # 깨진 프리셋이 있으면 종료 코드가 달라져야 합니다. 위의 줄만으로는
    # `check`가 늘 EXIT_OK 를 돌려주도록 되돌아가도 시험이 통과합니다.
    # (지금 내장·사용자 프리셋 가운데 실제로 깨지는 것이 없어 찾은 결과를 넣어 둡니다.)
    monkeypatch.setattr(
        "pipeline.subtitle_tool._broken_presets", lambda presets: [("my-move", "일부러 깨뜨림")]
    )
    assert main(["presets", "check"]) == EXIT_ERROR
    assert "일부러 깨뜨림" in capsys.readouterr().out
    monkeypatch.undo()
    monkeypatch.setenv("R4_PRESETS_DIR", str(tmp_path))
    monkeypatch.delenv("R4_PRESETS_DIR")

    assert main(["presets", "show", "없는프리셋"]) == EXIT_ERROR


def test_style_applies_a_preset_by_name_or_json_file(srt, tmp_path):
    out = tmp_path / "styled.ass"
    assert main(["style", str(srt), str(out), "--preset", "from-below"]) == EXIT_OK
    text = pysubs2.load(str(out)).events[0].text
    assert "\\move(" in text and "\\alpha&HFF&" in text

    mine = tmp_path / "mine.json"
    assert main(["presets", "export", "quick-zoom", str(mine)]) == EXIT_OK
    assert main(["style", str(srt), str(out), "--preset", str(mine)]) == EXIT_OK
    assert "\\fscx58" in pysubs2.load(str(out)).events[0].text
    # 프리셋은 움직임보다 먼저 쓰입니다.
    assert main(["style", str(srt), str(out), "--preset", "quick-zoom", "--animation", "fade"]) == (
        EXIT_OK
    )
    assert "\\fscx58" in pysubs2.load(str(out)).events[0].text
    assert main(["style", str(srt), str(out), "--preset", "없는프리셋"]) == EXIT_ERROR


def test_presets_pack_and_import_make_files_you_can_keep(tmp_path, capsys, monkeypatch):
    import zipfile

    archive_path = tmp_path / "kinetic.zip"
    assert main(["presets", "pack", "kinetic", str(archive_path)]) == EXIT_OK
    assert "키네틱 팩 34종" in capsys.readouterr().out
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "읽어보기.txt" in names and "elastic-in.json" in names and len(names) == 35
        assert json.loads(archive.read("elastic-in.json"))["label"] == "탱탱볼 등장"
    assert main(["presets", "pack", "nope", str(archive_path)]) == EXIT_ERROR

    exported = tmp_path / "mine.json"
    assert main(["presets", "export", "bob", str(exported)]) == EXIT_OK
    capsys.readouterr()
    # 디렉터리를 알려 주지 않으면 넣을 곳이 없습니다.
    assert main(["presets", "import", str(exported)]) == EXIT_ERROR
    directory = tmp_path / "mine"
    directory.mkdir()
    monkeypatch.setenv("R4_PRESETS_DIR", str(directory))
    # 내장과 같은 이름은 막습니다.
    assert main(["presets", "import", str(exported)]) == EXIT_ERROR
    body = json.loads(exported.read_text(encoding="utf-8"))
    body["name"] = "my-bob"
    exported.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    assert main(["presets", "import", str(exported)]) == EXIT_OK
    stored = json.loads((directory / "my-bob.json").read_text(encoding="utf-8"))
    assert stored["pack"] == "user"
    assert main(["presets", "list"]) == EXIT_OK
    assert "my-bob" in capsys.readouterr().out
    # 넣은 프리셋은 바로 영상 자막에 쓸 수 있습니다.
    assert main(["presets", "show", "my-bob"]) == EXIT_OK


def _report_json(out: str) -> dict:
    """읽은 파일 요약 줄 뒤에 붙는 JSON만 떼어 냅니다."""
    return json.loads(out[out.index("{") :])


def test_quality_summarises_a_file_and_shows_what_pacing_changes(srt, capsys):
    assert main(["quality", str(srt), "--language", "ko"]) == EXIT_OK
    plain = capsys.readouterr().out
    assert "표시 시간" in plain and "읽기 속도" in plain and "화면에 떠 있는 시간" in plain

    assert main(["quality", str(srt), "--json"]) == EXIT_OK
    report = _report_json(capsys.readouterr().out)
    assert report["count"] >= 1 and "duration" in report and "violations" in report

    # 숏폼 규칙으로 다시 끊으면 자막이 늘고 짧아집니다.
    assert main(["quality", str(srt), "--pacing", "shortform", "--shape", "--json"]) == EXIT_OK
    short = _report_json(capsys.readouterr().out)
    assert short["count"] > report["count"]
    assert short["duration"]["median"] < report["duration"]["median"]

    # 모르는 끊기 방식은 argparse가 먼저 막습니다(쓸 수 있는 값을 함께 보여 줍니다).
    with pytest.raises(SystemExit):
        main(["quality", str(srt), "--pacing", "tiktok"])


def test_style_can_use_the_shortform_pacing(srt, tmp_path):
    def burned(*extra: str) -> list[str]:
        out = tmp_path / f"styled{len(extra)}.ass"
        assert main(["style", str(srt), str(out), *extra]) == EXIT_OK
        return [e.plaintext for e in pysubs2.load(str(out)).events if e.style == "Default"]

    plain, short = burned(), burned("--pacing", "shortform")
    assert len(short) > len(plain)
    assert max(text_width(line.replace("\n", " ")) for line in short) < max(
        text_width(line.replace("\n", " ")) for line in plain
    )
    # 자막 파일에는 단어 시각이 없어 글자 수로 나눕니다. 표시 시간이 모자라면 더 나누지
    # 못해 두 줄이 남을 수 있고, 그것은 quality가 위반으로 보고합니다.
    assert any("\n" not in line for line in short)
