from __future__ import annotations

import unittest
from datetime import date, datetime, time

from fuzzy_journey import alarms
from fuzzy_journey.models import Alarm, PrayerAlarm
from fuzzy_journey.prayer_times import PrayerDay
from fuzzy_journey.rhythm import DayKind
from tests.helpers import DbTestCase, activity


def make(**kw) -> Alarm:
    return Alarm(**{"title": "Morning", "time": "07:30", **kw})


class RuleTests(unittest.TestCase):
    def test_recurring_alarm_fires_inside_grace_window(self):
        a = make(id=1)
        self.assertTrue(alarms.should_fire(a, datetime(2026, 11, 2, 7, 34)))
        self.assertFalse(alarms.should_fire(a, datetime(2026, 11, 2, 7, 36)))
        self.assertFalse(alarms.should_fire(a, datetime(2026, 11, 2, 7, 29)))

    def test_only_selected_weekdays(self):
        monday = make(days_mask=1)
        self.assertTrue(alarms.should_fire(monday, datetime(2026, 11, 2, 7, 30)))
        self.assertFalse(alarms.should_fire(monday, datetime(2026, 11, 3, 7, 30)))

    def test_one_shot_and_next_occurrence(self):
        a = make(days_mask=0, one_shot_date="2026-11-04")
        self.assertEqual(alarms.next_occurrence(a, datetime(2026, 11, 2, 12)), datetime(2026, 11, 4, 7, 30))
        self.assertIsNone(alarms.next_occurrence(a, datetime(2026, 11, 5, 12)))

    def test_disabled_never_fires(self):
        self.assertFalse(alarms.should_fire(make(enabled=False), datetime(2026, 11, 2, 7, 30)))
        self.assertIsNone(alarms.next_occurrence(make(enabled=False), datetime(2026, 11, 2)))


class ClaimTests(DbTestCase):
    def test_recurring_alarm_rings_once_per_day(self):
        self.db.save_alarm(make())
        self.assertEqual(len(alarms.claim_due_reminders(self.db, datetime(2026, 11, 2, 7, 30))), 1)
        self.assertEqual(alarms.claim_due_reminders(self.db, datetime(2026, 11, 2, 7, 31)), [])
        self.assertEqual(len(alarms.claim_due_reminders(self.db, datetime(2026, 11, 3, 7, 30))), 1)

    def test_one_shot_is_disabled_when_claimed(self):
        self.db.save_alarm(make(days_mask=0, one_shot_date="2026-11-02"))
        self.assertEqual(len(alarms.claim_due_reminders(self.db, datetime(2026, 11, 2, 7, 30))), 1)
        self.assertFalse(self.db.list_alarms()[0].enabled)

    def test_past_one_shot_expires_without_ringing(self):
        self.db.save_alarm(make(days_mask=0, one_shot_date="2026-11-01"))
        self.assertEqual(alarms.claim_due_reminders(self.db, datetime(2026, 11, 2, 7, 30)), [])
        self.assertFalse(self.db.list_alarms()[0].enabled)

    def test_events_are_logged(self):
        self.db.save_alarm(make())
        alarms.claim_due_reminders(self.db, datetime(2026, 11, 2, 7, 30))
        self.assertEqual(self.db.recent_events()[0].title, "Morning")


class ScheduledEventTests(DbTestCase):
    day = date(2026, 11, 2)
    prayer = PrayerDay(day, {"Fajr": time(5, 42), "Dhuhr": time(12, 10), "Isha": time(18, 20)})

    def events(self, acts=(), prayers=None, kinds=None):
        return alarms.scheduled_events(
            self.day, prayer_day=self.prayer, prayer_alarms=prayers or {}, activities=acts,
            kinds=kinds or {},
        )

    def test_prayer_alarm_with_offset(self):
        (event,) = self.events(prayers={"Dhuhr": PrayerAlarm("Dhuhr", True, offset_minutes=-10)})
        self.assertEqual(event.due, datetime(2026, 11, 2, 12, 0))
        self.assertEqual(event.title, "Dhuhr prayer")

    def test_disabled_prayer_alarm_is_silent(self):
        self.assertEqual(self.events(prayers={"Dhuhr": PrayerAlarm("Dhuhr", False)}), [])

    def test_activity_start_and_end_alarms(self):
        act = activity("Gym", "17:00", "18:00", alarm_at_start=True, alarm_at_end=True, id=3)
        titles = [e.title for e in self.events([act])]
        self.assertEqual(titles, ["Gym", "Gym finished"])

    def test_rest_day_silences_work_activities_only(self):
        work = activity("Shift", "09:00", "17:00", "work", alarm_at_start=True, id=1)
        gym = activity("Gym", "17:00", "18:00", alarm_at_start=True, id=2)
        events = self.events([work, gym], kinds={self.day: DayKind.REST})
        self.assertEqual([e.title for e in events], ["Gym"])

    def test_midnight_crossing_block_ends_today(self):
        act = activity("Late", "23:00", "01:00", alarm_at_end=True, id=4)
        (event,) = self.events([act])
        self.assertEqual(event.due, datetime(2026, 11, 2, 1, 0))

    def test_claim_once_per_day_and_respects_grace(self):
        act = activity("Gym", "17:00", "18:00", alarm_at_start=True, id=2)
        events = self.events([act])
        self.assertEqual(len(alarms.claim_due_events(self.db, events, datetime(2026, 11, 2, 17, 2))), 1)
        self.assertEqual(alarms.claim_due_events(self.db, events, datetime(2026, 11, 2, 17, 3)), [])
        self.assertEqual(alarms.claim_due_events(self.db, events, datetime(2026, 11, 2, 17, 9)), [])


if __name__ == "__main__":
    unittest.main()
