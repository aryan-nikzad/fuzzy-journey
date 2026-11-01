from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from . import database

WEEKDAY_BITS = (1, 2, 4, 8, 16, 32, 64)
MISSED_ALARM_GRACE = timedelta(minutes=5)


def repeats_on(alarm: dict[str, Any], day: date) -> bool:
    one_shot_date = alarm.get("one_shot_date")
    if one_shot_date:
        return one_shot_date == day.isoformat()
    return bool(int(alarm.get("days_mask") or 0) & WEEKDAY_BITS[day.weekday()])


def should_fire(alarm: dict[str, Any], now: datetime) -> bool:
    if not alarm.get("enabled"):
        return False
    if alarm.get("last_fired_date") == now.date().isoformat():
        return False
    if not repeats_on(alarm, now.date()):
        return False
    scheduled_time = time.fromisoformat(alarm["alarm_time"])
    scheduled = datetime.combine(now.date(), scheduled_time)
    elapsed = now - scheduled
    return timedelta(0) <= elapsed <= MISSED_ALARM_GRACE


def next_occurrence(alarm: dict[str, Any], now: datetime) -> datetime | None:
    if not alarm.get("enabled"):
        return None
    scheduled_time = time.fromisoformat(alarm["alarm_time"])
    for offset in range(0, 370):
        day = now.date() + timedelta(days=offset)
        if not repeats_on(alarm, day):
            continue
        candidate = datetime.combine(day, scheduled_time)
        if candidate >= now:
            return candidate
        if alarm.get("one_shot_date"):
            return None
    return None


def fire_due_alarms(
    now: datetime | None = None,
    *,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Claim due alarms exactly once and record their delivery before notifying."""
    now = now or datetime.now().astimezone().replace(tzinfo=None)
    path = db_path or str(database.DATABASE_PATH)
    database.initialize(path)
    fired: list[dict[str, Any]] = []

    with database.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Expire one-time reminders from earlier dates instead of leaving
        # permanently enabled alarms that can no longer be delivered.
        connection.execute(
            """
            UPDATE alarms SET enabled=0, updated_at=?
            WHERE enabled=1 AND one_shot_date IS NOT NULL AND one_shot_date < ?
            """,
            (now.isoformat(timespec="seconds"), now.date().isoformat()),
        )
        rows = connection.execute(
            """
            SELECT id, title, alarm_time, days_mask, one_shot_date,
                   sound_enabled, enabled, last_fired_date
            FROM alarms WHERE enabled=1
            """
        ).fetchall()

        for row in rows:
            alarm = dict(row)
            if not should_fire(alarm, now):
                continue

            one_shot = bool(alarm.get("one_shot_date"))
            cursor = connection.execute(
                """
                UPDATE alarms
                SET last_fired_date=?,
                    enabled=CASE WHEN ? THEN 0 ELSE enabled END,
                    updated_at=?
                WHERE id=? AND enabled=1
                  AND (last_fired_date IS NULL OR last_fired_date<>?)
                """,
                (
                    now.date().isoformat(),
                    int(one_shot),
                    now.isoformat(timespec="seconds"),
                    alarm["id"],
                    now.date().isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                continue

            connection.execute(
                "INSERT INTO alarm_events(alarm_id, title, fired_at) VALUES (?, ?, ?)",
                (alarm["id"], alarm["title"], now.isoformat(timespec="seconds")),
            )
            alarm["sound_enabled"] = bool(alarm["sound_enabled"])
            fired.append(alarm)

    return fired
