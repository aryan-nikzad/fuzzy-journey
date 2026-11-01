from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fuzzy_journey.alarm_engine import fire_due_alarms, next_occurrence, should_fire


class AlarmEngineTests(unittest.TestCase):
    def alarm(self, **overrides):
        base = {
            "id": 1,
            "title": "Morning",
            "alarm_time": "07:30",
            "days_mask": 127,
            "one_shot_date": None,
            "sound_enabled": 1,
            "enabled": 1,
            "last_fired_date": None,
        }
        return {**base, **overrides}

    def test_recurring_alarm_fires_inside_grace_window(self):
        alarm = self.alarm()
        self.assertTrue(should_fire(alarm, datetime(2026, 11, 2, 7, 34)))
        self.assertFalse(should_fire(alarm, datetime(2026, 11, 2, 7, 36)))

    def test_alarm_only_fires_on_selected_weekdays(self):
        monday_only = self.alarm(days_mask=1)
        self.assertTrue(should_fire(monday_only, datetime(2026, 11, 2, 7, 30)))
        self.assertFalse(should_fire(monday_only, datetime(2026, 11, 3, 7, 30)))

    def test_one_shot_date_and_next_occurrence(self):
        alarm = self.alarm(days_mask=0, one_shot_date="2026-11-04")
        now = datetime(2026, 11, 2, 12, 0)
        self.assertEqual(next_occurrence(alarm, now), datetime(2026, 11, 4, 7, 30))
        self.assertFalse(should_fire(alarm, datetime(2026, 11, 3, 7, 30)))
        self.assertTrue(should_fire(alarm, datetime(2026, 11, 4, 7, 30)))

    def test_firing_is_persisted_and_one_shot_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "alarms.sqlite3"
            from fuzzy_journey.database import initialize, save_alarm, list_alarms
            initialize(db)
            alarm_id = save_alarm(
                title="One time",
                alarm_time="07:30",
                days_mask=0,
                one_shot_date="2026-11-02",
                path=db,
            )
            due = fire_due_alarms(datetime(2026, 11, 2, 7, 31), db_path=str(db))
            self.assertEqual([item["id"] for item in due], [alarm_id])
            self.assertEqual(fire_due_alarms(datetime(2026, 11, 2, 7, 32), db_path=str(db)), [])
            saved = list_alarms(db)[0]
            self.assertEqual(saved["enabled"], 0)
            self.assertEqual(saved["last_fired_date"], "2026-11-02")


if __name__ == "__main__":
    unittest.main()
