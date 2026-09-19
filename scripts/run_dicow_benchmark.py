#!/usr/bin/env python3
"""Run a prepared DiCoW checkpoint offline, without production secrets.

The audio root must contain only benchmark audio; it is mounted read-only.
Install requirements-dicow.txt into a dedicated --dependencies directory first.
"""

import argparse
import subprocess
from pathlib import Path

from ops import docker_environment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["model", "manifest", "audio-root", "output", "dependencies"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--image", default="recording4-stack-worker")
    p.add_argument("--quantize", action="store_true")
    p.add_argument("--ctc-weight", type=float, default=0.0)
    args = p.parse_args()
    # Do not mount the production runtime root (which contains credentials).
    if (args.audio_root / "production.env").exists():
        p.error("audio-root must be a dedicated audio-only directory")
    args.output.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        "0:0",
        "--network",
        "none",
        "--memory",
        "7g",
        "--cpus",
        "2",
        "--entrypoint",
        "python",
        "-e",
        "HF_HUB_OFFLINE=1",
        "-e",
        "OMP_NUM_THREADS=2",
        "-e",
        "PYTHONPATH=/deps:/scripts:/app/services/worker:/app/services/api:/app/packages/pipeline",
    ]
    for source, destination in [
        (args.model, "/model"),
        (args.manifest, "/manifest.json"),
        (args.audio_root, "/data"),
        (args.dependencies, "/deps"),
        (Path(__file__).resolve().parent, "/scripts"),
    ]:
        command += ["-v", f"{source.resolve()}:{destination}:ro"]
    command += [
        "-v",
        f"{args.output.resolve()}:/results",
        args.image,
        "/scripts/benchmark_target_asr.py",
        "--model",
        "/model",
        "--manifest",
        "/manifest.json",
        "--output",
        "/results/results.json",
        "--ctc-weight",
        str(args.ctc_weight),
    ]
    if args.quantize:
        command.append("--quantize")
    with (args.output / "run.log").open("w") as log:
        subprocess.run(command, env=docker_environment(), stdout=log, stderr=log, check=True)
    print(args.output / "results.json")


if __name__ == "__main__":
    main()
