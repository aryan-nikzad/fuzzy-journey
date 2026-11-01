from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .paths import DATABASE_PATH, ensure_data_dir


def connect(path: Path | str = DATABASE_PATH) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(path: Path | str = DATABASE_PATH) -> None:
    ensure_data_dir()
    with connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                alarm_time TEXT NOT NULL,
                days_mask INTEGER NOT NULL DEFAULT 127,
                one_shot_date TEXT,
                sound_enabled INTEGER NOT NULL DEFAULT 1,
                sound_key TEXT NOT NULL DEFAULT 'classic',
                custom_sound_path TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_fired_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_alarms_enabled_time
                ON alarms(enabled, alarm_time);

            CREATE TABLE IF NOT EXISTS alarm_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alarm_id INTEGER,
                title TEXT NOT NULL,
                fired_at TEXT NOT NULL,
                FOREIGN KEY(alarm_id) REFERENCES alarms(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS day_entries (
                day_date TEXT PRIMARY KEY,
                day_type TEXT NOT NULL CHECK(day_type IN ('50','75','off')),
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routine_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'personal',
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                days_mask INTEGER NOT NULL DEFAULT 127,
                alarm_enabled INTEGER NOT NULL DEFAULT 0,
                end_alarm_enabled INTEGER NOT NULL DEFAULT 0,
                sound_enabled INTEGER NOT NULL DEFAULT 1,
                sound_key TEXT NOT NULL DEFAULT 'classic',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prayer_alarm_settings (
                prayer_key TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                offset_minutes INTEGER NOT NULL DEFAULT 0,
                sound_enabled INTEGER NOT NULL DEFAULT 1,
                sound_key TEXT NOT NULL DEFAULT 'classic',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_event_fires (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL,
                event_date TEXT NOT NULL,
                fired_at TEXT NOT NULL,
                UNIQUE(event_key, event_date)
            );
            """
        )
        # Additive migrations preserve databases created by earlier releases.
        migrations = (
            ("alarms", "sound_key", "TEXT NOT NULL DEFAULT 'classic'"),
            ("alarms", "custom_sound_path", "TEXT"),
            ("routine_blocks", "end_alarm_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("routine_blocks", "sound_key", "TEXT NOT NULL DEFAULT 'classic'"),
            ("routine_blocks", "custom_sound_path", "TEXT"),
            ("prayer_alarm_settings", "sound_key", "TEXT NOT NULL DEFAULT 'classic'"),
            ("prayer_alarm_settings", "custom_sound_path", "TEXT"),
        )
        for table, column, definition in migrations:
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        connection.execute(
            "INSERT OR IGNORE INTO app_settings(setting_key, setting_value) VALUES ('time_bank_start_date', ?)",
            (date.today().isoformat(),),
        )


def list_alarms(path: Path | str = DATABASE_PATH) -> list[dict[str, Any]]:
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT id, title, alarm_time, days_mask, one_shot_date,
                   sound_enabled, sound_key, custom_sound_path, enabled, last_fired_date
            FROM alarms
            ORDER BY
                CASE WHEN one_shot_date IS NULL THEN 1 ELSE 0 END,
                one_shot_date,
                alarm_time,
                id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def save_alarm(
    *,
    title: str,
    alarm_time: str,
    days_mask: int,
    one_shot_date: str | None = None,
    sound_enabled: bool = True,
    sound_key: str = "classic",
    custom_sound_path: str | None = None,
    enabled: bool = True,
    alarm_id: int | None = None,
    path: Path | str = DATABASE_PATH,
) -> int:
    initialize(path)
    now = datetime.now().isoformat(timespec="seconds")
    values = (
        title.strip() or "Reminder",
        alarm_time,
        int(days_mask),
        one_shot_date,
        int(sound_enabled),
        sound_key,
        custom_sound_path,
        int(enabled),
        now,
    )
    with connect(path) as connection:
        if alarm_id is None:
            cursor = connection.execute(
                """
                INSERT INTO alarms
                    (title, alarm_time, days_mask, one_shot_date,
                     sound_enabled, sound_key, custom_sound_path, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values[:8], now, now),
            )
            return int(cursor.lastrowid)
        connection.execute(
            """
            UPDATE alarms
            SET title=?, alarm_time=?, days_mask=?, one_shot_date=?,
                sound_enabled=?, sound_key=?, custom_sound_path=?, enabled=?, updated_at=?, last_fired_date=NULL
            WHERE id=?
            """,
            (*values, alarm_id),
        )
        return alarm_id


def set_alarm_enabled(alarm_id: int, enabled: bool, path: Path | str = DATABASE_PATH) -> None:
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            "UPDATE alarms SET enabled=?, updated_at=? WHERE id=?",
            (int(enabled), datetime.now().isoformat(timespec="seconds"), alarm_id),
        )


def delete_alarm(alarm_id: int, path: Path | str = DATABASE_PATH) -> None:
    initialize(path)
    with connect(path) as connection:
        connection.execute("DELETE FROM alarms WHERE id=?", (alarm_id,))


def recent_events(limit: int = 12, path: Path | str = DATABASE_PATH) -> list[dict[str, Any]]:
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT title, fired_at FROM alarm_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def set_day_type(day_date: str, day_type: str, notes: str = "", path: Path | str = DATABASE_PATH) -> None:
    if day_type not in {"50", "75", "off"}:
        raise ValueError("day_type must be 50, 75, or off")
    datetime.strptime(day_date, "%Y-%m-%d")
    now = datetime.now().isoformat(timespec="seconds")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """INSERT INTO day_entries(day_date, day_type, notes, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(day_date) DO UPDATE SET
               day_type=excluded.day_type, notes=excluded.notes, updated_at=excluded.updated_at""",
            (day_date, day_type, notes, now),
        )


def get_day_entries(start_date: str, end_date: str, path: Path | str = DATABASE_PATH) -> list[dict[str, Any]]:
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT day_date, day_type, notes FROM day_entries WHERE day_date BETWEEN ? AND ? ORDER BY day_date",
            (start_date, end_date),
        ).fetchall()
    return [dict(row) for row in rows]


def get_app_setting(key: str, default: str = "", path: Path | str = DATABASE_PATH) -> str:
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)
        ).fetchone()
    return str(row["setting_value"]) if row else default


def set_app_setting(key: str, value: str, path: Path | str = DATABASE_PATH) -> None:
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value""",
            (key, value),
        )


def get_time_bank_start_date(path: Path | str = DATABASE_PATH) -> str:
    initialize(path)
    with connect(path) as connection:
        row = connection.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key='time_bank_start_date'"
        ).fetchone()
    return row["setting_value"] if row else date.today().isoformat()


def set_time_bank_start_date(start_date: str, path: Path | str = DATABASE_PATH) -> None:
    datetime.strptime(start_date, "%Y-%m-%d")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """INSERT INTO app_settings(setting_key, setting_value)
               VALUES ('time_bank_start_date', ?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value""",
            (start_date,),
        )


def day_balance(path: Path | str = DATABASE_PATH, as_of: date | None = None) -> dict[str, Any]:
    """Count only dates from the tracking baseline through the current day.

    Unclassified eligible dates count as normal (50%) days. Future dates and
    dates before the baseline are excluded.
    """
    initialize(path)
    start_date = get_time_bank_start_date(path)
    start = date.fromisoformat(start_date)
    today = as_of or date.today()
    elapsed_days = max(0, (today - start).days + 1)
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT day_type, COUNT(*) AS total FROM day_entries "
            "WHERE day_date >= ? AND day_date <= ? GROUP BY day_type",
            (start_date, today.isoformat()),
        ).fetchall()
    counts = {row["day_type"]: int(row["total"]) for row in rows}
    intensive = counts.get("75", 0)
    days_off = counts.get("off", 0)
    balance = intensive * 0.5 - days_off
    normal_days = max(0, elapsed_days - intensive - days_off)
    return {
        "start_date": start_date,
        "through_date": today.isoformat(),
        "intensive_days": intensive,
        "days_off": days_off,
        "normal_days": normal_days,
        "earned": intensive * 0.5,
        "consumed": days_off,
        "balance": balance,
        "to_next_day_off": (1 - (balance % 1)) % 1,
    }


def list_routine_blocks(path: Path | str = DATABASE_PATH) -> list[dict[str, Any]]:
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM routine_blocks ORDER BY start_time, id"
        ).fetchall()
    return [dict(row) for row in rows]


def save_routine_block(*, title: str, category: str, start_time: str, end_time: str,
                       days_mask: int = 127, alarm_enabled: bool = False,
                       end_alarm_enabled: bool = False, sound_enabled: bool = True,
                       sound_key: str = "classic", custom_sound_path: str | None = None,
                       enabled: bool = True,
                       block_id: int | None = None, path: Path | str = DATABASE_PATH) -> int:
    datetime.strptime(start_time, "%H:%M")
    datetime.strptime(end_time, "%H:%M")
    now = datetime.now().isoformat(timespec="seconds")
    initialize(path)
    with connect(path) as connection:
        if block_id is None:
            cur = connection.execute(
                """INSERT INTO routine_blocks
                (title, category, start_time, end_time, days_mask, alarm_enabled, end_alarm_enabled, sound_enabled, sound_key, custom_sound_path, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title.strip() or "Routine", category, start_time, end_time, days_mask,
                 int(alarm_enabled), int(end_alarm_enabled), int(sound_enabled), sound_key, custom_sound_path, int(enabled), now, now),
            )
            return int(cur.lastrowid)
        connection.execute(
            """UPDATE routine_blocks SET title=?, category=?, start_time=?, end_time=?,
            days_mask=?, alarm_enabled=?, end_alarm_enabled=?, sound_enabled=?, sound_key=?, custom_sound_path=?, enabled=?, updated_at=? WHERE id=?""",
            (title.strip() or "Routine", category, start_time, end_time, days_mask,
             int(alarm_enabled), int(end_alarm_enabled), int(sound_enabled), sound_key, custom_sound_path, int(enabled), now, block_id),
        )
        return block_id


def set_routine_enabled(block_id: int, enabled: bool, path: Path | str = DATABASE_PATH) -> None:
    initialize(path)
    with connect(path) as connection:
        connection.execute("UPDATE routine_blocks SET enabled=?, updated_at=? WHERE id=?",
                           (int(enabled), datetime.now().isoformat(timespec="seconds"), block_id))


def delete_routine_block(block_id: int, path: Path | str = DATABASE_PATH) -> None:
    initialize(path)
    with connect(path) as connection:
        connection.execute("DELETE FROM routine_blocks WHERE id=?", (block_id,))


def set_prayer_alarm(prayer_key: str, enabled: bool, offset_minutes: int = 0,
                     sound_enabled: bool = True, sound_key: str = "classic",
                     custom_sound_path: str | None = None,
                     path: Path | str = DATABASE_PATH) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    initialize(path)
    with connect(path) as connection:
        connection.execute(
            """INSERT INTO prayer_alarm_settings(prayer_key, enabled, offset_minutes, sound_enabled, sound_key, custom_sound_path, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(prayer_key) DO UPDATE SET enabled=excluded.enabled,
            offset_minutes=excluded.offset_minutes, sound_enabled=excluded.sound_enabled,
            sound_key=excluded.sound_key, custom_sound_path=excluded.custom_sound_path, updated_at=excluded.updated_at""",
            (prayer_key, int(enabled), int(offset_minutes), int(sound_enabled), sound_key, custom_sound_path, now),
        )


def list_prayer_alarms(path: Path | str = DATABASE_PATH) -> dict[str, dict[str, Any]]:
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute("SELECT * FROM prayer_alarm_settings").fetchall()
    return {row["prayer_key"]: dict(row) for row in rows}
