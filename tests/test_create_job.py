"""
Unit tests for app.scheduler.create_job._datetime_to_cron.

Cron lives in UTC on Cloud Scheduler, so a local-tz datetime must be converted
before its hour/minute/day/month fields are rendered.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.scheduler.create_job import _datetime_to_cron


def test_ist_morning_converts_to_utc_pre_dawn():
    # 2026-04-17 09:00 IST == 2026-04-17 03:30 UTC
    dt = datetime(2026, 4, 17, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert _datetime_to_cron(dt) == "30 3 17 4 *"


def test_ist_late_evening_rolls_to_next_utc_day():
    # 2026-04-17 23:30 IST == 2026-04-17 18:00 UTC (still same day)
    dt = datetime(2026, 4, 17, 23, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert _datetime_to_cron(dt) == "0 18 17 4 *"


def test_ist_after_midnight_rolls_back_a_utc_day():
    # 2026-04-18 04:00 IST == 2026-04-17 22:30 UTC
    dt = datetime(2026, 4, 18, 4, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert _datetime_to_cron(dt) == "30 22 17 4 *"


def test_naive_datetime_is_assumed_utc():
    # Naive input must not crash; we treat it as UTC already.
    dt = datetime(2026, 4, 17, 9, 0)
    assert _datetime_to_cron(dt) == "0 9 17 4 *"


def test_utc_datetime_unchanged():
    dt = datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc)
    assert _datetime_to_cron(dt) == "0 9 17 4 *"
