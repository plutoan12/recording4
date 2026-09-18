"""One-time local OAuth login; writes credentials only to a user-selected private file."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="YouTube OAuth 연결 (브라우저 로그인 필요)")
    parser.add_argument("client_secrets", type=Path)
    parser.add_argument("token_file", type=Path)
    args = parser.parse_args()
    if args.token_file.exists():
        parser.error("기존 인증 파일을 덮어쓰지 않습니다. 새 경로를 지정하세요.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ]
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secrets), scopes=scopes)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    channels = service.channels().list(part="id,snippet", mine=True).execute().get("items", [])
    if not channels:
        parser.error("연결 계정에서 YouTube 채널을 찾지 못했습니다.")
    descriptor = os.open(args.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(credentials.to_json())
    for channel in channels:
        print(f"채널: {channel['snippet']['title']} / {channel['id']}")
    print("인증 파일을 서버에 비밀 파일로 전달하고 R4_YOUTUBE_CREDENTIALS_FILE을 설정하세요.")


if __name__ == "__main__":
    main()
