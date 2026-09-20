#!/usr/bin/env python3
"""Run the isolated CPU benchmark outside Docker's VM memory limit.

Requires an explicitly prepared Python environment and compatibility overlay.
Creates a NEW private output directory. No production tokens are inherited.
"""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "dependencies", "model", "manifest", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 7200:
        parser.error("Timeout must be 1–7200 seconds")
    scripts = Path(__file__).resolve().parent
    root = scripts.parent
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    environment = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG") if k in os.environ}
    environment.update(
        HF_HOME=str(args.output.resolve() / "hf"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        WANDB_MODE="disabled",
        OMP_NUM_THREADS="2",
        TOKENIZERS_PARALLELISM="false",
        PYTHONPATH=os.pathsep.join(
            map(
                str,
                [
                    args.dependencies.resolve(),
                    root / "packages/pipeline",
                    root / "services/worker",
                    scripts,
                ],
            )
        ),
    )
    command = [
        str(args.python.resolve()),
        str(scripts / "benchmark_target_asr.py"),
        "--model",
        str(args.model.resolve()),
        "--manifest",
        str(args.manifest.resolve()),
        "--output",
        str(args.output.resolve() / "results.json"),
        "--device",
        "cpu",
    ]
    # Do not resolve a venv executable symlink: doing so bypasses that environment.
    command[0] = str(args.python.absolute())
    timed_out = False
    with (args.output / "run.log").open("x") as log:
        try:
            completed = subprocess.run(
                command,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds,
            )
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code, timed_out = 124, True
    status = dict(
        exit_code=code,
        timed_out=timed_out,
        device="cpu",
        dtype="float32",
        manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        deploy_allowed=False,
    )
    (args.output / "status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
