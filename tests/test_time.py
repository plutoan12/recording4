from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from pipeline.time import as_utc


@pytest.mark.parametrize(
    "value",
    [
        datetime(2030, 1, 1),
        datetime(2030, 1, 1, tzinfo=UTC),
        datetime(2030, 1, 1, 9, tzinfo=timezone(timedelta(hours=9))),
    ],
)
def test_database_time_preserves_instant(value):
    assert as_utc(value) == datetime(2030, 1, 1, tzinfo=UTC)


@pytest.mark.postgres
def test_postgres_seoul_session_time_preserves_instant(session, is_postgres):
    if not is_postgres:
        pytest.skip("PostgreSQL session timezone test")
    session.execute(text("SET TIME ZONE 'Asia/Seoul'"))
    try:
        moment = session.scalar(text("SELECT TIMESTAMPTZ '2030-01-01 00:00:00+00'"))
        assert moment.utcoffset() == timedelta(hours=9)
        assert as_utc(moment) == datetime(2030, 1, 1, tzinfo=UTC)
    finally:
        session.execute(text("SET TIME ZONE 'UTC'"))
