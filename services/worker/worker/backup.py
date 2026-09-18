"""Copy objects to a separate host backup directory, without deleting old data."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from adminapi.models import utcnow
from adminapi.storage import get_storage


def snapshot(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    dumps = sorted(root.parent.glob("*.dump"), key=lambda p: p.stat().st_mtime)
    database = dumps[-1].name if dumps else None
    storage = get_storage()
    entries = []
    for page in storage._client.get_paginator("list_objects_v2").paginate(Bucket=storage._bucket):
        for item in page.get("Contents", []):
            key, etag = item["Key"], item["ETag"]
            digest = hashlib.sha256((key + "\0" + etag).encode()).hexdigest()
            target = root / "objects" / digest
            target.parent.mkdir(exist_ok=True, mode=0o700)
            if not target.exists():
                fd, temporary = tempfile.mkstemp(dir=target.parent)
                os.close(fd)
                try:
                    storage.download_file(key, Path(temporary))
                    if Path(temporary).stat().st_size != item["Size"]:
                        raise ValueError("Object backup size mismatch")
                    Path(temporary).replace(target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            with target.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            entries.append(
                {
                    "key": key,
                    "etag": etag,
                    "size": item["Size"],
                    "sha256": checksum,
                    "file": f"objects/{digest}",
                }
            )
    report = {
        "created_at": utcnow().isoformat(),
        "bucket": storage._bucket,
        "database_dump": database,
        "objects": entries,
    }
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = root / f"media-{stamp}.json"
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(report))
    temporary.chmod(0o600)
    temporary.replace(path)
    return {"manifest": path.name, "count": len(entries)}
