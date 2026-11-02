from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, time, timedelta
from pathlib import Path

from fuzzy_journey.database import SCHEMA_VERSION, Database
from fuzzy_journey.models import Alarm, Location, PrayerAlarm, Sound
from fuzzy_journey.rhythm import DayKind
from tests.helpers import DbTestCase, activity


class DatabaseTests(DbTestCase):
    def test_alarm_round_trip(self):
        sound = Sound(True, "gentle", "/tmp/x.mp3")
        alarm_id = self.db.save_alarm(Alarm("Vitamins", "08:15", 31, sound=sound))
        (loaded,) = self.db.list_alarms()
        self.assertEqual((loaded.id, loaded.title, loaded.days_mask, loaded.sound), (alarm_id, "Vitamins", 31, sound))
        loaded.title = "Pills"
        self.db.save_alarm(loaded)
        self.assertEqual(self.db.list_alarms()[0].title, "Pills")
        self.db.delete_alarm(alarm_id)
        self.assertEqual(self.db.list_alarms(), [])

    def test_activity_round_trip_and_validation(self):
        self.db.save_activity(activity("Call", "10:00", "10:30", alarm_at_end=True))
        (loaded,) = self.db.list_activities()
        self.assertTrue(loaded.alarm_at_end)
        with self.assertRaises(ValueError):
            self.db.save_activity(activity("Bad", "25:00", "10:30"))

    def test_prayer_alarm_upsert(self):
        self.db.save_prayer_alarm(PrayerAlarm("Fajr", True, -10, Sound(True, "urgent")))
        self.db.save_prayer_alarm(PrayerAlarm("Fajr", True, 5, Sound(True, "urgent")))
        self.assertEqual(self.db.prayer_alarms()["Fajr"].offset_minutes, 5)

    def test_day_kinds_default_to_steady(self):
        day = date(2026, 5, 5)
        self.assertIs(self.db.day_kind(day), DayKind.STEADY)
        self.db.set_day_kind(day, DayKind.PUSH, "big launch")
        self.assertIs(self.db.day_kind(day), DayKind.PUSH)
        self.assertEqual(self.db.day_entries(day, day)[day].note, "big launch")

    def test_settings_have_sane_defaults_and_persist(self):
        s = self.db.settings
        self.assertEqual((s.theme, s.evening_start, s.flex), ("system", time(18, 0), timedelta(0)))
        self.assertEqual(s.location, Location())
        s.theme = "dark"
        s.evening_start = time(19, 30)
        s.flex = timedelta(minutes=45)
        s.location = Location("New York", 40.7, -74.0, 2)
        again = Database(self.db.path).settings
        self.assertEqual((again.theme, again.evening_start, again.flex), ("dark", time(19, 30), timedelta(minutes=45)))
        self.assertEqual(again.location.slug, "new-york")

    def test_invalid_stored_values_fall_back(self):
        self.db.settings.set("evening_work_start", "09:00")
        self.db.settings.set("location_lat", "nope")
        self.assertEqual(self.db.settings.evening_start, time(18, 0))
        self.assertEqual(self.db.settings.location, Location())

    def test_prune_history(self):
        with self.db.transaction() as conn:
            for i in range(10):
                conn.execute("INSERT INTO alarm_events(title, fired_at) VALUES (?, 'x')", (str(i),))
        self.db.prune_history(keep=3)
        self.assertEqual(len(self.db.recent_events(100)), 3)


class LegacyMigrationTests(unittest.TestCase):
    def test_a_1x_database_is_upgraded_in_place_without_losing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            conn = sqlite3.connect(path)
            # The earliest 1.x shape: no sound_key / custom_sound_path columns.
            conn.executescript(
                """
                CREATE TABLE alarms (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                  alarm_time TEXT NOT NULL, days_mask INTEGER NOT NULL DEFAULT 127, one_shot_date TEXT,
                  sound_enabled INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1,
                  last_fired_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                INSERT INTO alarms(title, alarm_time, created_at, updated_at) VALUES ('Old', '06:00', 'x', 'x');
                CREATE TABLE app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL);
                INSERT INTO app_settings VALUES ('time_bank_start_date', '2025-12-01');
                INSERT INTO app_settings VALUES ('theme', 'dark');
                """
            )
            conn.commit()
            conn.close()
            db = Database(path)
            (alarm,) = db.list_alarms()
            self.assertEqual((alarm.title, alarm.sound.key), ("Old", "classic"))
            self.assertEqual(db.settings.bank_start, date(2025, 12, 1))
            self.assertEqual(db.settings.theme, "dark")
            with db.connection() as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
