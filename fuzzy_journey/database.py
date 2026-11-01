from __future__ import annotations

import sqlite3
from datetime import datetime
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
            """
        )


def list_alarms(path: Path | str = DATABASE_PATH) -> list[dict[str, Any]]:
    initialize(path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT id, title, alarm_time, days_mask, one_shot_date,
                   sound_enabled, enabled, last_fired_date
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
        int(enabled),
        now,
    )
    with connect(path) as connection:
        if alarm_id is None:
            cursor = connection.execute(
                """
                INSERT INTO alarms
                    (title, alarm_time, days_mask, one_shot_date,
                     sound_enabled, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values[:6], now, now),
            )
            return int(cursor.lastrowid)
        connection.execute(
            """
            UPDATE alarms
            SET title=?, alarm_time=?, days_mask=?, one_shot_date=?,
                sound_enabled=?, enabled=?, updated_at=?, last_fired_date=NULL
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
