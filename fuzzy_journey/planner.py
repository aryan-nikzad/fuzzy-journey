"""One place that builds a day, so the app and the alarm service always agree."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .database import Database
from .prayer_times import PrayerLibrary
from .timeutil import now as clock_now
from .today import TodayView, build_today


def build_view(db: Database, library: PrayerLibrary, now: datetime) -> TodayView:
    """The day that contains ``now``, with its pomodoro schedule."""
    day = now.date()
    slug = db.settings.location.slug
    tomorrow = library.day(slug, day + timedelta(days=1))
    return build_today(
        now,
        db.day_kind(day),
        prayer_day=library.day(slug, day),
        next_fajr=tomorrow.fajr if tomorrow else None,
        activities=db.list_activities(),
        reminders=db.list_alarms(),
        prayer_alarms=db.prayer_alarms(),
        evening_start=db.settings.evening_start,
        flex=db.settings.flex,
        pomodoro=db.settings.pomodoro,
        pomodoro_sound=db.settings.pomodoro_sound,
        pomodoro_pauses=db.pomodoro_pauses(day),
    )


def view_for_day(db: Database, library: PrayerLibrary, day: date) -> TodayView:
    """Any day: now for today, the start of the day for the future, its end for the past."""
    today = clock_now().date()
    if day == today:
        now = clock_now()
    elif day > today:
        now = datetime.combine(day, time(0, 0))
    else:
        now = datetime.combine(day, time(23, 59))
    return build_view(db, library, now)
