"""Small, dependency-free helpers for clock times, durations and weekdays."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ALL_DAYS = 0b1111111
WEEKDAYS_ONLY = 0b0011111
WEEKENDS_ONLY = 0b1100000


def day_bit(day: date) -> int:
    """Bit for a date's weekday (Monday = bit 0)."""
    return 1 << day.weekday()


def mask_includes(mask: int, day: date) -> bool:
    return bool(int(mask or 0) & day_bit(day))


def mask_label(mask: int) -> str:
    mask = int(mask or 0) & ALL_DAYS
    if mask == ALL_DAYS:
        return "Every day"
    if mask == WEEKDAYS_ONLY:
        return "Weekdays"
    if mask == WEEKENDS_ONLY:
        return "Weekends"
    if mask == 0:
        return "Never"
    return " · ".join(name for i, name in enumerate(WEEKDAY_NAMES) if mask & (1 << i))


def parse_clock(value: str) -> time:
    """Parse ``HH:MM`` or ``HH:MM:SS``. Raises ValueError on anything else."""
    text = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"expected a 24-hour time like 07:30, got {value!r}")


def clock_str(value: time | datetime) -> str:
    return value.strftime("%H:%M")


def parse_hhmm_duration(value: str) -> timedelta:
    """Parse a ``HH:MM`` duration (hours may exceed 23)."""
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {value!r}")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"expected integer hours and minutes, got {value!r}") from exc
    if hours < 0 or not 0 <= minutes < 60:
        raise ValueError(f"minutes must be 00-59 and hours non-negative, got {value!r}")
    return timedelta(hours=hours, minutes=minutes)


def duration_hhmm(value: timedelta) -> str:
    total = max(0, int(value.total_seconds() // 60))
    hours, minutes = divmod(total, 60)
    return f"{hours:02d}:{minutes:02d}"


def human_duration(value: timedelta) -> str:
    """``3h 12m``, ``45m``, ``2h``. Never negative."""
    total = max(0, int(value.total_seconds() // 60))
    hours, minutes = divmod(total, 60)
    if hours and minutes:
        return f"{hours}h {minutes:02d}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def countdown(value: timedelta) -> str:
    """Like :func:`human_duration` but spells out days for long waits."""
    total = max(0, int(value.total_seconds() // 60))
    days, rest = divmod(total, 1440)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    return human_duration(timedelta(minutes=total))


def span_after(day: date, start: time, end: time) -> tuple[datetime, datetime]:
    """Start/end datetimes for a daily block; an end at or before the start wraps past midnight."""
    begin = datetime.combine(day, start)
    finish = datetime.combine(day, end)
    if finish <= begin:
        finish += timedelta(days=1)
    return begin, finish


def now() -> datetime:
    """Local wall-clock time, timezone-naive (what the user sees on their clock).

    ``FUZZY_JOURNEY_NOW=2026-11-02T09:30`` pins the clock for screenshots and demos.
    """
    pinned = os.environ.get("FUZZY_JOURNEY_NOW")
    if pinned:
        try:
            return datetime.fromisoformat(pinned)
        except ValueError:
            pass
    return datetime.now()
