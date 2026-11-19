"""Backup and restore: everything comes back, nothing is touched before the file is checked."""

from __future__ import annotations

import json
import sqlite3
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path

from fuzzy_journey import backup
from fuzzy_journey.backup import BackupError, create_backup, read_backup_info, restore_backup
from fuzzy_journey.database import SCHEMA_VERSION, Database
from fuzzy_journey.models import Alarm, Sound, Task
from fuzzy_journey.principles import Principle
from fuzzy_journey.rhythm import DayKind

from .helpers import DbTestCase, activity

DAY = date(2026, 11, 2)


class BackupTestCase(DbTestCase):
    def setUp(self):
        super().setUp()
        self.dir = Path(self._tmp.name)
        self.sound_dir = self.dir / "restored-sounds"
        self.safety_dir = self.dir / "safety"

    def restore(self, db, source):
        return restore_backup(db, source, sound_dir=self.sound_dir, safety_dir=self.safety_dir)

    def fresh(self, name="other.sqlite3") -> Database:
        return Database(self.dir / name)

    def fill(self, db: Database, sound: Path | None = None) -> None:
        """Something of every kind the app stores."""
        db.settings.theme = "dark"
        db.settings.tray_icon = True
        db.settings.selftest_mode = "interval"
        db.settings.set_habit_start("porn", date(2026, 10, 1))
        db.save_task(Task("Write the chapter", 90, DAY))
        db.set_day_kind(DAY, DayKind.DISRUPTION, "a cold")
        db.set_habit_day(DAY, {"masturbation": 2, "porn": 1})
        db.save_principle(Principle("rules", "My own rule", "Be kind.\nSleep."))
        custom = Sound(True, "classic", str(sound)) if sound else Sound()
        db.save_alarm(Alarm("Stretch", "10:30", sound=custom))
        db.save_activity(activity("Gym", "17:00", "18:00", sound=custom))


class RoundTripTests(BackupTestCase):
    def test_everything_comes_back_in_a_fresh_install(self):
        sound = self.dir / "bell.wav"
        sound.write_bytes(b"RIFFfake")
        self.fill(self.db, sound)
        archive = self.dir / "b.zip"
        info = create_backup(self.db, archive, now=datetime(2026, 11, 19, 8, 30))
        self.assertEqual((info.schema, info.sounds, info.created), (SCHEMA_VERSION, 1, "2026-11-19T08:30:00"))

        other = self.fresh()
        result = self.restore(other, archive)
        self.assertEqual(result.info.sounds, 1)
        self.assertEqual(other.settings.theme, "dark")
        self.assertTrue(other.settings.tray_icon)
        self.assertEqual(other.settings.selftest_mode, "interval")
        self.assertEqual(other.settings.habit_start("porn"), date(2026, 10, 1))
        self.assertEqual([t.title for t in other.tasks_on(DAY, prayers=False)], ["Write the chapter"])
        self.assertEqual(other.day_kind(DAY), DayKind.DISRUPTION)
        self.assertEqual(other.habit_counts(DAY, DAY)[DAY], {"masturbation": 2, "porn": 1})
        self.assertIn("My own rule", [p.title for p in other.list_principles("rules")])
        self.assertEqual([a.title for a in other.list_alarms()], ["Stretch"])
        self.assertIn("Gym", [a.title for a in other.list_activities()])

    def test_personal_sounds_come_back_and_their_paths_follow_them(self):
        sound = self.dir / "bell.wav"
        sound.write_bytes(b"RIFFfake")
        self.fill(self.db, sound)
        create_backup(self.db, self.dir / "b.zip")
        sound.unlink()  # the original is gone, as on a new computer

        other = self.fresh()
        self.restore(other, self.dir / "b.zip")
        path = Path(other.list_alarms()[0].sound.custom_path)
        self.assertEqual(path.parent, self.sound_dir)
        self.assertEqual(path.read_bytes(), b"RIFFfake")
        gym = next(a for a in other.list_activities() if a.title == "Gym")
        self.assertEqual(Path(gym.sound.custom_path), path)

    def test_a_missing_sound_does_not_stop_the_backup(self):
        self.fill(self.db, self.dir / "never-existed.wav")
        info = create_backup(self.db, self.dir / "b.zip")
        self.assertEqual(info.sounds, 0)

    def test_restoring_replaces_what_is_there_and_keeps_a_copy_of_it(self):
        self.fill(self.db)
        create_backup(self.db, self.dir / "b.zip")
        other = self.fresh()
        other.settings.theme = "light"
        other.save_task(Task("Only on this computer", 30, DAY))
        result = self.restore(other, self.dir / "b.zip")
        self.assertEqual(other.settings.theme, "dark")
        self.assertNotIn("Only on this computer", [t.title for t in other.tasks_on(DAY, prayers=False)])
        # ...and the old data is in the safety copy
        with sqlite3.connect(result.safety_copy) as conn:
            titles = [r[0] for r in conn.execute("SELECT title FROM tasks WHERE kind='task'")]
        self.assertEqual(titles, ["Only on this computer"])

    def test_the_backup_has_no_prayer_time_csv_files(self):
        self.fill(self.db)
        create_backup(self.db, self.dir / "b.zip")
        names = zipfile.ZipFile(self.dir / "b.zip").namelist()
        self.assertFalse([n for n in names if n.lower().endswith(".csv")])
        self.assertEqual(sorted(n for n in names if "/" not in n), ["database.sqlite3", "manifest.json"])

    def test_the_app_keeps_working_after_a_restore(self):
        self.fill(self.db)
        create_backup(self.db, self.dir / "b.zip")
        other = self.fresh()
        self.restore(other, self.dir / "b.zip")
        other.save_task(Task("After", 15, DAY))
        other.settings.theme = "light"
        self.assertEqual(other.settings.theme, "light")
        with other.connection() as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")


class UpgradeTests(BackupTestCase):
    def forge(self, archive: Path, **changes) -> Path:
        """A copy of ``archive`` whose manifest says something else."""
        out = self.dir / "forged.zip"
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(out, "w") as dst:
            for item in src.infolist():
                data = src.read(item)
                if item.filename == "manifest.json":
                    manifest = json.loads(data)
                    manifest.update(changes)
                    data = json.dumps(manifest).encode()
                dst.writestr(item, data)
        return out

    def test_an_older_backup_is_upgraded_to_the_current_schema(self):
        self.fill(self.db)
        create_backup(self.db, self.dir / "b.zip")
        old = self.dir / "old.zip"
        with zipfile.ZipFile(self.dir / "b.zip") as src, zipfile.ZipFile(old, "w") as dst:
            for item in src.infolist():
                data = src.read(item)
                if item.filename == "database.sqlite3":
                    scratch = self.dir / "scratch.sqlite3"
                    scratch.write_bytes(data)
                    with sqlite3.connect(scratch) as conn:
                        conn.execute("DROP TABLE habit_days")  # a version-8 database has no habit table
                        conn.execute("PRAGMA user_version = 8")
                    data = scratch.read_bytes()
                if item.filename == "manifest.json":
                    data = json.dumps({**json.loads(data), "schema": 8}).encode()
                dst.writestr(item, data)
        other = self.fresh()
        self.restore(other, old)
        self.assertEqual(other.habit_counts(DAY, DAY), {})  # the table exists again, empty
        other.set_habit_day(DAY, {"porn": 1})
        with other.connection() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_a_backup_from_a_newer_version_is_refused_and_nothing_changes(self):
        self.fill(self.db)
        create_backup(self.db, self.dir / "b.zip")
        newer = self.forge(self.dir / "b.zip", schema=SCHEMA_VERSION + 1)
        other = self.fresh()
        other.settings.theme = "light"
        with self.assertRaisesRegex(BackupError, "newer version"):
            self.restore(other, newer)
        self.assertEqual(other.settings.theme, "light")
        self.assertFalse(self.safety_dir.exists())


class RefusalTests(BackupTestCase):
    def refuse(self, source: Path, pattern: str) -> None:
        other = self.fresh()
        other.settings.theme = "light"
        with self.assertRaisesRegex(BackupError, pattern):
            self.restore(other, source)
        self.assertEqual(other.settings.theme, "light")  # untouched
        with self.assertRaisesRegex(BackupError, pattern):
            read_backup_info(source)

    def test_a_file_that_is_not_a_zip(self):
        junk = self.dir / "junk.zip"
        junk.write_text("hello")
        self.refuse(junk, "not a readable backup")

    def test_a_zip_that_is_not_a_backup(self):
        other = self.dir / "other.zip"
        with zipfile.ZipFile(other, "w") as z:
            z.writestr("notes.txt", "x")
        self.refuse(other, "not a Fuzzy Journey backup")

    def test_a_manifest_for_another_app(self):
        z = self.dir / "z.zip"
        with zipfile.ZipFile(z, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"app_id": "com.example.Other", "schema": 1}))
            archive.writestr("database.sqlite3", b"")
        self.refuse(z, "not a Fuzzy Journey backup")

    def test_damaged_database_data(self):
        self.fill(self.db)
        create_backup(self.db, self.dir / "b.zip")
        broken = self.dir / "broken.zip"
        with zipfile.ZipFile(self.dir / "b.zip") as src, zipfile.ZipFile(broken, "w") as dst:
            for item in src.infolist():
                dst.writestr(item, b"this is not sqlite" * 50 if item.filename == "database.sqlite3" else src.read(item))
        other = self.fresh()
        with self.assertRaises(BackupError):
            self.restore(other, broken)

    def test_an_unsafe_sound_name_is_refused(self):
        sound = self.dir / "bell.wav"
        sound.write_bytes(b"x")
        self.fill(self.db, sound)
        create_backup(self.db, self.dir / "b.zip")
        evil = UpgradeTests.forge(self, self.dir / "b.zip", sounds={"../escape.wav": str(sound)})
        other = self.fresh()
        with self.assertRaisesRegex(BackupError, "unsafe"):
            self.restore(other, evil)
        self.assertFalse((self.dir / "escape.wav").exists())

    def test_a_destination_that_cannot_be_written(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        with self.assertRaises(BackupError):
            create_backup(self.db, blocker / "inside.zip")

    def test_no_half_written_backup_is_left_under_the_real_name(self):
        create_backup(self.db, self.dir / "ok.zip")
        self.assertTrue(zipfile.is_zipfile(self.dir / "ok.zip"))
        self.assertEqual([p.name for p in self.dir.glob("*.part")], [])


class MiscTests(unittest.TestCase):
    def test_default_filename(self):
        self.assertEqual(backup.default_filename(datetime(2026, 11, 19, 9, 0)), "fuzzy-journey-backup-2026-11-19.zip")


if __name__ == "__main__":
    unittest.main()
