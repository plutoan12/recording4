"""세로형 자막: 명시적인 어절 시각과 고정 레이아웃을 사용하는 ASS 출력."""

import argparse
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import imageio_ffmpeg
import pysubs2
from PIL import ImageFont

from pipeline.motion_templates import PRESETS, bgr, literal

STYLES = ("clean-focus", "marker-follow", "soft-pop")


def validate(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("version: 1인 JSON을 사용하세요.")
    if data.get("timing_source") not in {"manual", "aligned", "estimated"}:
        raise ValueError("timing_source는 manual/aligned/estimated 중 하나입니다.")
    cues = data.get("cues")
    if not isinstance(cues, list) or not cues:
        raise ValueError("cues가 비어 있습니다.")
    previous = 0
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("cue는 객체여야 합니다.")
        start, end = cue.get("start_ms"), cue.get("end_ms")
        if type(start) is not int or type(end) is not int or not previous <= start < end:
            raise ValueError("자막 시각은 겹치지 않는 양의 길이의 정수 ms여야 합니다.")
        words = cue.get("words")
        if not isinstance(words, list) or not words:
            raise ValueError("words가 비어 있습니다.")
        last = start
        for word in words:
            if not isinstance(word, dict):
                raise ValueError("word는 객체여야 합니다.")
            text = word.get("text")
            a, z = word.get("start_ms"), word.get("end_ms")
            if not isinstance(text, str) or not text.strip() or any(c.isspace() for c in text):
                raise ValueError("각 word.text는 공백 없는 어절이어야 합니다.")
            if type(a) is not int or type(z) is not int or not last <= a < z <= end:
                raise ValueError("단어 시각은 자막 안에서 겹치지 않아야 합니다.")
            if a % 10 or z % 10 or start % 10 or end % 10:
                raise ValueError("ASS 정밀도에 맞춰 시각을 10ms 단위로 입력하세요.")
            last = z
        expected = " ".join(w["text"] for w in words)
        if cue.get("text", expected) != expected:
            raise ValueError("text와 words가 다릅니다. 대사 수정 후 단어 시각도 확인하세요.")
        for field in ("translation", "speaker"):
            if field in cue:
                value = cue[field]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field}는 비어 있지 않은 문자열이어야 합니다.")
                if any(ord(char) < 32 for char in value):
                    raise ValueError(f"{field}에는 줄바꿈/제어 문자를 넣지 마세요.")
        previous = end
    return data


def layout(words, font_path):
    """어절을 자르지 않고 실제 폰트 폭으로 두 줄까지 배치한다."""
    for size in range(64, 43, -2):
        font = ImageFont.truetype(str(font_path), size)
        space = font.getlength(" ")
        rows, row, width = [], [], 0
        for i, word in enumerate(words):
            advance = font.getlength(literal(word["text"])) + 10
            if advance > 820:
                break
            if row and width + space + advance > 820:
                rows.append((row, width))
                row, width = [], 0
            x = width + (space if row else 0)
            row.append((i, x, advance))
            width = x + advance
        else:
            rows.append((row, width))
            if len(rows) <= 2:
                positions = {}
                for n, (items, row_width) in enumerate(rows):
                    for i, x, advance in items:
                        positions[i] = (
                            540 - row_width / 2 + x + advance / 2,
                            1190 + n * 100,
                            advance,
                        )
                return size, positions
    raise ValueError("두 줄 안에 들어가지 않습니다. 자막을 의미 단위로 나누세요.")


def fit_label(text, font_path, maximum=42, minimum=30, max_lines=2):
    """고정 보조 영역에 들어가는 텍스트만 허용; 어절을 임의로 자르지 않는다."""
    for size in range(maximum, minimum - 1, -2):
        font = ImageFont.truetype(str(font_path), size)
        lines = [""]
        for word in text.split():
            if font.getlength(literal(word)) > 820:
                break
            candidate = (lines[-1] + " " + word).strip()
            if font.getlength(literal(candidate)) <= 820:
                lines[-1] = candidate
            else:
                lines.append(word)
        else:
            if len(lines) <= max_lines:
                return size, "\n".join(lines)
    raise ValueError("보조 자막/이름표가 영역을 넘습니다. 내용을 줄여 주세요.")


def plain_tracks(data):
    """원문·번역·이중 자막을 서로 다른 파일로 보존한다."""
    tracks = {name: pysubs2.SSAFile() for name in ("source", "translated", "bilingual")}
    for cue in data["cues"]:
        original = " ".join(w["text"] for w in cue["words"])
        translation = cue.get("translation")
        texts = {"source": original, "bilingual": original}
        if translation:
            texts["translated"] = translation
            texts["bilingual"] += "\n" + translation
        for name, text in texts.items():
            event = pysubs2.SSAEvent(start=cue["start_ms"], end=cue["end_ms"])
            event.plaintext = text
            tracks[name].append(event)
    return tracks


def create(data, font_path, style="clean-focus", theme="cinema"):
    validate(data)
    if style not in STYLES or theme not in PRESETS:
        raise ValueError("알 수 없는 스타일/테마입니다.")
    accent = bgr(PRESETS[theme]["accent"])
    result = pysubs2.SSAFile()
    result.info.update(PlayResX="1080", PlayResY="1920", WrapStyle="2")
    result.styles["Default"] = pysubs2.SSAStyle(
        fontname="Noto Sans KR", fontsize=64, bold=False, outline=2, shadow=0
    )
    plain = plain_tracks(data)["source"]
    speakers = list(dict.fromkeys(c["speaker"] for c in data["cues"] if "speaker" in c))
    speaker_colors = ("67E8F9", "F9A8D4", "FDE68A", "C4B5FD")
    for cue in data["cues"]:
        words = cue["words"]
        size, positions = layout(words, font_path)
        start, end = cue["start_ms"], cue["end_ms"]
        cue_accent = accent
        if "speaker" in cue:
            cue_accent = bgr(speaker_colors[speakers.index(cue["speaker"]) % len(speaker_colors)])
            label_size, label = fit_label(cue["speaker"], font_path, 34, 26, 1)
            tags = rf"\an5\pos(540,1080)\fs{label_size}\c&H{cue_accent}&\bord0"
            result.append(
                pysubs2.SSAEvent(
                    start=start, end=end, layer=2, text="{" + tags + "}" + literal(label)
                )
            )
        if "translation" in cue:
            sub_size, sub_text = fit_label(cue["translation"], font_path)
            tags = rf"\an8\pos(540,1380)\fs{sub_size}\c&HDCE2EC&\bord1"
            result.append(
                pysubs2.SSAEvent(
                    start=start, end=end, layer=2, text="{" + tags + "}" + literal(sub_text)
                )
            )
        boundaries = sorted({start, end, *(w[k] for w in words for k in ("start_ms", "end_ms"))})
        for a, z in zip(boundaries, boundaries[1:], strict=False):
            for i, word in enumerate(words):
                active = word["start_ms"] <= a < word["end_ms"]
                x, y, width = positions[i]
                tags = rf"\an5\pos({x:.2f},{y})\fs{size}\c&HFFFFFF&\3c&H151515&"
                if active and style == "marker-follow":
                    box = (
                        rf"{{\an7\pos({x-width/2-6:.2f},{y-size*.8:.2f})"
                        rf"\p1\bord0\c&H{cue_accent}&}}"
                    )
                    h = size * 1.6
                    box += f"m 0 0 l {width+12:.2f} 0 l {width+12:.2f} {h:.2f} l 0 {h:.2f}"
                    result.append(pysubs2.SSAEvent(start=a, end=z, text=box, layer=0))
                    tags += r"\c&H151515&\bord0"
                elif active:
                    tags += rf"\c&H{cue_accent}&"
                    if style == "soft-pop":
                        ms = min(120, (z - a) // 2)
                        tags += rf"\fscx106\fscy106\t(0,{ms},\fscx100\fscy100)"
                result.append(
                    pysubs2.SSAEvent(
                        start=a, end=z, text="{" + tags + "}" + literal(word["text"]), layer=1
                    )
                )
    return result, plain


def build(source, output, fonts, style="clean-focus", theme="cinema", render=True, audio=None):
    if output.exists():
        raise ValueError("기존 결과는 덮어쓰지 않습니다.")
    for name in ("NotoSansKR.ttf", "OFL.txt"):
        if not (fonts / name).is_file():
            raise ValueError(f"필요한 폰트/라이선스: {name}")
    data = validate(json.loads(source.read_text(encoding="utf-8")))
    ass, plain = create(data, fonts / "NotoSansKR.ttf", style, theme)
    duration_ms = data["cues"][-1]["end_ms"] + 500
    if audio is not None:
        with wave.open(str(audio)) as stream:
            duration_ms = max(
                duration_ms, round(stream.getnframes() / stream.getframerate() * 1000)
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".portrait-", dir=output.parent) as tmp:
        root = Path(tmp) / "result"
        root.mkdir()
        (root / "fonts").mkdir()
        for name in ("NotoSansKR.ttf", "OFL.txt"):
            shutil.copyfile(fonts / name, root / "fonts" / name)
        ass.save(str(root / "editable.ass"))
        plain.save(str(root / "captions.srt"))
        plain.save(str(root / "captions.vtt"))
        if any("translation" in cue for cue in data["cues"]):
            tracks = plain_tracks(data)
            for name in ("translated", "bilingual"):
                for extension in ("srt", "vtt"):
                    tracks[name].save(str(root / f"{name}.{extension}"))
        (root / "words.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report = dict(
            style=style,
            theme=theme,
            timing_source=data["timing_source"],
            resolution=[1080, 1920],
            rendered=render,
            audio_included=audio is not None and render,
            translated_cues=sum("translation" in c for c in data["cues"]),
            untranslated_cues=sum("translation" not in c for c in data["cues"]),
            speakers=list(dict.fromkeys(c["speaker"] for c in data["cues"] if "speaker" in c)),
            limits=[
                "번역과 화자는 입력값 사용. 자동 번역/화자 인식은 실행하지 않음.",
                (
                    "MP4에 입력 음성을 포함함. 정렬 출처는 words.json 참고."
                    if audio is not None
                    else "MP4는 무음 미리보기. 원음 인식/강제 정렬은 실행하지 않음."
                ),
                "SRT/VTT는 문장 자막. 단어 시각은 words.json에 보존.",
                "기존 15종의 색상 테마만 재사용. 가로형 장식/모션은 복제하지 않음.",
                "중괄호·역슬래시는 전각으로 표시. 네이티브 편집 앱 미검증.",
            ],
        )
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if render:
            subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-v",
                    "error",
                    "-n",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x111827:s=1080x1920:r=30",
                    *(
                        [
                            "-i",
                            str(audio.resolve()),
                            "-map",
                            "0:v:0",
                            "-map",
                            "1:a:0",
                            "-c:a",
                            "aac",
                            "-af",
                            "apad",
                        ]
                        if audio is not None
                        else []
                    ),
                    "-vf",
                    "ass=editable.ass:fontsdir=fonts",
                    "-t",
                    str(duration_ms / 1000),
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
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        root.rename(output)


def main():
    parser = argparse.ArgumentParser(description="세로형 단어 강조 자막 제작")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--style", choices=STYLES, default=STYLES[0])
    parser.add_argument("--theme", choices=PRESETS, default="cinema")
    parser.add_argument("--fonts", type=Path, default=Path(".runtime/external-fonts"))
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    try:
        build(args.input, args.output, args.fonts, args.style, args.theme, not args.no_render)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"제작 실패: {exc}\n")
    print(f"생성 완료: {args.output}")


if __name__ == "__main__":
    main()
