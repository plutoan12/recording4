#!/usr/bin/env python3
"""자막 템플릿 글꼴을 받아 설치합니다. 워커 이미지 빌드와 로컬 미리보기에 씁니다.

목록·출처·체크섬은 `pipeline.subtitle_fonts`에 있습니다. 출처는 커밋 해시로
고정되어 있고, 받은 파일의 SHA-256이 목록과 다르면 설치하지 않고 실패합니다.
이미 같은 체크섬의 파일이 있으면 다시 받지 않습니다.

    python scripts/fetch_fonts.py --out /usr/share/fonts/truetype/r4
    python scripts/fetch_fonts.py --out .fonts        # 로컬. R4_FONTS_DIR로 씁니다.

`fc-scan`이 있으면 파일 안의 family 이름이 템플릿이 쓰는 이름과 같은지도 확인합니다.
이름이 다르면 libass가 다른 글꼴로 대체해 모양이 조용히 달라지므로 실패로 봅니다.

WOFF 출처(눈누 저장소)는 fontTools로 TTF/OTF로 바꿔 설치합니다(`pip install -e ".[fonts]"`).
체크섬은 내려받은 WOFF 원본으로 확인하고, 변환한 파일 옆에 `.source-sha256`을 남겨
다음 실행에서 다시 받지 않게 합니다.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from pipeline.subtitle_fonts import FONT_SOURCES, FontSource


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "recording4-fetch-fonts"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 고정 https 출처
        return response.read()


def families_in(path: Path) -> list[str] | None:
    """fc-scan이 알려 주는 family 이름들. fc-scan이 없으면 None(확인 생략)."""
    binary = shutil.which("fc-scan")
    if not binary:
        return None
    completed = subprocess.run(
        [binary, "--format", "%{family}\n", str(path)], capture_output=True, text=True
    )
    if completed.returncode:
        return None
    names: list[str] = []
    for line in completed.stdout.splitlines():
        names.extend(part.strip() for part in line.split(",") if part.strip())
    return names


def convert_woff(data: bytes, family: str = "", style: str = "Regular") -> bytes:
    """WOFF를 같은 글꼴의 TTF/OTF 바이트로 바꿉니다. fontTools가 필요합니다.

    name 테이블에 family 이름이 없으면(잘난체·지마켓 산스) `family`·`style`로 채웁니다.
    libass는 이름 없는 글꼴을 등록하지 못하고 조용히 다른 글꼴로 바꾸기 때문입니다.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        raise RuntimeError(
            "WOFF 글꼴을 바꾸려면 fontTools가 필요합니다: pip install -e '.[fonts]'"
        ) from None
    import io

    font = TTFont(io.BytesIO(data))
    font.flavor = None
    if family and not any(r.nameID == 1 for r in font["name"].names):
        full = f"{family} {style}".strip()
        postscript = full.replace(" ", "-")
        for name_id, value in ((1, family), (2, style), (3, full), (4, full), (6, postscript)):
            font["name"].setName(value, name_id, 3, 1, 0x409)
            font["name"].setName(value, name_id, 1, 0, 0)
    buffer = io.BytesIO()
    font.save(buffer)
    return buffer.getvalue()


def _installed_source_hash(target: Path) -> str | None:
    """설치된 파일이 어떤 원본에서 왔는지. 변환한 글꼴은 옆 파일에, 아니면 파일 자체로 압니다."""
    marker = target.with_name(target.name + ".source-sha256")
    if marker.is_file():
        return marker.read_text(encoding="utf-8").strip()
    return sha256_of(target) if target.is_file() else None


def fetch(source: FontSource, out: Path, *, timeout: float) -> str:
    """글꼴 하나를 받아 설치합니다. 결과 설명 한 줄을 돌려줍니다."""
    target = out / source.filename
    if target.is_file() and _installed_source_hash(target) == source.sha256:
        _check_family(source, target)
        return f"{source.family:<20} {source.filename:<28} 이미 있음"
    data = download(source.url, timeout)
    actual = hashlib.sha256(data).hexdigest()
    if actual != source.sha256:
        raise RuntimeError(
            f"{source.filename}: 체크섬이 다릅니다. 기대 {source.sha256[:12]}…, 실제 {actual[:12]}…"
        )
    installed = convert_woff(data, source.family, source.style) if source.needs_conversion else data
    # 이름 확인이 끝나기 전에는 제자리에 두지 않습니다. 실패한 파일이 남아 다음
    # 실행에서 "이미 있음"으로 통과하면 안 됩니다. 임시 파일도 **같은 파일 이름**을
    # 씁니다. name 테이블이 빈 글꼴(잘난체·지마켓 산스 OTF)은 fontconfig가 파일
    # 이름으로 family를 정하므로 `.part`를 붙이면 이름이 달라져 검사가 틀립니다.
    with tempfile.TemporaryDirectory(dir=out, prefix=".fetch-") as staging:
        partial = Path(staging) / target.name
        partial.write_bytes(installed)
        _check_family(source, partial)
        partial.replace(target)
    if source.needs_conversion:
        target.with_name(target.name + ".source-sha256").write_text(actual, encoding="utf-8")
    note = " (WOFF→변환)" if source.needs_conversion else ""
    return f"{source.family:<20} {source.filename:<28} {len(data) / 1024 / 1024:.1f}MB 받음{note}"


def _check_family(source: FontSource, path: Path) -> None:
    names = families_in(path)
    if names is not None and source.family not in names:
        raise RuntimeError(
            f"{source.filename}: 파일의 family 이름 {names}에 "
            f"템플릿 이름 {source.family!r}이 없습니다."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="자막 템플릿 글꼴 내려받기")
    parser.add_argument("--out", type=Path, required=True, help="설치할 디렉터리")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--only", nargs="*", help="family 이름 일부만 받습니다(비우면 전부).")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    chosen = [s for s in FONT_SOURCES if not args.only or s.family in args.only]
    if args.only and len(chosen) != len(args.only):
        known = ", ".join(s.family for s in FONT_SOURCES)
        print(f"오류: 모르는 글꼴 이름이 있습니다. 쓸 수 있는 것: {known}", file=sys.stderr)
        return 2
    failed = 0
    for source in chosen:
        try:
            print(fetch(source, args.out, timeout=args.timeout))
        except Exception as exc:  # noqa: BLE001 - 하나가 실패해도 나머지는 계속 받습니다.
            failed += 1
            print(f"실패: {exc}", file=sys.stderr)
    print(f"{len(chosen) - failed}/{len(chosen)}개 준비됨: {args.out}")
    if not failed and shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", str(args.out)], check=False)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
