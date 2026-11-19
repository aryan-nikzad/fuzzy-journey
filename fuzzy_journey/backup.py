"""Back up everything the app stores, and restore it later. No GTK.

A backup is one zip file:

``manifest.json``
    What it is: the app, its version, the schema it was made with, and when.
``database.sqlite3``
    A consistent snapshot of the whole database: settings, reminders, routine, tasks, days, the habit
    calendar, rules, the recovery plan, the bank, pomodoro state.
``custom-sounds/<file>``
    Every personal sound a reminder, the routine, a prayer or the pomodoro uses, so they come back too.

The prayer-time CSV files are deliberately **not** part of it. They are not app state: they are data you
can fetch again or copy in, and they already work on their own wherever they are placed.

Restoring is careful. The file is checked before anything is touched, a copy of what you have now is kept
first, an older backup is upgraded to the current schema, and a backup from a *newer* version is refused
rather than half-understood.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from .database import SCHEMA_VERSION, Database
from .meta import APP_ID, APP_NAME, VERSION
from .paths import BACKUP_DIR, CUSTOM_SOUND_DIR

MANIFEST = "manifest.json"
DATABASE = "database.sqlite3"
SOUND_DIR = "custom-sounds"

#: Where a personal sound path is stored: (table, column, optional extra condition).
SOUND_COLUMNS = (
    ("alarms", "custom_sound_path"),
    ("routine_blocks", "custom_sound_path"),
    ("prayer_alarm_settings", "custom_sound_path"),
)
SOUND_SETTING = "pomo_sound_path"


class BackupError(Exception):
    """A backup that cannot be made or used. The message says why, in words fit to show."""


@dataclass(frozen=True)
class BackupInfo:
    app_version: str
    schema: int
    created: str
    sounds: int

    @property
    def created_text(self) -> str:
        try:
            return datetime.fromisoformat(self.created).strftime("%d %b %Y, %H:%M")
        except ValueError:
            return self.created


@dataclass(frozen=True)
class RestoreResult:
    info: BackupInfo
    safety_copy: Path | None  # a copy of the data that was replaced


def default_filename(now: datetime | None = None) -> str:
    return f"fuzzy-journey-backup-{(now or datetime.now()):%Y-%m-%d}.zip"


# --------------------------------------------------------------------------
# Making a backup
# --------------------------------------------------------------------------


def _sound_paths(conn: sqlite3.Connection) -> list[str]:
    found: list[str] = []
    for table, column in SOUND_COLUMNS:
        found += [r[0] for r in conn.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL")]
    found += [r[0] for r in conn.execute(
        "SELECT setting_value FROM app_settings WHERE setting_key=?", (SOUND_SETTING,))]
    return sorted({p for p in found if p})


def create_backup(db: Database, destination: Path, *, now: datetime | None = None) -> BackupInfo:
    """Write everything to ``destination`` (a .zip). Raises :class:`BackupError` if it cannot."""
    now = now or datetime.now()
    destination = Path(destination)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / DATABASE
            source = sqlite3.connect(db.path, timeout=10)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)  # consistent even while the alarm service is writing
                target.execute("PRAGMA journal_mode = DELETE")
                with target:
                    paths = _sound_paths(target)
            finally:
                target.close()
                source.close()

            sounds: dict[str, str] = {}  # name in the zip -> the path it had
            files: dict[str, Path] = {}
            for index, original in enumerate(paths):
                path = Path(original)
                if not path.is_file():
                    continue  # a sound that was already deleted cannot be backed up
                name = path.name if path.name not in files else f"{index}-{path.name}"
                files[name], sounds[name] = path, original

            manifest = {
                "app": APP_NAME, "app_id": APP_ID, "app_version": VERSION, "schema": SCHEMA_VERSION,
                "created": now.isoformat(timespec="seconds"), "database": DATABASE, "sounds": sounds,
                "not_included": "prayer-time CSV files",
            }
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_suffix(destination.suffix + ".part")
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
                archive.write(snapshot, DATABASE)
                for name, path in files.items():
                    archive.write(path, f"{SOUND_DIR}/{name}")
            partial.replace(destination)  # never leave half a backup under the real name
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as error:
        raise BackupError(f"The backup could not be written: {error}") from error
    return BackupInfo(VERSION, SCHEMA_VERSION, manifest["created"], len(files))


# --------------------------------------------------------------------------
# Reading and restoring one
# --------------------------------------------------------------------------


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(archive.read(MANIFEST))
    except (KeyError, ValueError) as error:
        raise BackupError("This is not a Fuzzy Journey backup (no manifest).") from error
    if manifest.get("app_id") != APP_ID or DATABASE not in archive.namelist():
        raise BackupError("This is not a Fuzzy Journey backup.")
    schema = manifest.get("schema")
    if not isinstance(schema, int) or schema < 1:
        raise BackupError("This backup does not say which version of the data it holds.")
    if schema > SCHEMA_VERSION:
        raise BackupError(
            f"This backup was made by a newer version of {APP_NAME} (data version {schema}, this one "
            f"understands up to {SCHEMA_VERSION}). Update the app, then restore it."
        )
    return manifest


def _info(manifest: dict) -> BackupInfo:
    return BackupInfo(str(manifest.get("app_version", "?")), manifest["schema"], str(manifest.get("created", "")),
                      len(manifest.get("sounds", {})))


def read_backup_info(source: Path) -> BackupInfo:
    """What a backup file is, without changing anything. Raises :class:`BackupError` if it is not usable."""
    try:
        with zipfile.ZipFile(source) as archive:
            return _info(_read_manifest(archive))
    except (OSError, zipfile.BadZipFile) as error:
        raise BackupError("This file is not a readable backup (it is not a valid zip file).") from error


def restore_backup(
    db: Database, source: Path, *, sound_dir: Path = CUSTOM_SOUND_DIR, safety_dir: Path = BACKUP_DIR,
    now: datetime | None = None,
) -> RestoreResult:
    """Replace everything the app stores with the contents of ``source``.

    Nothing is changed until the backup has been checked. A copy of the current data is kept first, in
    ``safety_dir``. Personal sounds are copied into ``sound_dir`` and their paths pointed at the copies.
    """
    now = now or datetime.now()
    read_backup_info(source)  # refuse anything that is not a usable backup before touching a thing
    try:
        with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory() as tmp:
            manifest = _read_manifest(archive)
            sounds: dict[str, str] = manifest.get("sounds", {})
            staged = Path(tmp) / DATABASE
            with archive.open(DATABASE) as stream, open(staged, "wb") as out:
                shutil.copyfileobj(stream, out)
            _check_database(staged, manifest["schema"])

            # 1. keep what is there now
            safety_dir.mkdir(parents=True, exist_ok=True)
            safety = safety_dir / f"before-restore-{now:%Y%m%d-%H%M%S}.sqlite3"
            live = sqlite3.connect(db.path, timeout=10)
            keep = sqlite3.connect(safety)
            try:
                live.backup(keep)
            finally:
                keep.close()
                live.close()

            # 2. bring the sounds back and point the staged database at the copies
            sound_dir.mkdir(parents=True, exist_ok=True)
            moved: dict[str, str] = {}
            for name, original in sounds.items():
                member = PurePosixPath(name)
                if member.name != name or name in ("", ".", ".."):
                    raise BackupError("This backup contains an unsafe file name and was not restored.")
                try:
                    data = archive.read(f"{SOUND_DIR}/{name}")
                except KeyError:
                    continue
                target = sound_dir / name
                if not target.exists():
                    target.write_bytes(data)
                moved[original] = str(target)
            _repoint_sounds(staged, moved)

            # 3. copy it over the live database (the alarm service may be reading it right now)
            source_db = sqlite3.connect(staged)
            live = sqlite3.connect(db.path, timeout=30)
            try:
                source_db.backup(live)
            finally:
                live.close()
                source_db.close()
        db._migrate()  # an older backup is brought up to the current schema
        return RestoreResult(_info(manifest), safety)
    except BackupError:
        raise
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as error:
        raise BackupError(f"The backup could not be restored: {error}") from error


def _check_database(path: Path, schema: int) -> None:
    try:
        conn = sqlite3.connect(path)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("The data inside this backup is damaged.")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "app_settings" not in tables:
                raise BackupError("This backup does not contain Fuzzy Journey data.")
            if conn.execute("PRAGMA user_version").fetchone()[0] != schema:
                raise BackupError("This backup's data version does not match its manifest.")
        finally:
            conn.close()
    except sqlite3.DatabaseError as error:
        raise BackupError("The data inside this backup is not a readable database.") from error


def _repoint_sounds(path: Path, moved: dict[str, str]) -> None:
    conn = sqlite3.connect(path)
    try:
        with conn:
            for original, new in moved.items():
                for table, column in SOUND_COLUMNS:
                    conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, original))
                conn.execute("UPDATE app_settings SET setting_value=? WHERE setting_key=? AND setting_value=?",
                             (new, SOUND_SETTING, original))
    finally:
        conn.close()
