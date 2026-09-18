"""Recurring health and failure checks; stores local alerts without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx
from redis import Redis
from sqlalchemy import func, select, text

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Job, OutboxMessage, Publication, utcnow
from adminapi.outbox import enqueue
from adminapi.services.budget import expire_stale
from adminapi.storage import get_storage
from pipeline.states import JobState, PublicationState
from worker.celery_app import celery_app


def recover_expired(session):
    recovered = 0
    for model, states, topic, field in [
        (Job, [JobState.PROCESSING], "job.step", "job_id"),
        (
            Publication,
            [
                PublicationState.PENDING,
                PublicationState.UPLOADING,
                PublicationState.PROCESSING_ON_YOUTUBE,
                PublicationState.SCHEDULED,
            ],
            "publication.run",
            "publication_id",
        ),
    ]:
        for row in session.scalars(
            select(model)
            .where(model.state.in_(states), model.lease_until < utcnow())
            .with_for_update(skip_locked=True)
        ):
            enqueue(
                session,
                topic=topic,
                payload={field: str(row.id)},
                dedupe_key=f"recover:{topic}:{row.id}:{row.lease_token}",
            )
            recovered += 1
    return recovered


def check():
    result = {"checked_at": utcnow().isoformat(), "checks": {}, "attention": {}}
    settings = get_settings()
    for name, action in {
        "redis": lambda: Redis.from_url(settings.redis_url).ping(),
        "storage": lambda: get_storage()._client.head_bucket(Bucket=settings.s3_bucket),
        "worker": lambda: celery_app.control.inspect(timeout=5).ping(),
    }.items():
        try:
            result["checks"][name] = bool(action())
        except Exception as exc:
            result["checks"][name] = False
            result["attention"][name] = type(exc).__name__
    try:
        with get_session_factory()() as session:
            session.execute(text("select 1"))
            result["checks"]["database"] = True
            result["attention"]["expired_budget_holds"] = len(expire_stale(session))
            result["recovery_requests"] = recover_expired(session)
            session.commit()
            for name, model, condition in [
                ("jobs_blocked_or_failed", Job, Job.state.in_([JobState.BLOCKED, JobState.FAILED])),
                ("publications_failed", Publication, Publication.state == PublicationState.FAILED),
                ("outbox_send_errors", OutboxMessage, OutboxMessage.last_error.is_not(None)),
                (
                    "expired_jobs",
                    Job,
                    (Job.state == JobState.PROCESSING) & (Job.lease_until < utcnow()),
                ),
            ]:
                result["attention"][name] = session.scalar(
                    select(func.count()).select_from(model).where(condition)
                )
    except Exception as exc:
        result["checks"]["database"] = False
        result["attention"]["database"] = type(exc).__name__
    result["healthy"] = all(result["checks"].values())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    last = None
    next_backup = 0
    backed_up_dump = None
    while True:
        report = check()
        dumps = sorted(Path("/backups").glob("*.dump"), key=lambda p: p.stat().st_mtime)
        latest_dump = dumps[-1].name if dumps else None
        report["attention"]["database_backup_stale"] = (
            not dumps or time.time() - dumps[-1].stat().st_mtime > 93600
        )
        if (
            not args.once
            and latest_dump
            and latest_dump != backed_up_dump
            and time.monotonic() >= next_backup
        ):
            from worker.backup import snapshot

            try:
                report["media_backup"] = snapshot(Path("/backups/media"))
                backed_up_dump = latest_dump
                next_backup = 0
            except Exception as exc:
                report["attention"]["media_backup"] = type(exc).__name__
                next_backup = time.monotonic() + 300
        destination = Path("/var/recording4/status.json")
        if destination.parent.exists():
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False))
            temporary.replace(destination)
        fingerprint = json.dumps([report["checks"], report["attention"]], sort_keys=True)
        if args.once or fingerprint != last:
            print(json.dumps(report), flush=True)
            webhook = os.environ.get("R4_ALERT_WEBHOOK_URL")
            if webhook and not args.once:
                try:
                    httpx.post(webhook, json=report, timeout=10).raise_for_status()
                except Exception:
                    print("Alert delivery failed; local report retained.", flush=True)
            last = fingerprint
        if args.once:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
