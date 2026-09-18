"""Disposable process with a hard file-size ceiling and no server credentials."""

import os
import resource
import sys

from pipeline.source_links import youtube_url


def main():
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.youtube import YoutubeIE

    url, target, maximum = sys.argv[1:]
    url = youtube_url(url)
    maximum = int(maximum)
    resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
    # Do not pass worker secrets into downloader subprocesses or optional runtimes.
    for key in list(os.environ):
        if key.startswith(("R4_", "AWS_", "GOOGLE_")):
            del os.environ[key]
    with YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "cachedir": False,
            "js_runtimes": {"node": {}},
            "remote_components": set(),
            "fixup": "never",
            "outtmpl": target,
            "overwrites": True,
            "format": (
                "bestvideo[ext=mp4][vcodec^=avc1][height<=720][protocol=https]"
                "+bestaudio[ext=m4a][protocol=https]/"
                "best[ext=mp4][height<=720][protocol=https]"
            ),
            "merge_output_format": "mp4",
            "max_filesize": maximum,
            "socket_timeout": 20,
            "retries": 1,
            "fragment_retries": 0,
            "geo_bypass": False,
            "match_filter": lambda info, **kwargs: (
                "Live streams are not supported" if info.get("is_live") else None
            ),
        },
        auto_init=False,
    ) as downloader:
        downloader.add_info_extractor(YoutubeIE())
        downloader.extract_info(url, download=True)


if __name__ == "__main__":
    main()
