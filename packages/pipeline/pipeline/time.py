"""UTC normalization for SQLite naive and PostgreSQL aware timestamps."""

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
