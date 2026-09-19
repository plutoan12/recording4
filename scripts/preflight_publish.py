#!/usr/bin/env python3
"""게시 직전 점검. 업로드는 하지 않고, 업로드가 실패할 이유만 먼저 찾습니다.

실제 업로드는 되돌릴 수 없습니다. 올라간 뒤에 "채널이 다르다", "토큰이
만료됐다", "실행 설정이 꺼져 있다"를 알게 되면 계정에 지울 영상이 남습니다.
이 점검은 업로드 직전까지 필요한 것을 모두 확인하고, `videos.insert`는
부르지 않습니다.

    R4_YOUTUBE_CREDENTIALS_FILE=... R4_YOUTUBE_CHANNEL_ID=... \\
      python scripts/preflight_publish.py

확인하는 것:

- 실행 설정(`R4_YOUTUBE_UPLOAD_ENABLED`)이 켜져 있는지
- 인증 파일이 있고, 남이 읽을 수 없고, 갱신 토큰과 필요한 권한을 담고 있는지
- 그 인증으로 채널을 조회할 수 있는지(읽기 호출 1회)
- 조회된 채널이 설정한 채널과 같은지

마지막 두 가지는 네트워크를 씁니다. 읽기 호출이라 영상을 만들지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

# 업로드에 필요한 권한. 하나라도 빠지면 업로드 때 거절당합니다.
NEEDED_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",)


def check_enabled(value: str | None) -> list[str]:
    """실행 설정. 꺼져 있으면 워커가 업로드 직전에 막습니다."""
    if (value or "").strip().lower() in ("1", "true", "yes", "on"):
        return []
    return ["R4_YOUTUBE_UPLOAD_ENABLED이 켜져 있지 않습니다. 켜지 않으면 워커가 업로드를 막습니다."]


def check_credentials_file(path: Path) -> list[str]:
    """인증 파일의 모양만 봅니다. 값은 읽어도 찍지 않습니다."""
    if not path.exists():
        return [f"인증 파일이 없습니다: {path}"]
    problems: list[str] = []
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        problems.append(
            f"인증 파일을 다른 사용자가 읽을 수 있습니다(권한 {mode:o}). chmod 600으로 바꾸세요."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [*problems, f"인증 파일을 읽지 못했습니다: {type(exc).__name__}"]
    if not isinstance(data, dict):
        return [*problems, "인증 파일 형식이 다릅니다. connect_youtube.py가 만든 파일이 맞나요?"]
    # 갱신 토큰이 없으면 처음 한 번만 되고 다음부터 막힙니다.
    if not data.get("refresh_token"):
        problems.append(
            "갱신 토큰이 없습니다. connect_youtube.py로 다시 연결하세요"
            "(access_type=offline, prompt=consent)."
        )
    granted = set(data.get("scopes") or [])
    if not granted:
        # 권한 목록이 없으면 확인할 수 없습니다. 조용히 통과시키면 이 점검을
        # 둔 뜻이 없어집니다. 모르는 것은 모른다고 적습니다.
        problems.append(
            "인증 파일에 권한 목록이 없어 업로드 권한을 확인하지 못했습니다. "
            "채널 조회가 통과해도 업로드에서 거절당할 수 있습니다."
        )
    elif missing := [scope for scope in NEEDED_SCOPES if scope not in granted]:
        problems.append("업로드 권한이 없습니다: " + ", ".join(missing))
    return problems


def check_channel(found: list[dict], expected: str | None) -> list[str]:
    """조회된 채널과 설정한 채널이 같은지 봅니다.

    다르면 승인한 것과 다른 채널에 올라갑니다. 업로드 뒤에는 되돌릴 수
    없으므로 여기서 막습니다.
    """
    if not found:
        return ["이 계정에서 YouTube 채널을 찾지 못했습니다."]
    ids = [item.get("id") for item in found]
    if not expected:
        return ["R4_YOUTUBE_CHANNEL_ID가 비어 있습니다. 찾은 채널: " + ", ".join(map(str, ids))]
    if expected not in ids:
        return [
            f"설정한 채널({expected})이 이 계정의 채널과 다릅니다: {', '.join(map(str, ids))}. "
            "이대로 올리면 승인한 것과 다른 채널에 올라갑니다."
        ]
    return []


def channels(path: Path) -> list[dict]:
    """읽기 호출 한 번으로 채널 목록을 받습니다. 영상은 건드리지 않습니다."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_authorized_user_file(str(path))
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    return service.channels().list(part="id,snippet", mine=True).execute().get("items", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--offline", action="store_true", help="네트워크 확인을 건너뜁니다.")
    args = parser.parse_args()

    credentials = args.credentials or Path(os.environ.get("R4_YOUTUBE_CREDENTIALS_FILE", ""))
    channel = args.channel or os.environ.get("R4_YOUTUBE_CHANNEL_ID")
    if not str(credentials):
        print("인증 파일 경로가 없습니다. --credentials 또는 R4_YOUTUBE_CREDENTIALS_FILE.")
        return 2

    problems = check_enabled(os.environ.get("R4_YOUTUBE_UPLOAD_ENABLED"))
    print(f"인증 파일 {credentials}")
    problems += check_credentials_file(Path(credentials))

    if args.offline:
        print("네트워크 확인은 건너뜁니다(--offline).")
    elif any("인증 파일이 없습니다" in problem for problem in problems):
        print("인증 파일이 없어 채널 확인을 건너뜁니다.")
    else:
        try:
            found = channels(Path(credentials))
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 사람이 읽을 말로 바꿉니다.
            problems.append(
                f"채널 조회에 실패했습니다: {type(exc).__name__}: {exc}. "
                "토큰이 만료됐거나 권한이 빠졌을 수 있습니다."
            )
        else:
            for item in found:
                print(f"  계정 채널: {item.get('snippet', {}).get('title')} / {item.get('id')}")
            problems += check_channel(found, channel)

    if problems:
        print("\n올리기 전에 고칠 것:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n업로드 직전까지 확인했습니다. 이 점검은 영상을 올리지 않았습니다.")
    print("실제 게시는 docs/PUBLISH_RUNBOOK.md의 3단계부터 진행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
