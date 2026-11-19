"""Disruption days (25% work, or offline), prayers as tasks, and the schema 8 upgrade."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

from fuzzy_journey import alarms
from fuzzy_journey.database import Database
from fuzzy_journey.principles import FIRST_COMPUTER_RULE, SECTION_RULES
from fuzzy_journey.rhythm import DISRUPTION_SHARE, DayKind, plan_day, summarize_bank

from .helpers import DbTestCase, activity

DAY = date(2026, 11, 2)
FAJR, ISHA = time(5, 30), time(18, 45)


def plan(kind, **kw):
    return plan_day(DAY, kind, fajr=FAJR, isha=ISHA, next_fajr=time(5, 31), **kw)


class RhythmTests(unittest.TestCase):
    def test_a_disruption_day_keeps_a_quarter_of_a_normal_day(self):
        steady, quarter = plan(DayKind.STEADY), plan(DayKind.DISRUPTION)
        self.assertEqual(DISRUPTION_SHARE, 0.25)
        self.assertAlmostEqual(quarter.target / steady.target, 0.5, delta=0.01)  # 25% vs 50% of the day
        self.assertEqual(quarter.morning.start, datetime.combine(DAY, FAJR))
        self.assertIsNone(quarter.evening)
        self.assertEqual(quarter.bedtime, datetime.combine(DAY, ISHA))

    def test_an_offline_day_has_no_work_at_all(self):
        offline = plan(DayKind.OFFLINE)
        self.assertEqual(offline.target, timedelta(0))
        self.assertEqual(offline.blocks, ())

    def test_neither_takes_evening_or_night_work(self):
        for kind in (DayKind.DISRUPTION, DayKind.OFFLINE):
            hard = plan(kind, overtime=timedelta(hours=2), evening_extra=timedelta(hours=1))
            self.assertIsNone(hard.overtime)
            self.assertIsNone(hard.evening)
            self.assertEqual(hard.bedtime, datetime.combine(DAY, ISHA))
        self.assertIsNotNone(plan(DayKind.STEADY, overtime=timedelta(hours=1)).overtime)

    def test_they_are_neutral_for_the_bank(self):
        days = [DAY + timedelta(days=i) for i in range(4)]
        kinds = dict(zip(days, (DayKind.DISRUPTION, DayKind.OFFLINE, DayKind.STEADY, DayKind.PUSH), strict=True))
        bank = summarize_bank(kinds, days[0], days[-1])
        self.assertEqual((bank.push_days, bank.rest_days, bank.balance), (1, 0, 0.5))

    def test_kind_flags(self):
        self.assertTrue(DayKind.OFFLINE.no_work and DayKind.REST.no_work)
        self.assertFalse(DayKind.DISRUPTION.no_work)
        self.assertTrue(DayKind.DISRUPTION.is_disruption and not DayKind.REST.is_disruption)
        self.assertFalse(DayKind.REST.allows_extra_work or DayKind.DISRUPTION.allows_extra_work)


class StorageTests(DbTestCase):
    def kind(self):
        return self.db.day_kind(DAY)

    def test_each_kind_round_trips(self):
        for kind in (DayKind.DISRUPTION, DayKind.OFFLINE, DayKind.PUSH, DayKind.REST, DayKind.STEADY):
            self.db.set_day_kind(DAY, kind, "note")
            self.assertEqual(self.kind(), kind)
            self.assertEqual(self.db.day_entries(DAY, DAY)[DAY].note, "note")

    def test_going_back_to_normal_clears_the_disruption(self):
        self.db.set_day_kind(DAY, DayKind.DISRUPTION)
        self.db.set_day_kind(DAY, DayKind.STEADY)
        self.assertEqual(self.kind(), DayKind.STEADY)

    def test_a_disruption_clears_night_and_evening_work_and_recovered_start(self):
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(9, 0))
        self.db.set_day_overtime(DAY, 60)
        self.db.set_day_evening(DAY, 60)
        self.db.set_day_kind(DAY, DayKind.DISRUPTION)
        entry = self.db.day_entries(DAY, DAY)[DAY]
        self.assertEqual((entry.kind, entry.overtime, entry.evening, entry.start), (DayKind.DISRUPTION, 0, 0, None))

    def test_choosing_recovered_replaces_a_disruption(self):
        self.db.set_day_kind(DAY, DayKind.OFFLINE)
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(9, 0))
        self.assertEqual(self.kind(), DayKind.RECOVERED)


class AlarmTests(unittest.TestCase):
    def test_work_activities_are_silent_on_an_offline_day_but_the_gym_still_rings(self):
        from fuzzy_journey.prayer_times import PrayerDay

        shift = activity("Shift", "09:00", "12:00", "work", alarm_at_start=True)
        gym = activity("Gym", "17:00", "18:00", alarm_at_start=True)
        shift.id, gym.id = 1, 2
        prayer = PrayerDay(DAY, {"Fajr": FAJR, "Isha": ISHA})
        for kind, expected in ((DayKind.STEADY, {"Shift", "Gym"}), (DayKind.OFFLINE, {"Gym"}),
                               (DayKind.DISRUPTION, {"Shift", "Gym"})):
            events = alarms.scheduled_events(DAY, prayer_day=prayer, prayer_alarms={}, activities=[shift, gym],
                                             kinds={DAY: kind})
            self.assertEqual({e.title for e in events}, expected, kind)


class PrayerTaskTests(DbTestCase):
    def test_prayers_can_be_turned_off_as_tasks_and_come_back(self):
        self.assertTrue(self.db.settings.show_prayers)
        self.db.ensure_prayer_tasks(DAY)
        self.assertEqual(len(self.db.tasks_on(DAY)), 5)
        self.db.settings.show_prayers = False
        self.assertEqual(self.db.tasks_on(DAY), [])
        self.assertEqual(self.db.unset_tasks_before(DAY + timedelta(days=1)), [])
        self.db.ensure_prayer_tasks(DAY + timedelta(days=1))
        self.assertEqual(self.db.tasks_on(DAY + timedelta(days=1)), [])
        self.db.settings.show_prayers = True
        self.assertEqual(len(self.db.tasks_on(DAY)), 5)  # nothing was deleted
        self.assertEqual(len(self.db.unset_tasks_before(DAY + timedelta(days=1))), 5)


class UpgradeTests(DbTestCase):
    def _reopen_as_v7(self):
        with self.db.connection() as conn:
            conn.execute("PRAGMA user_version = 7")
        return Database(self.db.path)

    def test_an_untouched_computer_rule_gains_the_off_outside_work_line(self):
        rule = next(r for r in self.db.list_principles(SECTION_RULES) if r.title == "Computer-use boundary")
        rule.body = FIRST_COMPUTER_RULE
        self.db.save_principle(rule)
        again = next(r for r in self._reopen_as_v7().list_principles(SECTION_RULES) if r.id == rule.id)
        self.assertIn("Outside work time the PC must be off", again.body)

    def test_an_edited_computer_rule_is_never_touched(self):
        rule = next(r for r in self.db.list_principles(SECTION_RULES) if r.title == "Computer-use boundary")
        rule.body = FIRST_COMPUTER_RULE + "\nMy own extra line."
        self.db.save_principle(rule)
        again = next(r for r in self._reopen_as_v7().list_principles(SECTION_RULES) if r.id == rule.id)
        self.assertEqual(again.body, rule.body)


if __name__ == "__main__":
    unittest.main()
