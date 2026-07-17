"""UTC-safe formatting for clinical timestamps.

Timestamps are stored as timestamptz; drivers may return them in the
connection's local timezone. Every user-facing date must be normalized to UTC
before truncation, or dates near midnight shift by a day.
"""

from datetime import UTC, datetime


def utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def utc_date(dt: datetime | None) -> str | None:
    iso = utc_iso(dt)
    return iso[:10] if iso else None
