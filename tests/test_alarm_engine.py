from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fuzzy_journey.alarm_engine import fire_due_alarms, fire_due_schedule_events, next_occurrence, should_fire


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

    def test_recurring_alarm_can_only_fire_once_per_day(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "alarms.sqlite3"
            from fuzzy_journey.database import initialize, save_alarm
            initialize(db)
            save_alarm(title="Daily", alarm_time="07:30", days_mask=127, path=db)
            self.assertEqual(len(fire_due_alarms(datetime(2026, 11, 2, 7, 30), db_path=str(db))), 1)
            self.assertEqual(fire_due_alarms(datetime(2026, 11, 2, 7, 31), db_path=str(db)), [])

    def test_past_one_time_alarm_is_expired_without_ringing(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "alarms.sqlite3"
            from fuzzy_journey.database import initialize, save_alarm, list_alarms
            initialize(db)
            save_alarm(
                title="Missed",
                alarm_time="07:30",
                days_mask=0,
                one_shot_date="2026-11-01",
                path=db,
            )
            self.assertEqual(fire_due_alarms(datetime(2026, 11, 2, 7, 30), db_path=str(db)), [])
            self.assertEqual(list_alarms(db)[0]["enabled"], 0)

    def test_two_intensive_days_earn_one_day_and_day_off_can_create_debt(self):
        from datetime import date
        from fuzzy_journey.database import initialize, set_day_type, set_time_bank_start_date, day_balance
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "days.sqlite3"
            initialize(db)
            set_time_bank_start_date("2026-11-02", path=db)
            set_day_type("2026-11-02", "75", path=db)
            set_day_type("2026-11-03", "75", path=db)
            self.assertEqual(day_balance(db, as_of=date(2026, 11, 5))["balance"], 1.0)
            set_day_type("2026-11-04", "off", path=db)
            self.assertEqual(day_balance(db, as_of=date(2026, 11, 5))["balance"], 0.0)
            set_day_type("2026-11-05", "off", path=db)
            self.assertEqual(day_balance(db, as_of=date(2026, 11, 5))["balance"], -1.0)

    def test_future_days_and_days_before_baseline_do_not_affect_balance(self):
        from datetime import date
        from fuzzy_journey.database import initialize, set_day_type, set_time_bank_start_date, day_balance
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "days.sqlite3"
            initialize(db)
            set_time_bank_start_date("2026-11-02", path=db)
            set_day_type("2026-11-01", "off", path=db)  # before the baseline
            set_day_type("2026-11-03", "75", path=db)   # today
            set_day_type("2026-11-04", "off", path=db)  # future
            stats = day_balance(db, as_of=date(2026, 11, 3))
            self.assertEqual(stats["balance"], 0.5)
            self.assertEqual(stats["normal_days"], 1)
            self.assertEqual(stats["days_off"], 0)

    def test_custom_audio_paths_are_saved_for_all_alarm_types(self):
        from fuzzy_journey.database import (
            initialize, save_alarm, list_alarms, save_routine_block,
            list_routine_blocks, set_prayer_alarm, list_prayer_alarms,
        )
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "audio.sqlite3"
            initialize(db)
            custom_path = str(Path(temp) / "my-alarm.mp3")
            save_alarm(title="MP3 alarm", alarm_time="07:00", days_mask=127,
                       custom_sound_path=custom_path, path=db)
            self.assertEqual(list_alarms(db)[0]["custom_sound_path"], custom_path)
            save_routine_block(title="Wake up", category="wake", start_time="07:00",
                end_time="07:30", custom_sound_path=custom_path, path=db)
            self.assertEqual(list_routine_blocks(db)[0]["custom_sound_path"], custom_path)
            set_prayer_alarm("Fajr", True, custom_sound_path=custom_path, path=db)
            self.assertEqual(list_prayer_alarms(db)["Fajr"]["custom_sound_path"], custom_path)

    def test_work_block_progress_shows_productive_time_remaining(self):
        from fuzzy_journey.alarm_engine import routine_work_state

        work = {"id": 1, "category": "work", "start_time": "08:00", "end_time": "16:00",
                "days_mask": 127, "enabled": 1}
        call = {"id": 2, "category": "call", "start_time": "10:00", "end_time": "14:00",
                "days_mask": 127, "enabled": 1}
        paused = routine_work_state(work, [work, call], datetime(2026, 11, 2, 11, 0))
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["remaining"].total_seconds(), 6 * 3600)
        self.assertEqual(paused["pause_until"], datetime(2026, 11, 2, 14, 0))
        resumed = routine_work_state(work, [work, call], datetime(2026, 11, 2, 15, 0))
        self.assertEqual(resumed["status"], "in_progress")
        self.assertEqual(resumed["remaining"].total_seconds(), 5 * 3600)
        upcoming = routine_work_state(work, [work, call], datetime(2026, 11, 2, 7, 0))
        self.assertEqual(upcoming["status"], "upcoming")

    def test_work_block_pauses_during_other_activities(self):
        from datetime import date
        from fuzzy_journey.alarm_engine import effective_routine_end

        work = {"id": 1, "category": "work", "start_time": "08:00", "end_time": "16:00",
                "days_mask": 127, "enabled": 1}
        activity = {"id": 2, "category": "call", "start_time": "10:00", "end_time": "14:00",
                    "days_mask": 127, "enabled": 1}
        end = effective_routine_end(work, [work, activity], date(2026, 11, 2))
        self.assertEqual(end, datetime(2026, 11, 2, 20, 0))

    def test_work_block_end_alarm_uses_adjusted_finish(self):
        from fuzzy_journey.database import initialize, save_routine_block
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "routines.sqlite3"
            initialize(db)
            save_routine_block(title="Work", category="work", start_time="08:00", end_time="16:00",
                days_mask=127, end_alarm_enabled=True, path=db)
            save_routine_block(title="Call", category="call", start_time="10:00", end_time="14:00",
                days_mask=127, path=db)
            events = fire_due_schedule_events(datetime(2026, 11, 2, 20, 0), db_path=str(db))
            self.assertEqual([event["title"] for event in events], ["Work finished"])

    def test_time_bank_start_date_resets_initial_balance(self):
        from datetime import date
        from fuzzy_journey.database import initialize, set_day_type, set_time_bank_start_date, day_balance
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "days.sqlite3"
            initialize(db)
            set_day_type("2026-11-01", "off", path=db)
            set_day_type("2026-11-02", "75", path=db)
            set_day_type("2026-11-03", "75", path=db)
            set_time_bank_start_date("2026-11-02", path=db)
            stats = day_balance(db, as_of=date(2026, 11, 3))
            self.assertEqual(stats["balance"], 1.0)
            self.assertEqual(stats["days_off"], 0)

    def test_routine_alarm_fires_once_per_day(self):
        from fuzzy_journey.database import initialize, save_routine_block
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "routines.sqlite3"
            initialize(db)
            save_routine_block(title="Work starts", category="work", start_time="08:00",
                end_time="12:00", days_mask=127, alarm_enabled=True, path=db)
            first = fire_due_schedule_events(datetime(2026, 11, 2, 8, 0), db_path=str(db))
            second = fire_due_schedule_events(datetime(2026, 11, 2, 8, 1), db_path=str(db))
            self.assertEqual([event["title"] for event in first], ["Work starts"])
            self.assertEqual(second, [])

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
