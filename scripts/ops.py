#!/usr/bin/env python3
"""Private local deployment; secrets are written to files, never printed."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import secrets
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
ENV_FILE = RUNTIME / "production.env"


def initialize():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if ENV_FILE.exists():
        return
    password = secrets.token_hex(24)
    config = {
        "R4_DB_PASSWORD": password,
        "R4_DATABASE_URL": f"postgresql+psycopg://recording4:{password}@postgres:5432/recording4",
        "R4_REDIS_URL": "redis://redis:6379/0",
        "R4_JWT_SECRET": secrets.token_hex(32),
        "R4_ADMIN_EMAIL": "admin@recording4.example.com",
        "R4_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        "R4_S3_ENDPOINT_URL": "http://minio:9000",
        "R4_S3_PUBLIC_ENDPOINT_URL": "http://localhost:18444",
        "R4_S3_BUCKET": "recording4",
        "R4_S3_ACCESS_KEY_ID": "r4" + secrets.token_hex(8),
        "R4_S3_SECRET_ACCESS_KEY": secrets.token_hex(24),
        "R4_S3_REGION": "us-east-1",
        "R4_S3_FORCE_PATH_STYLE": "true",
        "R4_SITE_ADDRESS": "http://localhost",
        "R4_BIND_IP": "127.0.0.1",
        "R4_HTTP_PORT": "18444",
        "R4_HTTPS_PORT": "18445",
        "R4_BACKUP_DIR": str(RUNTIME / "backups"),
        "R4_PAID_PROCESSING_ENABLED": "false",
        "R4_YOUTUBE_UPLOAD_ENABLED": "false",
        "R4_WHISPER_MODEL": "small",
        "R4_WHISPER_DEVICE": "cpu",
    }
    (RUNTIME / "backups").mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in config.items()))
    print(f"Private settings created: {ENV_FILE}")


def compose(*args, **kwargs):
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(ROOT / "infra/compose.runtime.yml"),
            *args,
        ],
        env={**os.environ, "R4_ENV_FILE": str(ENV_FILE)},
        check=True,
        **kwargs,
    )


def main():
    parser = argparse.ArgumentParser(description="recording4 local operations")
    parser.add_argument(
        "command",
        choices=[
            "init",
            "up",
            "status",
            "stop",
            "backup",
            "check",
            "credentials-path",
            "restore-check",
            "install-startup",
            "login-start",
        ],
    )
    args = parser.parse_args()
    initialize()
    if args.command == "up":
        compose("up", "-d", "--build", "--wait", "--wait-timeout", "300")
    elif args.command == "status":
        compose("ps")
    elif args.command == "stop":
        compose("stop")
    elif args.command == "check":
        compose("exec", "-T", "monitor", "python", "-m", "worker.operations", "--once")
    elif args.command == "backup":
        target = RUNTIME / "backups" / f"manual-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump"
        with target.open("wb") as stream:
            compose(
                "exec",
                "-T",
                "postgres",
                "pg_dump",
                "-U",
                "recording4",
                "-d",
                "recording4",
                "-Fc",
                stdout=stream,
            )
        target.chmod(0o600)
        compose(
            "exec",
            "-T",
            "monitor",
            "python",
            "-c",
            "from pathlib import Path; from worker.backup import snapshot; "
            "print(snapshot(Path('/backups/media')))",
        )
        print(json.dumps({"backup": str(target)}))
    elif args.command == "restore-check":
        dumps = sorted((RUNTIME / "backups").glob("*.dump"), key=lambda p: p.stat().st_mtime)
        if not dumps:
            raise SystemExit("Run backup first.")
        database = "r4_verify_" + uuid.uuid4().hex[:12]
        compose("exec", "-T", "postgres", "createdb", "-U", "recording4", database)
        try:
            with dumps[-1].open("rb") as stream:
                compose(
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--exit-on-error",
                    "-U",
                    "recording4",
                    "-d",
                    database,
                    stdin=stream,
                )
            compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "recording4",
                "-d",
                database,
                "-c",
                "SELECT count(*) AS restored_jobs FROM jobs",
            )
        finally:
            compose("exec", "-T", "postgres", "dropdb", "-U", "recording4", database)
        print("Isolated database restore verified; live database unchanged.")
    elif args.command == "login-start":
        subprocess.run(["/usr/bin/open", "-a", "Docker"], check=True)
        for _ in range(90):
            if (
                subprocess.run(
                    ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                ).returncode
                == 0
            ):
                compose("up", "-d", "--wait", "--wait-timeout", "300")
                break
            time.sleep(2)
        else:
            raise SystemExit("Docker engine did not become ready.")
    elif args.command == "install-startup":
        path = Path.home() / "Library/LaunchAgents/com.recording4.stack.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SystemExit("Startup entry already exists; inspect it before changing.")
        entry = {
            "Label": "com.recording4.stack",
            "RunAtLoad": True,
            "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "login-start"],
            "WorkingDirectory": str(ROOT),
            "EnvironmentVariables": {
                "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            },
            "StandardOutPath": str(RUNTIME / "startup.log"),
            "StandardErrorPath": str(RUNTIME / "startup-error.log"),
        }
        path.write_bytes(plistlib.dumps(entry))
        path.chmod(0o600)
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], check=True)
        print(f"Login startup installed: {path}")
    elif args.command == "credentials-path":
        print(ENV_FILE)


if __name__ == "__main__":
    main()
