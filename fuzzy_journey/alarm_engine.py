from __future__ import annotations

import csv
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


def _block_interval(block: dict[str, Any], start_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(start_day, time.fromisoformat(block["start_time"]))
    end = datetime.combine(start_day, time.fromisoformat(block["end_time"]))
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _routine_pause_intervals(
    work_block: dict[str, Any],
    all_blocks: list[dict[str, Any]],
    work_day: date,
) -> tuple[datetime, datetime, list[tuple[datetime, datetime, str]]]:
    start, base_end = _block_interval(work_block, work_day)
    if str(work_block.get("category", "")).lower() != "work":
        return start, base_end, []

    intervals: list[tuple[datetime, datetime, str]] = []
    for block in all_blocks:
        if block.get("id") == work_block.get("id"):
            continue
        if not block.get("enabled", True):
            continue
        if str(block.get("category", "")).lower() == "work":
            continue
        for offset in range(-1, 5):
            pause_day = work_day + timedelta(days=offset)
            if not (int(block.get("days_mask") or 0) & WEEKDAY_BITS[pause_day.weekday()]):
                continue
            pause_start, pause_end = _block_interval(block, pause_day)
            if pause_end > start:
                intervals.append((pause_start, pause_end, str(block.get("title") or "Activity")))

    intervals.sort(key=lambda item: item[0])
    merged: list[tuple[datetime, datetime, str]] = []
    for pause_start, pause_end, title in intervals:
        if not merged or pause_start > merged[-1][1]:
            merged.append((pause_start, pause_end, title))
        elif pause_end > merged[-1][1]:
            old_start, _old_end, old_title = merged[-1]
            merged[-1] = (old_start, pause_end, old_title if old_title == title else "Other activity")
    return start, base_end, merged


def effective_routine_end(
    work_block: dict[str, Any],
    all_blocks: list[dict[str, Any]],
    work_day: date,
) -> datetime:
    """Return the finish after enabled non-work activities pause productive work."""
    start, base_end, pauses = _routine_pause_intervals(work_block, all_blocks, work_day)
    remaining = base_end - start
    cursor = start
    for pause_start, pause_end, _title in pauses:
        if pause_end <= cursor:
            continue
        if pause_start > cursor:
            productive = pause_start - cursor
            if productive >= remaining:
                return cursor + remaining
            remaining -= productive
            cursor = pause_start
        if pause_start <= cursor < pause_end:
            cursor = pause_end
    return cursor + remaining


def routine_work_state(
    work_block: dict[str, Any],
    all_blocks: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Describe progress in a work block, excluding time spent in activities."""
    start, base_end, pauses = _routine_pause_intervals(work_block, all_blocks, now.date())
    finish = effective_routine_end(work_block, all_blocks, now.date())
    planned = base_end - start
    if now < start:
        return {
            "status": "upcoming", "start": start, "end": finish,
            "remaining": planned, "pause_title": None, "pause_until": None,
        }
    if now >= finish:
        return {
            "status": "completed", "start": start, "end": finish,
            "remaining": timedelta(0), "pause_title": None, "pause_until": None,
        }

    paused_total = timedelta(0)
    active_pause = None
    for pause_start, pause_end, title in pauses:
        overlap_start = max(start, pause_start)
        overlap_end = min(now, pause_end, finish)
        if overlap_end > overlap_start:
            paused_total += overlap_end - overlap_start
        if pause_start <= now < pause_end:
            active_pause = (title, pause_end)

    wall_elapsed = max(timedelta(0), min(now, finish) - start)
    productive_elapsed = min(planned, max(timedelta(0), wall_elapsed - paused_total))
    remaining = max(timedelta(0), planned - productive_elapsed)
    return {
        "status": "paused" if active_pause else "in_progress",
        "start": start,
        "end": finish,
        "remaining": remaining,
        "pause_title": active_pause[0] if active_pause else None,
        "pause_until": active_pause[1] if active_pause else None,
    }


def fire_due_alarms(
    now: datetime | None = None,
    *,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Claim due reminders exactly once and record delivery before notifying."""
    now = now or datetime.now().astimezone().replace(tzinfo=None)
    path = db_path or str(database.DATABASE_PATH)
    database.initialize(path)
    fired: list[dict[str, Any]] = []

    with database.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
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
                   sound_enabled, sound_key, custom_sound_path, enabled, last_fired_date
            FROM alarms WHERE enabled=1
            """
        ).fetchall()

        for row in rows:
            alarm = dict(row)
            if not should_fire(alarm, now):
                continue

            one_shot = bool(alarm.get("one_shot_date"))
            claimed = connection.execute(
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
            if claimed.rowcount != 1:
                continue

            connection.execute(
                "INSERT INTO alarm_events(alarm_id, title, fired_at) VALUES (?, ?, ?)",
                (alarm["id"], alarm["title"], now.isoformat(timespec="seconds")),
            )
            alarm["sound_enabled"] = bool(alarm["sound_enabled"])
            fired.append(alarm)

    return fired


def fire_due_schedule_events(now: datetime | None = None, *, db_path: str | None = None) -> list[dict[str, Any]]:
    """Resolve prayer and routine start/end alarms from local data, once per scheduled day."""
    from .paths import schedule_path

    now = now or datetime.now().astimezone().replace(tzinfo=None)
    path = db_path or str(database.DATABASE_PATH)
    database.initialize(path)
    candidates: list[tuple[str, str, datetime, bool, str, str | None, str]] = []

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

    for key, settings in database.list_prayer_alarms(path).items():
        if not settings.get("enabled") or not prayer_times.get(key):
            continue
        try:
            due = datetime.combine(now.date(), time.fromisoformat(prayer_times[key]))
            due += timedelta(minutes=int(settings.get("offset_minutes") or 0))
        except ValueError:
            continue
        candidates.append((
            f"prayer:{key}", f"{key} prayer", due,
            bool(settings.get("sound_enabled", 1)),
            str(settings.get("sound_key") or "classic"), settings.get("custom_sound_path"), now.date().isoformat(),
        ))

    blocks = database.list_routine_blocks(path)
    for block in blocks:
        if not block.get("enabled"):
            continue
        # Previous start day is included for blocks that end after midnight.
        for offset in (-1, 0):
            start_day = now.date() + timedelta(days=offset)
            if not (int(block.get("days_mask") or 0) & WEEKDAY_BITS[start_day.weekday()]):
                continue
            start_due, base_end = _block_interval(block, start_day)
            sound_enabled = bool(block.get("sound_enabled", 1))
            sound_key = str(block.get("sound_key") or "classic")
            custom_sound_path = block.get("custom_sound_path")
            event_day = start_day.isoformat()
            if offset == 0 and block.get("alarm_enabled"):
                candidates.append((
                    f"routine:{block['id']}", block["title"], start_due,
                    sound_enabled, sound_key, custom_sound_path, event_day,
                ))
            if block.get("end_alarm_enabled"):
                end_due = (
                    effective_routine_end(block, blocks, start_day)
                    if str(block.get("category", "")).lower() == "work"
                    else base_end
                )
                candidates.append((
                    f"routine:{block['id']}:end", f"{block['title']} finished", end_due,
                    sound_enabled, sound_key, custom_sound_path, event_day,
                ))

    fired: list[dict[str, Any]] = []
    with database.connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for event_key, title, due, sound_enabled, sound_key, custom_sound_path, event_day in candidates:
            elapsed = now - due
            if elapsed < timedelta(0) or elapsed > MISSED_ALARM_GRACE:
                continue
            try:
                connection.execute(
                    "INSERT INTO schedule_event_fires(event_key, event_date, fired_at) VALUES (?, ?, ?)",
                    (event_key, event_day, now.isoformat(timespec="seconds")),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    continue
                raise
            connection.execute(
                "INSERT INTO alarm_events(alarm_id, title, fired_at) VALUES (NULL, ?, ?)",
                (title, now.isoformat(timespec="seconds")),
            )
            fired.append({
                "id": event_key,
                "title": title,
                "alarm_time": due.strftime("%H:%M:%S" if due.second else "%H:%M"),
                "sound_enabled": sound_enabled,
                "sound_key": sound_key,
                "custom_sound_path": custom_sound_path,
            })
    return fired
