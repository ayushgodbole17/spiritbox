"""
Unit tests for app.agents.reminder_timing.compute_reminder_time.

Each test pins a fake `now` so the week/month arithmetic is deterministic.
No LLM calls — just the post-validator logic.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.agents.reminder_timing import compute_reminder_time


TZ_NAME = "Asia/Kolkata"
TZ = ZoneInfo(TZ_NAME)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_granularity_time_subtracts_one_hour():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 4, 17, 19, 0, tzinfo=TZ)  # tomorrow at 7pm

    ev, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str=_iso(event - timedelta(hours=1)),
        granularity="time",
        timezone_name=TZ_NAME,
        now=now,
    )

    assert ev == event
    assert rem == event - timedelta(hours=1)


def test_granularity_day_uses_9am_local_same_day():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 4, 17, 9, 0, tzinfo=TZ)  # tomorrow

    _, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str="",
        granularity="day",
        timezone_name=TZ_NAME,
        now=now,
    )

    assert rem == datetime(2026, 4, 17, 9, 0, tzinfo=TZ)


def test_granularity_week_uses_sunday_before():
    # Monday 2026-04-20 is the start of "next week" relative to Thu 2026-04-16.
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 4, 20, 9, 0, tzinfo=TZ)  # Mon next week

    _, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str="",
        granularity="week",
        timezone_name=TZ_NAME,
        now=now,
    )

    assert rem == datetime(2026, 4, 19, 9, 0, tzinfo=TZ)  # Sunday before


def test_granularity_month_uses_first_sunday():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 5, 1, 9, 0, tzinfo=TZ)  # bare "in May"

    _, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str="",
        granularity="month",
        timezone_name=TZ_NAME,
        now=now,
    )

    # First Sunday of May 2026 is May 3rd.
    assert rem == datetime(2026, 5, 3, 9, 0, tzinfo=TZ)


def test_event_in_past_returns_none():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 4, 15, 9, 0, tzinfo=TZ)

    ev, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str="",
        granularity="time",
        timezone_name=TZ_NAME,
        now=now,
    )

    assert ev is None and rem is None


def test_llm_proposed_reminder_in_past_is_rejected():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 4, 17, 19, 0, tzinfo=TZ)
    bad_proposal = datetime(2020, 1, 1, 9, 0, tzinfo=TZ)

    _, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str=_iso(bad_proposal),
        granularity="time",
        timezone_name=TZ_NAME,
        now=now,
    )

    # Should have fallen back to granularity rule: event - 1h
    assert rem == event - timedelta(hours=1)


def test_unparseable_event_time_returns_none():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)

    ev, rem = compute_reminder_time(
        event_time_str="not-a-date",
        proposed_reminder_str="",
        granularity="time",
        timezone_name=TZ_NAME,
        now=now,
    )

    assert ev is None and rem is None


def test_unknown_granularity_defaults_to_time_rule():
    now = datetime(2026, 4, 16, 10, 0, tzinfo=TZ)
    event = datetime(2026, 4, 17, 19, 0, tzinfo=TZ)

    _, rem = compute_reminder_time(
        event_time_str=_iso(event),
        proposed_reminder_str="",
        granularity="nonsense",
        timezone_name=TZ_NAME,
        now=now,
    )

    assert rem == event - timedelta(hours=1)
