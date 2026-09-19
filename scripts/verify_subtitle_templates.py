"""Offline FFmpeg smoke test for every subtitle template. No external API calls."""

import argparse
import array
import json
import subprocess
from pathlib import Path

from pipeline.editing import Cue
from pipeline.subtitle_templates import TEMPLATES
from worker.composition import ffmpeg, render_final


def pcm(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    samples = array.array("f")
    samples.frombytes(result.stdout)
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    output.mkdir(exist_ok=True, parents=True)
    source = output / "source.mp4"
    ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=0x20384c:s=360x640:r=24:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ]
    )
    original = pcm(source)
    cues = [
        Cue(start=0, end=2, text="안녕하세요", speaker="A", original_text="Hello"),
        Cue(
            start=2, end=4, text="원래 음성 유지", speaker="B", original_text="Keep original audio"
        ),
    ]
    report = []
    for template in TEMPLATES:
        target = output / f"{template['id']}.mp4"
        render_final(
            source,
            target,
            cues=cues,
            duration=4,
            width=360,
            height=640,
            subtitle_template=template["id"],
        )
        audio = pcm(target)
        n = min(len(audio), len(original))
        # AAC is re-encoded; compare normalized waveform rather than encoded bytes.
        similarity = (
            sum(x * y for x, y in zip(original[:n], audio[:n], strict=False))
            / (sum(x * x for x in original[:n]) * sum(x * x for x in audio[:n])) ** 0.5
        )
        assert similarity > 0.98, (template["id"], similarity)
        ffmpeg(["-i", str(target), "-f", "null", "-"])
        ffmpeg(
            ["-ss", "1", "-i", str(target), "-frames:v", "1", str(output / f"{template['id']}.png")]
        )
        report.append(
            {"template": template["id"], "audio_similarity": round(similarity, 6), "decoded": True}
        )
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
