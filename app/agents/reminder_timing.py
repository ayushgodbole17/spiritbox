"""
Reminder timing helpers — compute a safe reminder_time given the event_time
and granularity emitted by the intent detector.

Granularity rules mirror the SYSTEM prompt in app/prompts/detect_intent.py:

  - "time"  → reminder = event - 1h
  - "day"   → reminder = 09:00 local on event date (same day)
  - "week"  → reminder = 09:00 local on the Sunday BEFORE that week
  - "month" → reminder = 09:00 local on the FIRST Sunday of that month

If the LLM emits an invalid / past / nonsensical reminder_time we fall back
to the rule for the given granularity, and as a last resort to
09:00 local on (event_date - 1 day).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo


def _parse(dt_str: str, tz: ZoneInfo) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _nine_am(d: datetime, tz: ZoneInfo) -> datetime:
    return d.astimezone(tz).replace(hour=9, minute=0, second=0, microsecond=0)


def _sunday_before(d: datetime, tz: ZoneInfo) -> datetime:
    """The Sunday strictly before the start of the week containing d."""
    local = d.astimezone(tz)
    # Monday=0 ... Sunday=6. We want the Sunday before the Monday of d's week.
    monday = local - timedelta(days=local.weekday())
    sunday = monday - timedelta(days=1)
    return _nine_am(sunday, tz)


def _first_sunday_of_month(d: datetime, tz: ZoneInfo) -> datetime:
    local = d.astimezone(tz)
    first = local.replace(day=1)
    # weekday(): Mon=0..Sun=6 → days to add to reach Sunday.
    offset = (6 - first.weekday()) % 7
    sunday = first + timedelta(days=offset)
    return _nine_am(sunday, tz)


def compute_reminder_time(
    event_time_str: str,
    proposed_reminder_str: str,
    granularity: str,
    timezone_name: str,
    now: Optional[datetime] = None,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Validate (event_time, reminder_time) from the LLM and compute a safe reminder.

    Returns (event_time, reminder_time) as timezone-aware datetimes, or
    (None, None) if the event is unparseable / already in the past.
    """
    tz = ZoneInfo(timezone_name)
    now = now or datetime.now(tz)

    event_time = _parse(event_time_str, tz)
    if event_time is None:
        return None, None

    if event_time <= now:
        return None, None

    proposed = _parse(proposed_reminder_str, tz)

    gran = (granularity or "time").lower()
    if gran == "time":
        computed = event_time - timedelta(hours=1)
    elif gran == "day":
        computed = _nine_am(event_time, tz)
    elif gran == "week":
        computed = _sunday_before(event_time, tz)
    elif gran == "month":
        computed = _first_sunday_of_month(event_time, tz)
    else:
        computed = event_time - timedelta(hours=1)

    # For "time" / "week" the reminder must fire strictly before the event.
    # For "day" / "month" the event_time is a nominal placeholder, so we only
    # require the reminder to be in the future.
    needs_before_event = gran in ("time", "week")

    def _ok(dt: Optional[datetime]) -> bool:
        if dt is None or dt <= now:
            return False
        if needs_before_event and dt >= event_time:
            return False
        return True

    if _ok(proposed):
        reminder = proposed
    elif _ok(computed):
        reminder = computed
    else:
        # Last resort: 09:00 the day before the event, or 5 minutes from now.
        fallback = _nine_am(event_time - timedelta(days=1), tz)
        if _ok(fallback):
            reminder = fallback
        else:
            reminder = now + timedelta(minutes=5)

    return event_time, reminder
