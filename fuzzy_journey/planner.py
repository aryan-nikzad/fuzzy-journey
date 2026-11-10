"""One place that builds a day, so the app and the alarm service always agree."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .database import Database
from .models import Task, TaskStatus
from .prayer_times import PrayerLibrary
from .rhythm import DayKind
from .timeutil import now as clock_now
from .today import TodayView, build_today


def snooze(db: Database) -> timedelta:
    """How long *Ask me later* waits (a setting; half an hour by default)."""
    return timedelta(minutes=db.settings.closing_snooze)


def build_view(
    db: Database, library: PrayerLibrary, now: datetime, *,
    overtime: int | None = None, evening: int | None = None,
) -> TodayView:
    """The day that contains ``now``, with its pomodoro schedule.

    ``overtime`` and ``evening`` preview a different amount of night work, or of optional
    evening work, than the one saved."""
    day = now.date()
    slug = db.settings.location.slug
    tomorrow = library.day(slug, day + timedelta(days=1))
    entry = db.day_entries(day, day).get(day)
    return build_today(
        now,
        entry.kind if entry else DayKind.STEADY,
        prayer_day=library.day(slug, day),
        next_fajr=tomorrow.fajr if tomorrow else None,
        activities=db.list_activities(),
        reminders=db.list_alarms(),
        prayer_alarms=db.prayer_alarms(),
        evening_start=db.settings.evening_start,
        flex=db.settings.flex,
        start=entry.start if entry else None,
        overtime=overtime if overtime is not None else (entry.overtime if entry else 0),
        evening=evening if evening is not None else (entry.evening if entry else 0),
        protect_bedtime=db.settings.protect_bedtime,
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


# --------------------------------------------------------------------------
# What each day really had
# --------------------------------------------------------------------------


def steady_reference(db: Database, library: PrayerLibrary, day: date) -> timedelta:
    """The focus time a plain Steady ``day`` would have offered: the yardstick for "percent"."""
    slug = db.settings.location.slug
    prayers = library.day(slug, day)
    if prayers is None:
        return timedelta(0)
    tomorrow = library.day(slug, day + timedelta(days=1))
    view = build_today(
        datetime.combine(day, time(0, 0)), DayKind.STEADY, prayer_day=prayers,
        next_fajr=tomorrow.fajr if tomorrow else None, activities=db.list_activities(),
        reminders=[], prayer_alarms={}, evening_start=db.settings.evening_start,
        flex=db.settings.flex, pomodoro=db.settings.pomodoro,
    )
    return timedelta(minutes=view.schedule.focus_minutes) if view.schedule else timedelta(0)


def record_progress(db: Database, library: PrayerLibrary, now: datetime) -> None:
    """Remember the focus today's clock has run, and close the books on earlier days.

    Only days that were recorded while the app or the service was running are closed, so a day
    nobody was around for stays empty instead of being invented from today's settings.
    """
    block = db.settings.pomodoro.focus
    for day in db.open_progress_days(before=now.date()):
        view = build_view(db, library, datetime.combine(day, time(23, 59)))
        if view.schedule is not None:
            db.record_progress(day, view.worked, timedelta(minutes=view.schedule.focus_minutes),
                               steady_reference(db, library, day), block, final=True)
    view = build_view(db, library, now)
    if view.schedule is not None:
        db.record_progress(now.date(), view.worked, timedelta(minutes=view.schedule.focus_minutes),
                           steady_reference(db, library, now.date()), block)


# --------------------------------------------------------------------------
# Closing the day
# --------------------------------------------------------------------------


def open_tasks(db: Database, day: date) -> list[Task]:
    """Tasks of ``day`` still waiting for a status (the prayers settle in their own time)."""
    return [t for t in db.tasks_on(day, prayers=False) if t.status is TaskStatus.UNSET]


def closing_due(db: Database, view: TodayView, now: datetime) -> bool:
    """Should the app now ask whether today's tasks were done, moved or cancelled?

    Yes once the day's work is over (planning has begun) and tasks are still open, unless the
    person already closed the day or asked to be asked later. Never after bedtime: the night is
    for sleep, and tomorrow's review picks up whatever is left. Switched off, it never asks by
    itself; with the reminder on it also opens when nothing is open, to remind you to plan tomorrow.
    """
    settings = db.settings
    if not settings.closing_prompt or not view.closing_due:
        return False
    if view.bedtime is not None and now >= view.bedtime:
        return False
    closed, ask_again_at = db.closing_state(view.day)
    if closed or (ask_again_at is not None and now < ask_again_at):
        return False
    return bool(open_tasks(db, view.day)) or settings.closing_reminder
