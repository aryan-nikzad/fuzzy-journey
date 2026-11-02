"""When should something ring?

Pure scheduling rules plus the database "claim" that guarantees each alarm
rings once. No GTK, no audio here; the alarm service imports this module.

Guarantees (also listed in AGENTS.md):

* An alarm is *claimed* in a transaction before it is delivered, so a restart
  or two processes can never ring it twice.
* There is a five-minute catch-up window: an alarm slightly late (the service
  restarted, the laptop just woke) still rings; anything older is missed.
* A one-time alarm is disabled the moment it is claimed.
* Times are the computer's local wall-clock time.
* Nothing here touches the network.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .database import Database
from .models import Activity, Alarm, PrayerAlarm, Sound
from .prayer_times import PrayerDay
from .rhythm import DayKind, collect_pauses, finish_with_pauses
from .timeutil import mask_includes, span_after

#: How late an alarm may still ring. Keep in sync with README and tests.
GRACE = timedelta(minutes=5)


@dataclass(frozen=True)
class Ring:
    """Something that is due right now."""

    key: str
    title: str
    due: datetime
    sound: Sound

    @property
    def message(self) -> str:
        return f"It's {self.due.strftime('%H:%M')}."


@dataclass(frozen=True)
class ScheduledEvent:
    """A prayer or activity alarm resolved to a concrete moment."""

    key: str
    title: str
    due: datetime
    sound: Sound
    day: date  # the day it belongs to; (key, day) is unique per delivery
    source: str  # "Prayer" or "Schedule"


# --------------------------------------------------------------------------
# Reminders
# --------------------------------------------------------------------------


def repeats_on(alarm: Alarm, day: date) -> bool:
    if alarm.one_shot_date:
        return alarm.one_shot_date == day.isoformat()
    return mask_includes(alarm.days_mask, day)


def should_fire(alarm: Alarm, now: datetime) -> bool:
    if not alarm.enabled:
        return False
    if alarm.last_fired_date == now.date().isoformat():
        return False
    if not repeats_on(alarm, now.date()):
        return False
    scheduled = datetime.combine(now.date(), alarm.clock)
    return timedelta(0) <= now - scheduled <= GRACE


def next_occurrence(alarm: Alarm, now: datetime) -> datetime | None:
    """The next moment this reminder will ring, or None (disabled, or a one-time date in the past)."""
    if not alarm.enabled:
        return None
    clock = alarm.clock
    for offset in range(0, 370):
        day = now.date() + timedelta(days=offset)
        if not repeats_on(alarm, day):
            continue
        candidate = datetime.combine(day, clock)
        if candidate >= now:
            return candidate
        if alarm.one_shot_date:
            return None
    return None


def claim_due_reminders(db: Database, now: datetime) -> list[Ring]:
    """Atomically claim every reminder that is due. Returns what should ring."""
    claimed: list[Ring] = []
    today = now.date().isoformat()
    with db.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE alarms SET enabled=0, updated_at=? "
            "WHERE enabled=1 AND one_shot_date IS NOT NULL AND one_shot_date < ?",
            (now.isoformat(timespec="seconds"), today),
        )
    # Read after expiring, then claim each candidate inside its own immediate transaction.
    for alarm in db.list_alarms():
        if not should_fire(alarm, now):
            continue
        with db.transaction(immediate=True) as conn:
            updated = conn.execute(
                """UPDATE alarms
                   SET last_fired_date=?,
                       enabled=CASE WHEN one_shot_date IS NOT NULL THEN 0 ELSE enabled END,
                       updated_at=?
                   WHERE id=? AND enabled=1 AND (last_fired_date IS NULL OR last_fired_date<>?)""",
                (today, now.isoformat(timespec="seconds"), alarm.id, today),
            )
            if updated.rowcount != 1:
                continue
            conn.execute(
                "INSERT INTO alarm_events(alarm_id, title, fired_at) VALUES (?, ?, ?)",
                (alarm.id, alarm.title, now.isoformat(timespec="seconds")),
            )
        claimed.append(
            Ring(f"alarm:{alarm.id}", alarm.title, datetime.combine(now.date(), alarm.clock), alarm.sound)
        )
    return claimed


# --------------------------------------------------------------------------
# Prayer and activity alarms
# --------------------------------------------------------------------------


def scheduled_events(
    today: date,
    *,
    prayer_day: PrayerDay | None,
    prayer_alarms: Mapping[str, PrayerAlarm],
    activities: Iterable[Activity],
    kinds: Mapping[date, DayKind],
) -> list[ScheduledEvent]:
    """Every prayer and activity alarm that can fall on ``today``.

    Activities that started yesterday are considered too, because a block that
    crosses midnight ends today. On a Rest day, work activities stay silent.
    """
    events: list[ScheduledEvent] = []
    activities = list(activities)

    if prayer_day:
        for name, setting in prayer_alarms.items():
            moment = prayer_day.at(name)
            if not setting.enabled or moment is None:
                continue
            events.append(
                ScheduledEvent(
                    key=f"prayer:{name}",
                    title=f"{name} prayer",
                    due=moment + timedelta(minutes=setting.offset_minutes),
                    sound=setting.sound,
                    day=today,
                    source="Prayer",
                )
            )

    for activity in activities:
        if not activity.enabled:
            continue
        for offset in (-1, 0):
            start_day = today + timedelta(days=offset)
            if not mask_includes(activity.days_mask, start_day):
                continue
            if activity.is_work and kinds.get(start_day, DayKind.STEADY) is DayKind.REST:
                continue
            start, base_end = span_after(start_day, activity.start_clock, activity.end_clock)
            if offset == 0 and activity.alarm_at_start:
                events.append(
                    ScheduledEvent(
                        f"routine:{activity.id}", activity.title, start,
                        activity.sound, start_day, "Schedule",
                    )
                )
            if activity.alarm_at_end:
                end = (
                    finish_with_pauses(start, base_end - start, collect_pauses(activities, start_day))
                    if activity.is_work
                    else base_end
                )
                if end.date() > today or end < datetime.combine(today, time()) - GRACE:
                    continue  # belongs to another day (tomorrow's run handles it)
                events.append(
                    ScheduledEvent(
                        f"routine:{activity.id}:end", f"{activity.title} finished", end,
                        activity.sound, start_day, "Schedule",
                    )
                )
    return sorted(events, key=lambda e: e.due)


def claim_due_events(db: Database, events: Iterable[ScheduledEvent], now: datetime) -> list[Ring]:
    """Claim each due event once per (event, day). Duplicate claims are ignored."""
    claimed: list[Ring] = []
    for event in events:
        if not timedelta(0) <= now - event.due <= GRACE:
            continue
        with db.transaction(immediate=True) as conn:
            try:
                conn.execute(
                    "INSERT INTO schedule_event_fires(event_key, event_date, fired_at) VALUES (?, ?, ?)",
                    (event.key, event.day.isoformat(), now.isoformat(timespec="seconds")),
                )
            except sqlite3.IntegrityError:
                continue  # already delivered today
            conn.execute(
                "INSERT INTO alarm_events(alarm_id, title, fired_at) VALUES (NULL, ?, ?)",
                (event.title, now.isoformat(timespec="seconds")),
            )
        claimed.append(Ring(event.key, event.title, event.due, event.sound))
    return claimed
