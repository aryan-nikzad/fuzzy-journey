"""Regular self-tests: a zero-length task that asks you to say your plan from memory.

The person chooses when they appear: at each prayer time, or every few hours from waking until bed.
Like the prayers they are only a record for yourself. They never count as focus time, are never
carried over, and an old one that was not ticked never nags in a review.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta

MODE_OFF = "off"
MODE_PRAYERS = "prayers"
MODE_INTERVAL = "interval"
MODES = (MODE_OFF, MODE_PRAYERS, MODE_INTERVAL)

HOURS_RANGE = (1, 12)
DEFAULT_HOURS = 4

#: The prayers a self-test can follow, in order.
PRAYER_NAMES = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")

PREFIX = "Test myself"


def title_for(moment: datetime) -> str:
    return f"{PREFIX} · {moment:%H:%M}"


def times_for(
    mode: str, hours: int, day: date, prayer_times: Mapping[str, time],
    wake: datetime | None, bedtime: datetime | None,
) -> list[datetime]:
    """When ``day``'s self-tests fall, in order. Nothing when they are off or the day is unknown."""
    if mode == MODE_PRAYERS:
        return sorted(datetime.combine(day, prayer_times[name]) for name in PRAYER_NAMES if name in prayer_times)
    if mode == MODE_INTERVAL and wake and bedtime:
        step = timedelta(hours=min(max(hours, HOURS_RANGE[0]), HOURS_RANGE[1]))
        out, moment = [], wake.replace(second=0, microsecond=0)
        while moment < bedtime:
            out.append(moment)
            moment += step
        return out
    return []


def latest_due(times: list[datetime], now: datetime) -> datetime | None:
    """The most recent self-test time that has come. Earlier ones nobody was there for are skipped."""
    passed = [t for t in times if t <= now]
    return passed[-1] if passed else None
