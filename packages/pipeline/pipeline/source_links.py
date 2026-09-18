"""Only canonical single-video YouTube URLs cross the worker boundary."""

import re
from urllib.parse import parse_qs, urlsplit


def youtube_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or parts.username or parts.password or parts.port:
        raise ValueError("HTTPS YouTube 단일 영상 링크를 입력하세요.")
    host = parts.hostname
    video = None
    if host == "youtu.be":
        video = parts.path.removeprefix("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parts.path == "/watch":
            ids = parse_qs(parts.query).get("v", [])
            video = ids[0] if len(ids) == 1 else None
        elif parts.path.startswith("/shorts/"):
            video = parts.path.removeprefix("/shorts/")
    if not video or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        raise ValueError("YouTube 영상 또는 Shorts 링크만 지원합니다.")
    return f"https://www.youtube.com/watch?v={video}"
