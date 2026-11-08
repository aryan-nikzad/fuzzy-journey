"""SQLite persistence.

One :class:`Database` object per process. Each operation opens a short-lived
connection, so the GUI and the alarm service can share the file safely (WAL
mode, with a busy timeout). The schema is migrated once, when the object is
created, and is compatible with databases written by 1.x releases.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .models import (
    SOUND_PRESETS,
    Activity,
    Alarm,
    DayEntry,
    FiredEvent,
    Location,
    PrayerAlarm,
    Sound,
    Task,
    TaskStatus,
)
from .paths import DATABASE_PATH, ensure_data_dir
from .pomodoro import EVERY_RANGE, FOCUS_RANGE, LONG_RANGE, SHORT_RANGE, ManualPause, PomodoroSettings
from .rhythm import DEFAULT_EVENING_START, DayKind, parse_evening_start
from .tasks import ORDER_MODES, ORDER_SEQUENCE, PRAYERS, can_cancel, can_carry
from .timeutil import duration_hhmm, parse_clock, parse_hhmm_duration

SCHEMA_VERSION = 5


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Migrations
# --------------------------------------------------------------------------


def _migrate_to_v1(conn: sqlite3.Connection) -> None:
    """Create the base schema, and upgrade any database written before versioning."""
    conn.executescript(
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
        CREATE INDEX IF NOT EXISTS idx_alarms_enabled_time ON alarms(enabled, alarm_time);

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
            custom_sound_path TEXT,
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
            custom_sound_path TEXT,
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
    # Columns added by releases before schema versioning existed.
    additive = (
        ("alarms", "sound_key", "TEXT NOT NULL DEFAULT 'classic'"),
        ("alarms", "custom_sound_path", "TEXT"),
        ("routine_blocks", "end_alarm_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("routine_blocks", "sound_key", "TEXT NOT NULL DEFAULT 'classic'"),
        ("routine_blocks", "custom_sound_path", "TEXT"),
        ("prayer_alarm_settings", "sound_key", "TEXT NOT NULL DEFAULT 'classic'"),
        ("prayer_alarm_settings", "custom_sound_path", "TEXT"),
    )
    for table, column, definition in additive:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute(
        "INSERT OR IGNORE INTO app_settings(setting_key, setting_value) VALUES ('time_bank_start_date', ?)",
        (date.today().isoformat(),),
    )


def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    """Tasks, and the manual pauses of a day's pomodoro."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_date TEXT NOT NULL,
            title TEXT NOT NULL,
            minutes INTEGER NOT NULL,
            level INTEGER NOT NULL DEFAULT 2,
            position INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unset',
            origin_id INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_day ON tasks(day_date);

        CREATE TABLE IF NOT EXISTS pomodoro_pauses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_date TEXT NOT NULL,
            paused_at TEXT NOT NULL,
            resumed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pomodoro_pauses_day ON pomodoro_pauses(day_date);
        """
    )


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    """A Recovered day is a Steady day with a start time; the CHECK on day_type stays valid."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(day_entries)")}
    if "start_time" not in existing:
        conn.execute("ALTER TABLE day_entries ADD COLUMN start_time TEXT")


def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    """Night work: minutes of overtime after Isha, per day."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(day_entries)")}
    if "overtime_minutes" not in existing:
        conn.execute("ALTER TABLE day_entries ADD COLUMN overtime_minutes INTEGER NOT NULL DEFAULT 0")


def _migrate_to_v5(conn: sqlite3.Connection) -> None:
    """Tasks have a kind: an ordinary task, or one of the five daily prayers."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "kind" not in existing:
        conn.execute("ALTER TABLE tasks ADD COLUMN kind TEXT NOT NULL DEFAULT 'task'")


#: Append new migrations here; never edit an old one.
MIGRATIONS = (_migrate_to_v1, _migrate_to_v2, _migrate_to_v3, _migrate_to_v4, _migrate_to_v5)


# --------------------------------------------------------------------------
# Row <-> object helpers
# --------------------------------------------------------------------------


def _sound(row: sqlite3.Row) -> Sound:
    return Sound(
        enabled=bool(row["sound_enabled"]),
        key=row["sound_key"] or "classic",
        custom_path=row["custom_sound_path"],
    )


def _alarm(row: sqlite3.Row) -> Alarm:
    return Alarm(
        id=row["id"],
        title=row["title"],
        time=row["alarm_time"],
        days_mask=int(row["days_mask"]),
        one_shot_date=row["one_shot_date"],
        sound=_sound(row),
        enabled=bool(row["enabled"]),
        last_fired_date=row["last_fired_date"],
    )


def _activity(row: sqlite3.Row) -> Activity:
    return Activity(
        id=row["id"],
        title=row["title"],
        category=row["category"],
        start=row["start_time"],
        end=row["end_time"],
        days_mask=int(row["days_mask"]),
        alarm_at_start=bool(row["alarm_enabled"]),
        alarm_at_end=bool(row["end_alarm_enabled"]),
        sound=_sound(row),
        enabled=bool(row["enabled"]),
    )


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DATABASE_PATH
        if path is None:
            ensure_data_dir()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()
        self.settings = Settings(self)

    # -- connections -------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        # isolation_level=None: we manage transactions explicitly.
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """A connection in autocommit mode, always closed afterwards."""
        conn = self._open()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Run a block atomically. ``immediate`` takes the write lock up front."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def _migrate(self) -> None:
        # Migrations are idempotent (IF NOT EXISTS / add-column-if-missing), so it is
        # safe if the GUI and the alarm service happen to migrate at the same moment.
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for target, migration in enumerate(MIGRATIONS, start=1):
                if version < target:
                    migration(conn)
                    conn.execute(f"PRAGMA user_version = {target}")

    # -- reminders ---------------------------------------------------------

    def list_alarms(self) -> list[Alarm]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM alarms
                ORDER BY CASE WHEN one_shot_date IS NULL THEN 1 ELSE 0 END,
                         one_shot_date, alarm_time, id
                """
            ).fetchall()
        return [_alarm(row) for row in rows]

    def save_alarm(self, alarm: Alarm) -> int:
        now = _now_iso()
        values = (
            alarm.title.strip() or "Reminder",
            alarm.time,
            int(alarm.days_mask),
            alarm.one_shot_date,
            int(alarm.sound.enabled),
            alarm.sound.key,
            alarm.sound.custom_path,
            int(alarm.enabled),
        )
        with self.transaction() as conn:
            if alarm.id is None:
                cursor = conn.execute(
                    """INSERT INTO alarms (title, alarm_time, days_mask, one_shot_date,
                           sound_enabled, sound_key, custom_sound_path, enabled, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*values, now, now),
                )
                alarm.id = int(cursor.lastrowid)
            else:
                conn.execute(
                    """UPDATE alarms SET title=?, alarm_time=?, days_mask=?, one_shot_date=?,
                           sound_enabled=?, sound_key=?, custom_sound_path=?, enabled=?,
                           updated_at=?, last_fired_date=NULL
                       WHERE id=?""",
                    (*values, now, alarm.id),
                )
        return alarm.id

    def set_alarm_enabled(self, alarm_id: int, enabled: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE alarms SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), _now_iso(), alarm_id),
            )

    def delete_alarm(self, alarm_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM alarms WHERE id=?", (alarm_id,))

    def recent_events(self, limit: int = 12) -> list[FiredEvent]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT title, fired_at FROM alarm_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [FiredEvent(row["title"], row["fired_at"]) for row in rows]

    def prune_history(self, keep: int = 500) -> None:
        """Keep the delivery log and the once-per-day claim table from growing forever."""
        cutoff = (date.today() - timedelta(days=60)).isoformat()
        with self.transaction() as conn:
            conn.execute(
                "DELETE FROM alarm_events WHERE id NOT IN "
                "(SELECT id FROM alarm_events ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            conn.execute("DELETE FROM schedule_event_fires WHERE event_date < ?", (cutoff,))

    # -- activities (routine blocks) ----------------------------------------

    def list_activities(self) -> list[Activity]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM routine_blocks ORDER BY start_time, id").fetchall()
        return [_activity(row) for row in rows]

    def save_activity(self, activity: Activity) -> int:
        parse_clock(activity.start)
        parse_clock(activity.end)
        now = _now_iso()
        values = (
            activity.title.strip() or "Activity",
            activity.category,
            activity.start,
            activity.end,
            int(activity.days_mask),
            int(activity.alarm_at_start),
            int(activity.alarm_at_end),
            int(activity.sound.enabled),
            activity.sound.key,
            activity.sound.custom_path,
            int(activity.enabled),
        )
        with self.transaction() as conn:
            if activity.id is None:
                cursor = conn.execute(
                    """INSERT INTO routine_blocks (title, category, start_time, end_time, days_mask,
                           alarm_enabled, end_alarm_enabled, sound_enabled, sound_key, custom_sound_path,
                           enabled, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*values, now, now),
                )
                activity.id = int(cursor.lastrowid)
            else:
                conn.execute(
                    """UPDATE routine_blocks SET title=?, category=?, start_time=?, end_time=?, days_mask=?,
                           alarm_enabled=?, end_alarm_enabled=?, sound_enabled=?, sound_key=?,
                           custom_sound_path=?, enabled=?, updated_at=?
                       WHERE id=?""",
                    (*values, now, activity.id),
                )
        return activity.id

    def set_activity_enabled(self, activity_id: int, enabled: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE routine_blocks SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), _now_iso(), activity_id),
            )

    def delete_activity(self, activity_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM routine_blocks WHERE id=?", (activity_id,))

    # -- prayer alarms -----------------------------------------------------

    def prayer_alarms(self) -> dict[str, PrayerAlarm]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM prayer_alarm_settings").fetchall()
        return {
            row["prayer_key"]: PrayerAlarm(
                key=row["prayer_key"],
                enabled=bool(row["enabled"]),
                offset_minutes=int(row["offset_minutes"] or 0),
                sound=_sound(row),
            )
            for row in rows
        }

    def save_prayer_alarm(self, alarm: PrayerAlarm) -> None:
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO prayer_alarm_settings
                       (prayer_key, enabled, offset_minutes, sound_enabled, sound_key, custom_sound_path, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(prayer_key) DO UPDATE SET
                       enabled=excluded.enabled, offset_minutes=excluded.offset_minutes,
                       sound_enabled=excluded.sound_enabled, sound_key=excluded.sound_key,
                       custom_sound_path=excluded.custom_sound_path, updated_at=excluded.updated_at""",
                (
                    alarm.key,
                    int(alarm.enabled),
                    int(alarm.offset_minutes),
                    int(alarm.sound.enabled),
                    alarm.sound.key,
                    alarm.sound.custom_path,
                    _now_iso(),
                ),
            )

    # -- day entries -------------------------------------------------------

    def set_day_kind(self, day: date, kind: DayKind, note: str = "", start: time | None = None) -> None:
        """Mark a day. ``RECOVERED`` is a Steady entry plus the time the day began; saving it
        again without ``start`` (to change a note) keeps the time already stored."""
        recovered = kind is DayKind.RECOVERED
        code = DayKind.STEADY.value if recovered else kind.value
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO day_entries(day_date, day_type, notes, updated_at, start_time)
                   VALUES (:day, :code, :note, :now, :start)
                   ON CONFLICT(day_date) DO UPDATE SET
                       day_type=excluded.day_type, notes=excluded.notes, updated_at=excluded.updated_at,
                       overtime_minutes=CASE WHEN excluded.day_type='off' THEN 0 ELSE day_entries.overtime_minutes END,
                       start_time=CASE WHEN :recovered
                                       THEN COALESCE(excluded.start_time, day_entries.start_time) ELSE NULL END""",
                {"day": day.isoformat(), "code": code, "note": note, "now": _now_iso(),
                 "start": start.strftime("%H:%M") if recovered and start else None, "recovered": int(recovered)},
            )

    def set_day_overtime(self, day: date, minutes: int) -> None:
        """Set (or, with 0, remove) the night work of a day, keeping whatever kind it already has."""
        with self.transaction() as conn:
            conn.execute(
                """INSERT INTO day_entries(day_date, day_type, notes, updated_at, overtime_minutes)
                   VALUES (?, '50', '', ?, ?)
                   ON CONFLICT(day_date) DO UPDATE SET
                       overtime_minutes=excluded.overtime_minutes, updated_at=excluded.updated_at""",
                (day.isoformat(), _now_iso(), max(0, minutes)),
            )

    def day_entries(self, start: date, end: date) -> dict[date, DayEntry]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT day_date, day_type, notes, start_time, overtime_minutes FROM day_entries "
                "WHERE day_date BETWEEN ? AND ? ORDER BY day_date",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        entries = {}
        for row in rows:
            day = date.fromisoformat(row["day_date"])
            kind, started = DayKind.from_code(row["day_type"]), None
            if kind is DayKind.STEADY and row["start_time"]:
                try:
                    started, kind = parse_clock(row["start_time"]), DayKind.RECOVERED
                except ValueError:
                    pass
            entries[day] = DayEntry(day, kind, row["notes"] or "", started, int(row["overtime_minutes"] or 0))
        return entries

    def day_kind(self, day: date) -> DayKind:
        entry = self.day_entries(day, day).get(day)
        return entry.kind if entry else DayKind.STEADY


    # -- tasks -------------------------------------------------------------

    @staticmethod
    def _task(row: sqlite3.Row) -> Task:
        return Task(
            title=row["title"], minutes=row["minutes"], day=date.fromisoformat(row["day_date"]),
            level=row["level"], position=row["position"], status=TaskStatus(row["status"]),
            origin_id=row["origin_id"], id=row["id"], kind=row["kind"],
        )

    def tasks_on(self, day: date, *, prayers: bool = True) -> list[Task]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE day_date=? ORDER BY position, id", (day.isoformat(),)
            ).fetchall()
        return [t for t in map(self._task, rows) if prayers or not t.is_prayer]

    def ensure_prayer_tasks(self, day: date) -> None:
        """Give ``day`` its five prayers. Safe to call any number of times."""
        with self.transaction(immediate=True) as conn:
            have = {r[0] for r in conn.execute(
                "SELECT title FROM tasks WHERE day_date=? AND kind='prayer' AND origin_id IS NULL",
                (day.isoformat(),),
            )}
            for position, name in enumerate(PRAYERS):
                if name not in have:
                    conn.execute(
                        """INSERT INTO tasks(day_date, title, minutes, level, position, status, kind, created_at)
                           VALUES (?, ?, 0, 2, ?, 'unset', 'prayer', ?)""",
                        (day.isoformat(), name, position, _now_iso()),
                    )

    def unset_tasks_before(self, day: date) -> list[Task]:
        """Tasks from earlier days that still have no status."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE day_date<? AND status='unset' ORDER BY day_date, position, id",
                (day.isoformat(),),
            ).fetchall()
        return [self._task(r) for r in rows]

    def save_task(self, task: Task) -> int:
        with self.transaction() as conn:
            if task.id is None:
                position = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE day_date=?",
                    (task.day.isoformat(),),
                ).fetchone()[0]
                cursor = conn.execute(
                    """INSERT INTO tasks(day_date, title, minutes, level, position, status, origin_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (task.day.isoformat(), task.title.strip(), task.minutes, task.level, position,
                     task.status.value, task.origin_id, _now_iso()),
                )
                task.id, task.position = int(cursor.lastrowid), position
            else:
                conn.execute(
                    "UPDATE tasks SET title=?, minutes=?, level=? WHERE id=? AND kind='task'",
                    (task.title.strip(), task.minutes, task.level, task.id),
                )
        return int(task.id)

    def delete_task(self, task_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM tasks WHERE origin_id=? AND status='unset'", (task_id,))
            conn.execute("DELETE FROM tasks WHERE id=? AND kind='task'", (task_id,))  # prayers stay

    def move_task(self, task: Task, direction: int, siblings: list[Task]) -> None:
        """Swap ``task`` with its neighbour in ``siblings`` (already in display order)."""
        ids = [t.id for t in siblings]
        if task.id not in ids:
            return
        i, j = ids.index(task.id), ids.index(task.id) + direction
        if not 0 <= j < len(ids):
            return
        order = list(siblings)
        order[i], order[j] = order[j], order[i]
        with self.transaction() as conn:
            for position, item in enumerate(order):
                conn.execute("UPDATE tasks SET position=? WHERE id=?", (position, item.id))

    def set_task_status(self, task_id: int, status: TaskStatus, today: date | None = None) -> None:
        """Settle a task. ``CARRIED`` puts a copy on the next day (never in the past, so on ``today``
        if the task is older than yesterday); changing it back removes the copy."""
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                return
            task = self._task(row)
            if (status is TaskStatus.CARRIED and not can_carry(task)) or (
                status is TaskStatus.CANCELLED and not can_cancel(task)
            ):
                return  # the rules for prayers live in tasks.py; this is where they are enforced
            conn.execute("UPDATE tasks SET status=? WHERE id=?", (status.value, task_id))
            if status is TaskStatus.CARRIED and task.status is not TaskStatus.CARRIED:
                target = task.day + timedelta(days=1)
                tomorrow = max(target, today).isoformat() if today else target.isoformat()
                position = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE day_date=?", (tomorrow,)
                ).fetchone()[0]
                conn.execute(
                    """INSERT INTO tasks(day_date, title, minutes, level, position, status, origin_id, kind, created_at)
                       VALUES (?, ?, ?, ?, ?, 'unset', ?, ?, ?)""",
                    (tomorrow, task.title, task.minutes, task.level, position, task_id, task.kind, _now_iso()),
                )
            elif task.status is TaskStatus.CARRIED and status is not TaskStatus.CARRIED:
                conn.execute("DELETE FROM tasks WHERE origin_id=? AND status='unset'", (task_id,))

    # -- pomodoro pauses ---------------------------------------------------

    def pomodoro_pauses(self, day: date) -> list[ManualPause]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT paused_at, resumed_at FROM pomodoro_pauses WHERE day_date=? ORDER BY paused_at",
                (day.isoformat(),),
            ).fetchall()
        return [
            (datetime.fromisoformat(r["paused_at"]),
             datetime.fromisoformat(r["resumed_at"]) if r["resumed_at"] else None)
            for r in rows
        ]

    def pause_pomodoro(self, day: date, at: datetime) -> None:
        with self.transaction(immediate=True) as conn:
            open_ = conn.execute(
                "SELECT 1 FROM pomodoro_pauses WHERE day_date=? AND resumed_at IS NULL", (day.isoformat(),)
            ).fetchone()
            if not open_:
                conn.execute(
                    "INSERT INTO pomodoro_pauses(day_date, paused_at) VALUES (?, ?)",
                    (day.isoformat(), at.isoformat(timespec="seconds")),
                )

    def resume_pomodoro(self, day: date, at: datetime) -> None:
        with self.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE pomodoro_pauses SET resumed_at=? WHERE day_date=? AND resumed_at IS NULL",
                (at.isoformat(timespec="seconds"), day.isoformat()),
            )


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


class Settings:
    """Typed access to the key/value ``app_settings`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: str = "") -> str:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)
            ).fetchone()
        return str(row["setting_value"]) if row else default

    def set(self, key: str, value: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                """INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?)
                   ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value""",
                (key, value),
            )

    # appearance -----------------------------------------------------------

    @property
    def theme(self) -> str:
        value = self.get("theme", "system")
        return value if value in {"system", "light", "dark"} else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        self.set("theme", value)

    # rhythm ---------------------------------------------------------------

    @property
    def evening_start(self) -> time:
        try:
            return parse_evening_start(self.get("evening_work_start", "18:00") or "18:00")
        except ValueError:
            return DEFAULT_EVENING_START

    @evening_start.setter
    def evening_start(self, value: time) -> None:
        self.set("evening_work_start", value.strftime("%H:%M"))

    @property
    def flex(self) -> timedelta:
        try:
            return parse_hhmm_duration(self.get("flex_time", "00:00") or "00:00")
        except ValueError:
            return timedelta(0)

    @flex.setter
    def flex(self, value: timedelta) -> None:
        self.set("flex_time", duration_hhmm(value))

    # focus: pomodoro, planning and tasks -----------------------------------

    def _flag(self, key: str, default: bool) -> bool:
        return self.get(key, "1" if default else "0") == "1"

    def _number(self, key: str, default: int, low: int, high: int) -> int:
        try:
            return min(high, max(low, int(self.get(key, str(default)))))
        except ValueError:
            return default

    @property
    def pomodoro(self) -> PomodoroSettings:
        d = PomodoroSettings()
        return PomodoroSettings(
            enabled=self._flag("pomo_enabled", d.enabled),
            focus=self._number("pomo_focus", d.focus, *FOCUS_RANGE),
            short_enabled=self._flag("pomo_short_enabled", d.short_enabled),
            short=self._number("pomo_short", d.short, *SHORT_RANGE),
            long_enabled=self._flag("pomo_long_enabled", d.long_enabled),
            long=self._number("pomo_long", d.long, *LONG_RANGE),
            long_every=self._number("pomo_long_every", d.long_every, *EVERY_RANGE),
            planning_enabled=self._flag("planning_enabled", d.planning_enabled),
        )

    @pomodoro.setter
    def pomodoro(self, v: PomodoroSettings) -> None:
        for key, value in (
            ("pomo_enabled", int(v.enabled)), ("pomo_focus", v.focus),
            ("pomo_short_enabled", int(v.short_enabled)), ("pomo_short", v.short),
            ("pomo_long_enabled", int(v.long_enabled)), ("pomo_long", v.long),
            ("pomo_long_every", v.long_every), ("planning_enabled", int(v.planning_enabled)),
        ):
            self.set(key, str(value))

    @property
    def pomodoro_sound(self) -> Sound:
        key = self.get("pomo_sound_key", "classic")
        return Sound(
            enabled=self._flag("pomo_sound_enabled", True),
            key=key if key in SOUND_PRESETS else "classic",
            custom_path=self.get("pomo_sound_path", "") or None,
        )

    @pomodoro_sound.setter
    def pomodoro_sound(self, v: Sound) -> None:
        self.set("pomo_sound_enabled", "1" if v.enabled else "0")
        self.set("pomo_sound_key", v.key)
        self.set("pomo_sound_path", v.custom_path or "")

    @property
    def task_order(self) -> str:
        value = self.get("task_order", ORDER_SEQUENCE)
        return value if value in ORDER_MODES else ORDER_SEQUENCE

    @task_order.setter
    def task_order(self, value: str) -> None:
        self.set("task_order", value)

    # time bank ------------------------------------------------------------

    @property
    def bank_start(self) -> date:
        try:
            return date.fromisoformat(self.get("time_bank_start_date", ""))
        except ValueError:
            return date.today()

    @bank_start.setter
    def bank_start(self, value: date) -> None:
        self.set("time_bank_start_date", value.isoformat())

    # location -------------------------------------------------------------

    @property
    def location(self) -> Location:
        default = Location()
        try:
            return Location(
                name=self.get("location_name", default.name) or default.name,
                latitude=float(self.get("location_lat", str(default.latitude))),
                longitude=float(self.get("location_lon", str(default.longitude))),
                method=int(self.get("location_method", str(default.method))),
            )
        except ValueError:
            return default

    @location.setter
    def location(self, value: Location) -> None:
        self.set("location_name", value.name)
        self.set("location_lat", repr(value.latitude))
        self.set("location_lon", repr(value.longitude))
        self.set("location_method", str(value.method))

    # first run ------------------------------------------------------------

    @property
    def welcome_seen(self) -> bool:
        return self.get("welcome_seen", "") == "1"

    @welcome_seen.setter
    def welcome_seen(self, value: bool) -> None:
        self.set("welcome_seen", "1" if value else "")
