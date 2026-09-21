import hashlib
import json

import pytest

from pipeline import asset_catalog as catalog


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def fixture_api(monkeypatch, license_id="MIT", data=b"template"):
    license_data = b"MIT license fixture"
    entries = [
        {
            "type": "blob",
            "mode": "100644",
            "path": "LICENSE",
            "sha": blob(license_data),
            "size": len(license_data),
        }
    ]
    entries += [
        {"type": "blob", "mode": "100644", "path": p, "sha": blob(data), "size": len(data)}
        for p in ["one.ass", "two.ass"]
    ]
    entries.append({"type": "blob", "mode": "120000", "path": "symlink.ass", "sha": "bad"})

    def api(path):
        if "/commits/" in path:
            return {"sha": "a" * 40}
        if "/git/trees/" in path:
            return {"tree": entries}
        return {"default_branch": "main", "license": {"spdx_id": license_id}}

    monkeypatch.setattr(catalog, "api", api)
    requests = []

    def fetch(url, limit):
        requests.append(url)
        return license_data if url.endswith("/LICENSE") else data

    monkeypatch.setattr(catalog, "fetch", fetch)
    return requests


def config():
    return {"sources": [{"repo": "owner/repo", "app": "Aegisub", "download": True}]}


def test_collect_dedup_and_provenance(monkeypatch, tmp_path):
    fixture_api(monkeypatch)
    report = catalog.collect(config(), tmp_path)
    assert report["summary"] == {
        "total": 2,
        "downloaded": 2,
        "unique_files": 1,
        "kinds": {"subtitle": 2},
    }
    assert report["records"][0]["distribution"] == "review_required"
    assert report["sources"][0]["license_files"]
    assert json.loads((tmp_path / "catalog.json").read_text()) == report


def test_unknown_license_does_not_download(monkeypatch, tmp_path):
    requests = fixture_api(monkeypatch, "UNKNOWN")
    report = catalog.collect(config(), tmp_path)
    assert report["summary"]["downloaded"] == 0
    assert len(requests) == 1  # license evidence only


def test_file_and_byte_limits(monkeypatch, tmp_path):
    fixture_api(monkeypatch)
    report = catalog.collect(config(), tmp_path, max_files=1)
    assert report["summary"]["downloaded"] == 1
    report = catalog.collect(config(), tmp_path / "second", max_bytes=1)
    assert report["summary"]["downloaded"] == 0


@pytest.mark.parametrize("path", ["../bad.ass", "/tmp/x", "dir/../../x", "a\\b", "a\nb"])
def test_reject_unsafe_paths(path):
    with pytest.raises(ValueError):
        catalog.safe_path(path)


def test_corruption_rejected():
    with pytest.raises(ValueError, match="해시"):
        catalog.verify_blob(b"changed", blob(b"original"))


def test_html_escapes_remote_text(tmp_path):
    row = {
        "path": "<script>alert(1)</script>.ass",
        "repo": "owner/repo",
        "app": "<img onerror=bad>",
        "kind": "subtitle",
        "url": "https://github.com/owner/repo",
    }
    catalog.write_catalog(tmp_path, [row], [], [])
    page = (tmp_path / "index.html").read_text()
    assert "<img onerror" not in page
    assert "&lt;script&gt;alert" in page


def test_partial_source_failure_is_recorded(monkeypatch, tmp_path):
    def fail(_):
        raise RuntimeError("HTTP 403")

    monkeypatch.setattr(catalog, "api", fail)
    report = catalog.collect(config(), tmp_path)
    assert report["errors"][0]["error"] == "HTTP 403"
    assert report["summary"]["downloaded"] == 0


def test_existing_catalog_is_preserved(monkeypatch, tmp_path):
    fixture_api(monkeypatch)
    catalog.collect(config(), tmp_path)
    before = (tmp_path / "catalog.json").read_bytes()
    with pytest.raises(FileExistsError):
        catalog.collect(config(), tmp_path)
    assert (tmp_path / "catalog.json").read_bytes() == before
