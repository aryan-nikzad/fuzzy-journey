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


def fire_due_schedule_events(now: datetime | None = None, *, db_path: str | None = None) -> list[dict[str, Any]]:
    """Resolve prayer and routine alarms from local data and claim each event once."""
    import csv
    from .paths import schedule_path

    now = now or datetime.now().astimezone().replace(tzinfo=None)
    path = db_path or str(database.DATABASE_PATH)
    database.initialize(path)
    events: list[dict[str, Any]] = []
    schedule_file = schedule_path(now.year)
    prayer_times: dict[str, str] = {}
    if schedule_file and schedule_file.is_file():
        with schedule_file.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    row_day = datetime.strptime(row["Date"], "%d-%m-%Y").date()
                except (KeyError, ValueError):
                    continue
                if row_day == now.date():
                    prayer_times = row
                    break

    candidates: list[tuple[str, str, str, bool]] = []
    prayer_settings = database.list_prayer_alarms(path)
    for key, settings in prayer_settings.items():
        if not settings.get("enabled") or not prayer_times.get(key):
            continue
        try:
            base = datetime.combine(now.date(), time.fromisoformat(prayer_times[key]))
        except ValueError:
            continue
        due = base + timedelta(minutes=int(settings.get("offset_minutes") or 0))
        candidates.append((f"prayer:{key}", f"{key} prayer", due.strftime("%H:%M"), bool(settings.get("sound_enabled", 1))))

    for block in database.list_routine_blocks(path):
        if not block.get("enabled") or not block.get("alarm_enabled"):
            continue
        if not (int(block.get("days_mask") or 0) & WEEKDAY_BITS[now.weekday()]):
            continue
        candidates.append((f"routine:{block['id']}", block["title"], block["start_time"], bool(block["sound_enabled"])))

    with database.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for event_key, title, clock, sound in candidates:
            due = datetime.combine(now.date(), time.fromisoformat(clock))
            elapsed = now - due
            if elapsed < timedelta(0) or elapsed > MISSED_ALARM_GRACE:
                continue
            try:
                connection.execute(
                    "INSERT INTO schedule_event_fires(event_key, event_date, fired_at) VALUES (?, ?, ?)",
                    (event_key, now.date().isoformat(), now.isoformat(timespec="seconds")),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    continue
                raise
            connection.execute(
                "INSERT INTO alarm_events(alarm_id, title, fired_at) VALUES (NULL, ?, ?)",
                (title, now.isoformat(timespec="seconds")),
            )
            events.append({"id": event_key, "title": title, "sound_enabled": sound})
    return events
