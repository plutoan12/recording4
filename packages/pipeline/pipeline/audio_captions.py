"""음성 → 실제 단어 시각 → 세로형 강조 자막. 공급자는 로컬 Docker에서 실행."""

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import imageio_ffmpeg

from pipeline.motion_templates import PRESETS
from pipeline.portrait_captions import STYLES, build, layout, validate


def map_words(raw):
    """모델의 서브 토큰을 원문 어절로 합친다. 균등 시간 분할은 하지 않는다."""
    tokens = raw["words"]
    expected = raw["text"].split()
    if not tokens or not expected:
        raise ValueError("발화 단어를 찾지 못했습니다.")

    def clean(text):
        return "".join(text.split())

    if "".join(clean(t["text"]) for t in tokens) != "".join(expected):
        raise ValueError("대본과 정렬 결과가 다릅니다. 대본/언어를 확인하세요.")
    output, index = [], 0
    for word in expected:
        consumed, group = "", []
        while len(consumed) < len(word) and index < len(tokens):
            token = tokens[index]
            consumed += clean(token["text"])
            group.append(token)
            index += 1
        if consumed != word:
            raise ValueError("모델 토큰이 어절 경계를 가로지릅니다. 추정 분할하지 않습니다.")
        for token in group:
            a, z = token["start"], token["end"]
            if not all(isinstance(t, int | float) and math.isfinite(t) for t in (a, z)):
                raise ValueError("유효하지 않은 모델 시각입니다.")
            if a < 0 or z < a:
                raise ValueError("역전된 모델 시각입니다.")
        if any(
            b["start"] < a["start"] or b["end"] < a["end"]
            for a, b in zip(group, group[1:], strict=False)
        ):
            raise ValueError("어절 내부 토큰 시각이 역전됐습니다.")
        start = round(group[0]["start"] * 100) * 10
        end = round(group[-1]["end"] * 100) * 10
        if end <= start:
            raise ValueError("길이가 0인 단어가 있습니다. 대본/오디오를 확인하세요.")
        if output and start < output[-1]["end_ms"]:
            raise ValueError("단어 시각이 겹칩니다. 원본 정렬 결과를 검토하세요.")
        output.append(dict(text=word, start_ms=start, end_ms=end))
    return output


def pack_words(words, font_path):
    """폰트 폭과 발화 간격으로 묶되 정렬된 단어 시각은 변경하지 않는다."""
    cues, group = [], []

    def flush():
        if group:
            cues.append(
                dict(
                    start_ms=group[0]["start_ms"],
                    end_ms=group[-1]["end_ms"],
                    text=" ".join(w["text"] for w in group),
                    words=list(group),
                )
            )
            group.clear()

    for word in words:
        split = bool(
            group
            and (
                word["start_ms"] - group[-1]["end_ms"] >= 600
                or word["end_ms"] - group[0]["start_ms"] > 3500
                or len(group) >= 6
            )
        )
        if not split:
            try:
                layout(group + [word], font_path)
            except ValueError:
                split = True
        if split:
            flush()
        layout([word], font_path)
        group.append(word)
        if word["text"].endswith((".", "?", "!")):
            flush()
    flush()
    return validate(dict(version=1, timing_source="aligned", cues=cues))


def run(
    source,
    output,
    fonts,
    script=None,
    model="small",
    language="ko",
    style="clean-focus",
    theme="pop",
    image="recording4-stack-worker",
    cache="recording4-stack_models",
):
    if output.exists():
        raise ValueError("기존 결과는 덮어쓰지 않습니다.")
    if not source.is_file():
        raise ValueError("입력 음성/영상 파일이 없습니다.")
    for name in ("NotoSansKR.ttf", "OFL.txt"):
        if not (fonts / name).is_file():
            raise ValueError(f"필요한 폰트/라이선스: {name}")
    script_text = script.read_text(encoding="utf-8") if script else None
    if script_text is not None and not script_text.strip():
        raise ValueError("정렬할 대본이 비어 있습니다.")
    provider = Path(__file__).with_name("audio_provider.py").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".audio-caption-", dir=output.parent) as tmp:
        root = Path(tmp).resolve()
        wav = root / "audio.wav"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-v",
                "error",
                "-n",
                "-i",
                str(source.resolve()),
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with wave.open(str(wav)) as audio:
            duration = audio.getnframes() / audio.getframerate()
        args = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            "HF_HUB_OFFLINE=1",
            "-e",
            "HF_HUB_DISABLE_TELEMETRY=1",
            "-v",
            f"{cache}:/home/appuser/.cache:ro",
            "-v",
            f"{root}:/work",
            "-v",
            f"{provider}:/extract.py:ro",
            "--entrypoint",
            "python",
            image,
            "/extract.py",
            "/work/audio.wav",
            "/work/raw.json",
            "--model",
            model,
            "--language",
            language,
        ]
        if script_text is not None:
            (root / "script.txt").write_text(script_text, encoding="utf-8")
            args += ["--script", "/work/script.txt"]
        subprocess.run(args, check=True, capture_output=True, text=True)
        raw = json.loads((root / "raw.json").read_text())
        words = map_words(raw)
        if words[-1]["end_ms"] > duration * 1000 + 10:
            raise ValueError("단어 시각이 오디오 길이를 넘습니다.")
        data = pack_words(words, fonts / "NotoSansKR.ttf")
        with source.open("rb") as stream:
            source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        data["alignment"] = dict(
            provider="stable-ts" if script else "faster-whisper",
            mode=raw["mode"],
            model=model,
            language=language,
            source_sha256=source_hash,
            timing_precision_ms=10,
            note="모델이 계산한 시각. 단어별 정확도는 사람이 검수해야 합니다.",
        )
        (root / "words.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        build(root / "words.json", root / "pack", fonts, style, theme, audio=wav)
        (root / "pack/raw-alignment.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        (root / "pack").rename(output)


def main():
    parser = argparse.ArgumentParser(
        description="실제 음성을 정렬하고 소리 있는 강조 자막 영상 제작"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--script", type=Path, help="교정한 UTF-8 대본. 없으면 자동 전사")
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--fonts", type=Path, default=Path(".runtime/external-fonts"))
    parser.add_argument("--style", choices=STYLES, default="clean-focus")
    parser.add_argument("--theme", choices=PRESETS, default="pop")
    parser.add_argument("--image", default="recording4-stack-worker")
    parser.add_argument("--cache", default="recording4-stack_models")
    args = parser.parse_args()
    try:
        run(
            args.input,
            args.output,
            args.fonts,
            args.script,
            args.model,
            args.language,
            args.style,
            args.theme,
            args.image,
            args.cache,
        )
    except subprocess.CalledProcessError as exc:
        parser.exit(2, "음성 처리 실패: " + exc.stderr[-1800:] + "\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"음성 처리 실패: {exc}\n")
    print(f"생성 완료: {args.output}")


if __name__ == "__main__":
    main()
