"""The habit calendar: figures appear only after the days have passed, and the start date never wipes a day."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from fuzzy_journey.habits import HabitStat, clamp, days_left, days_passed, since_start, window_stat

from .helpers import DbTestCase

START = date(2026, 11, 1)


def counts(**by_offset):
    return {START + timedelta(days=int(k[1:])): v for k, v in by_offset.items()}


class StatTests(unittest.TestCase):
    def test_today_is_not_a_finished_day(self):
        self.assertEqual(days_passed(START, START), 0)
        self.assertEqual(days_passed(START, START + timedelta(days=7)), 7)
        self.assertEqual(days_passed(START + timedelta(days=3), START), 0)  # a start in the future

    def test_no_weekly_figure_until_seven_days_have_passed(self):
        for passed in range(7):
            self.assertIsNone(window_stat({}, START, START + timedelta(days=passed), 7), passed)
        self.assertIsNotNone(window_stat({}, START, START + timedelta(days=7), 7))
        self.assertEqual(days_left(START, START + timedelta(days=4), 7), 3)
        self.assertEqual(days_left(START, START + timedelta(days=9), 7), 0)

    def test_no_monthly_figure_until_thirty_days_have_passed(self):
        self.assertIsNone(window_stat({}, START, START + timedelta(days=29), 30))
        self.assertIsNotNone(window_stat({}, START, START + timedelta(days=30), 30))

    def test_the_week_is_the_last_seven_finished_days(self):
        today = START + timedelta(days=10)
        marks = {today - timedelta(days=1): 2, today - timedelta(days=7): 1,
                 today - timedelta(days=8): 5,  # outside the week
                 today: 9}  # today is not finished: not counted
        stat = window_stat(marks, START, today, 7)
        self.assertEqual((stat.days, stat.total, stat.days_with, stat.clean_days), (7, 3, 2, 5))
        self.assertAlmostEqual(stat.average, 3 / 7)

    def test_since_start_covers_every_finished_day(self):
        self.assertIsNone(since_start({}, START, START))
        stat = since_start(counts(d0=1, d2=3), START, START + timedelta(days=4))
        self.assertEqual((stat.days, stat.total, stat.days_with), (4, 4, 2))

    def test_marks_before_the_start_are_ignored_by_the_figures_not_deleted(self):
        marks = {START - timedelta(days=3): 4, START + timedelta(days=1): 1}
        stat = since_start(marks, START, START + timedelta(days=8))
        self.assertEqual((stat.total, stat.days), (1, 8))

    def test_an_empty_run_has_no_average(self):
        self.assertEqual(HabitStat(0, 0, 0).average, 0.0)
        self.assertEqual(clamp(-3), 0)
        self.assertEqual(clamp(500), 99)


class StorageTests(DbTestCase):
    def test_a_day_is_saved_per_habit_and_cleared_when_nothing_happened(self):
        day = date(2026, 11, 2)
        self.db.set_habit_day(day, {"masturbation": 2, "porn": 0})
        self.assertEqual(self.db.habit_counts(day, day), {day: {"masturbation": 2, "porn": 0}})
        self.db.set_habit_day(day, {"masturbation": 0, "porn": 1})
        self.assertEqual(self.db.habit_counts(day, day)[day], {"masturbation": 0, "porn": 1})
        self.db.set_habit_day(day, {})
        self.assertEqual(self.db.habit_counts(day, day), {})

    def test_changing_a_start_date_keeps_every_day(self):
        day = date(2026, 11, 2)
        self.db.set_habit_day(day, {"porn": 3})
        self.db.settings.set_habit_start("porn", date(2026, 11, 20))
        self.assertEqual(self.db.habit_counts(day, day)[day]["porn"], 3)

    def test_each_habit_has_its_own_start_and_the_first_one_is_remembered(self):
        s = self.db.settings
        first = s.habit_start("porn")
        self.assertEqual(s.habit_start("porn"), first)  # not a moving target
        s.set_habit_start("masturbation", date(2026, 1, 1))
        self.assertEqual(s.habit_start("masturbation"), date(2026, 1, 1))
        self.assertEqual(s.habit_start("porn"), first)

    def test_the_calendar_can_be_turned_off_without_losing_data(self):
        day = date(2026, 11, 2)
        self.db.set_habit_day(day, {"porn": 1})
        self.assertTrue(self.db.settings.habit_calendar)
        self.db.settings.habit_calendar = False
        self.assertFalse(self.db.settings.habit_calendar)
        self.assertEqual(self.db.habit_counts(day, day)[day]["porn"], 1)


if __name__ == "__main__":
    unittest.main()
