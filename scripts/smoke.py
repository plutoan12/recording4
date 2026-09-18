#!/usr/bin/env python3
"""Paid-call-free end-to-end check against running PostgreSQL, Redis, S3 and FFmpeg."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

from ops import ENV_FILE, RUNTIME, compose


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--stt",
        action="store_true",
        help="Use local speech recognition; may download model weights",
    )
    args = parser.parse_args()
    values = dict(
        line.split("=", 1)
        for line in ENV_FILE.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    base = values["R4_S3_PUBLIC_ENDPOINT_URL"]
    token = None

    def request(path, method="GET", body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body).encode()
        with urllib.request.urlopen(
            urllib.request.Request(base + "/api" + path, data=data, headers=headers, method=method),
            timeout=30,
        ) as response:
            return json.load(response)

    token = request(
        "/auth/login",
        "POST",
        {"email": values["R4_ADMIN_EMAIL"], "password": values["R4_ADMIN_PASSWORD"]},
    )["access_token"]
    if args.source:
        media = args.source.resolve()
    else:
        media = RUNTIME / "smoke-source.mp4"
        with media.open("wb") as stream:
            compose(
                "exec",
                "-T",
                "worker",
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=24:duration=8",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=8",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-movflags",
                "frag_keyframe+empty_moov",
                "-f",
                "mp4",
                "pipe:1",
                stdout=stream,
            )
    created = request(
        "/source-assets",
        "POST",
        {"filename": media.name, "byte_size": media.stat().st_size},
    )
    with urllib.request.urlopen(
        urllib.request.Request(created["upload_url"], data=media.read_bytes(), method="PUT"),
        timeout=60,
    ):
        pass
    aid = created["source_asset_id"]
    request(f"/source-assets/{aid}/complete", "POST", {})
    for _ in range(90):
        asset = request(f"/source-assets/{aid}")
        if asset["upload_state"] == "verified":
            break
        if asset["upload_state"] == "rejected":
            raise RuntimeError("Source verification rejected")
        time.sleep(2)
    else:
        raise TimeoutError("Source verification stalled")
    job = request(
        "/jobs",
        "POST",
        {
            "source_asset_id": aid,
            "target_language": "en",
            "workflow": {
                "audio_mode": "original",
                "clip": {
                    "start": 1,
                    "end": 7,
                    "width": 360,
                    "height": 640,
                    "title": "recording4 test",
                },
                **(
                    {}
                    if args.stt
                    else {
                        "transcript": [
                            {"start": 1, "end": 4, "text": "Automated local workflow test"}
                        ]
                    }
                ),
                "budget_usd": "0",
            },
        },
    )
    for _ in range(180):
        detail = request(f'/jobs/{job["id"]}/workflow')
        if detail["state"] == "review_required":
            break
        if detail["state"] in ("failed", "blocked"):
            raise RuntimeError(f'Workflow stopped: {detail["reason"]}')
        time.sleep(2)
    else:
        raise TimeoutError("Workflow stalled")
    preview = request(f'/artifacts/{detail["artifact_id"]}/preview')
    target = RUNTIME / "smoke-final.mp4"
    with urllib.request.urlopen(preview["url"], timeout=60) as response:
        target.write_bytes(response.read())
    with target.open("rb") as stream:
        compose(
            "exec",
            "-T",
            "worker",
            "ffmpeg",
            "-v",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "null",
            "-",
            stdin=stream,
        )
    report = {
        "source_id": aid,
        "job_id": job["id"],
        "state": detail["state"],
        "artifact_id": detail["artifact_id"],
        "file": str(target),
        "stages": detail["stages"],
        "paid_calls": 0,
        "youtube_uploads": 0,
    }
    (RUNTIME / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
