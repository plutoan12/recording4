"""Bounded, one-shot public GitHub collection. Never executes collected files."""

import argparse
import collections
import hashlib
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

KINDS = {
    ".ass": "subtitle",
    ".ssa": "subtitle",
    ".srt": "subtitle",
    ".vtt": "subtitle",
    ".ffx": "preset",
    ".mogrt": "preset",
    ".setting": "preset",
    ".comp": "preset",
    ".drfx": "preset",
    ".jsx": "script",
    ".lua": "script",
    ".moon": "script",
}
ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "Unlicense", "CC0-1.0"}


def fetch(url, limit=8_000_000):
    if urlparse(url).scheme != "https" or urlparse(url).netloc not in {
        "api.github.com",
        "raw.githubusercontent.com",
    }:
        raise ValueError("허용되지 않은 다운로드 주소")
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "response"
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--proto",
                "=https",
                "--max-time",
                "45",
                "--max-filesize",
                str(limit),
                "--user-agent",
                "recording4-catalog/0.1",
                "--output",
                str(target),
                url,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        if target.stat().st_size > limit:
            raise ValueError("응답 크기 제한 초과")
        return target.read_bytes()


def api(path):
    return json.loads(fetch("https://api.github.com/repos/" + path))


def safe_path(value):
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("잘못된 저장소 경로")
    return path


def verify_blob(data, sha):
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != sha:
        raise ValueError("Git blob 해시 불일치")


def store_blob(out, data):
    digest = hashlib.sha256(data).hexdigest()
    path = out / "blobs" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        temp = path.with_suffix(".tmp")
        temp.write_bytes(data)
        temp.replace(path)
    return digest, path.relative_to(out).as_posix()


def write_catalog(out, records, sources, errors):
    report = {
        "records": records,
        "sources": sources,
        "errors": errors,
        "summary": {
            "total": len(records),
            "downloaded": sum(bool(r.get("local")) for r in records),
            "unique_files": len({r["sha256"] for r in records if r.get("sha256")}),
            "kinds": dict(collections.Counter(r["kind"] for r in records)),
        },
    }
    (out / "catalog.json.tmp").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "catalog.json.tmp").replace(out / "catalog.json")
    cards = []
    for r in records:

        def e(key, record=r):
            return html.escape(str(record.get(key, "")), quote=True)

        filename = html.escape(PurePosixPath(r["path"]).name, quote=True)
        link = (
            f'<a href="{e("local")}" download="{filename}">파일 받기</a>'
            if r.get("local")
            else "링크만 수집"
        )
        cards.append(
            f'<article data-kind="{e("kind")}">'
            f'<small>{e("app")} · {e("kind")} · {e("license")}</small>'
            f'<h3>{e("path")}</h3><p>{e("repo")}</p>'
            f'<p>공개 배포: 검토 필요 · 앱 실행: 미검증</p>'
            f'<a href="{e("url")}">원본 보기</a> {link}</article>'
        )
    page = (
        """<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>recording4 자료 라이브러리</title>
<style>body{background:#10141d;
color:#ebedf5;
font:16px system-ui;
margin:40px auto;
max-width:1200px;
padding:0 24px}
h1{font-size:38px}
input,select{padding:14px;
border-radius:10px;
margin:12px 8px 24px 0}
input{width:55%}
main{display:grid;
grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
gap:16px}
article{background:#1c2331;
border:1px solid #303d53;
padding:22px;
border-radius:16px;
overflow-wrap:anywhere}
small{color:#acbada}
a{color:#91bcff;
margin-right:16px}
h3{font-size:17px}
p{color:#acbada;
font-size:13px}[hidden]{display:none}</style>
<h1>자료 라이브러리</h1>
<p>개인용 수집함 · 원본 파일과 제작용 스크립트 · 실행 미리보기 없음</p>
<input id="q" placeholder="이름, 프로그램, 저장소 검색" aria-label="검색">
<select id="kind" aria-label="종류">
<option value="">전체 종류</option>
<option>preset</option>
<option>subtitle</option>
<option>script</option>
</select>
<p id="count">
</p>
<main>"""
        + "".join(cards)
        + """</main>
<script>
const q=document.querySelector('#q'),kind=document.querySelector('#kind');
function filter(){let n=0;
document.querySelectorAll('article').forEach(a=>{a.hidden=!(a.textContent.toLowerCase().includes(q.value.toLowerCase())
  &&(!kind.value||kind.value===a.dataset.kind));
if(!a.hidden)n++});
document.querySelector('#count').textContent=n+'개 자료'}q.oninput=filter;
kind.onchange=filter;
filter();
</script>
</html>"""
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    return report


def collect(config, out, max_files=300, max_bytes=100_000_000, max_file_bytes=5_000_000):
    if min(max_files, max_bytes, max_file_bytes) <= 0:
        raise ValueError("수집 한도는 양수여야 합니다")
    if len(config["sources"]) > 10:
        raise ValueError("한 번에 최대 10개 저장소")
    if (out / "catalog.json").exists():
        raise FileExistsError("기존 수집함을 보존합니다. 새로운 --out 폴더를 지정하세요")
    out.mkdir(parents=True, exist_ok=True)
    records, sources, errors = [], [], []
    used, downloaded = 0, 0
    for source in config["sources"]:
        repo = source["repo"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("잘못된 GitHub 저장소 이름")
        try:
            info = api(repo)
            commit = api(repo + "/commits/" + quote(info["default_branch"], safe=""))["sha"]
            if not re.fullmatch(r"[a-f0-9]{40}", commit):
                raise ValueError("잘못된 커밋")
            tree = api(repo + "/git/trees/" + commit + "?recursive=1")
            if tree.get("truncated"):
                raise ValueError("파일 목록이 잘렸습니다. 저장소를 더 작게 나누세요")
            license_id = (info.get("license") or {}).get("spdx_id", "UNKNOWN")
            evidence = []
            for entry in tree["tree"]:
                if entry["type"] != "blob" or entry.get("mode") == "120000":
                    continue
                path = safe_path(entry["path"])
                if path.name.lower() in {
                    "license",
                    "license.txt",
                    "license.md",
                    "copying",
                    "notice",
                    "notice.txt",
                }:
                    data = fetch(
                        f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(str(path))}",
                        500_000,
                    )
                    verify_blob(data, entry["sha"])
                    digest, local = store_blob(out, data)
                    evidence.append({"path": str(path), "local": local, "sha256": digest})
            sources.append(
                {"repo": repo, "commit": commit, "license": license_id, "license_files": evidence}
            )
            # Root license detection is evidence, not automatic permission to republish assets.
            can_download = (
                license_id in ALLOWED_LICENSES and bool(evidence) and source.get("download", False)
            )
            for entry in tree["tree"]:
                if entry["type"] != "blob" or entry.get("mode") == "120000":
                    continue
                path = safe_path(entry["path"])
                kind = KINDS.get(path.suffix.lower())
                if not kind:
                    continue
                row = {
                    "repo": repo,
                    "path": str(path),
                    "commit": commit,
                    "git_sha": entry["sha"],
                    "app": source["app"],
                    "kind": kind,
                    "license": license_id,
                    "distribution": "review_required",
                    "validation": "not_tested",
                    "url": f"https://github.com/{repo}/blob/{commit}/{quote(str(path))}",
                    "status": "metadata_only",
                }
                records.append(row)
                size = entry.get("size", max_file_bytes + 1)
                if not can_download:
                    continue
                if downloaded >= max_files or size > max_file_bytes or used + size > max_bytes:
                    row["status"] = "limit_skipped"
                    continue
                try:
                    data = fetch(
                        f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(str(path))}",
                        min(max_file_bytes, max_bytes - used),
                    )
                    verify_blob(data, entry["sha"])
                    row["sha256"], row["local"] = store_blob(out, data)
                    row["status"] = "downloaded"
                    downloaded += 1
                    used += len(data)
                except (RuntimeError, ValueError, OSError) as exc:
                    row["status"] = "error"
                    errors.append({"repo": repo, "path": str(path), "error": str(exc)})
            write_catalog(out, records, sources, errors)
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            errors.append({"repo": repo, "error": str(exc)})
    return write_catalog(out, records, sources, errors)


def main():
    parser = argparse.ArgumentParser(description="공개 GitHub 개인용 자료 수집기")
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=300)
    parser.add_argument("--max-mb", type=int, default=100)
    args = parser.parse_args()
    report = collect(
        json.loads(args.sources.read_text()), args.out, args.max_files, args.max_mb * 1_000_000
    )
    print(
        json.dumps(
            {"summary": report["summary"], "errors": report["errors"]}, ensure_ascii=False, indent=2
        )
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
