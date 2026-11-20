"""The habit calendar: figures appear only after the days have passed, and the start date never wipes a day."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from fuzzy_journey.database import Database
from fuzzy_journey.habits import (
    BUILD,
    MAX_HABITS,
    MAX_NAME,
    QUIT,
    Habit,
    HabitStat,
    check_habit,
    clamp,
    days_left,
    days_passed,
    describe,
    since_start,
    window_stat,
)

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


class WordingTests(unittest.TestCase):
    def test_a_quit_habit_speaks_of_days_without_and_a_build_habit_of_days_missed(self):
        stat = HabitStat(7, 6, 5)
        self.assertEqual(describe(stat, 0, QUIT), "0.86 a day · 6 times · happened on 5 of 7 days · 2 without")
        self.assertEqual(describe(stat, 0, BUILD), "0.86 a day · 6 times · done on 5 of 7 days · 2 missed")

    def test_a_figure_that_is_not_ready_says_how_long_to_wait(self):
        self.assertEqual(describe(None, 1, QUIT), "Shown after 1 more day have passed.")
        self.assertEqual(describe(None, 4, BUILD), "Shown after 4 more days have passed.")

    def test_checking_a_habit(self):
        self.assertIsNone(check_habit("Reading", BUILD))
        self.assertIsNotNone(check_habit("  ", BUILD))
        self.assertIsNotNone(check_habit("x" * (MAX_NAME + 1), QUIT))
        self.assertIsNotNone(check_habit("Reading", "maybe"))


class StorageTests(DbTestCase):
    def habit(self, name="Reading", kind=BUILD, start=START):
        habit = Habit(name, kind, start)
        self.db.save_habit(habit)
        return habit

    def test_a_new_install_has_no_habits(self):
        self.assertEqual(self.db.list_habits(), [])

    def test_habits_can_be_added_renamed_and_keep_their_order(self):
        a, b = self.habit("Reading"), self.habit("Smoking", QUIT)
        self.assertEqual([h.name for h in self.db.list_habits()], ["Reading", "Smoking"])
        b.name, b.kind = "  Cigarettes ", QUIT
        self.db.save_habit(b)
        listed = self.db.list_habits()
        self.assertEqual([(h.id, h.name, h.kind) for h in listed], [(a.id, "Reading", BUILD), (b.id, "Cigarettes", QUIT)])

    def test_each_habit_has_its_own_marks_and_start(self):
        a = self.habit("Reading", BUILD, date(2026, 10, 1))
        b = self.habit("Smoking", QUIT, date(2026, 11, 1))
        day = date(2026, 11, 2)
        self.db.set_habit_mark(a.id, day, 3)
        self.db.set_habit_mark(b.id, day, 1)
        self.assertEqual(self.db.habit_marks(day, day)[day], {a.id: 3, b.id: 1})
        self.assertEqual(self.db.habit_counts(a.id, day, day), {day: 3})
        self.db.set_habit_mark(a.id, day, 0)
        self.assertEqual(self.db.habit_marks(day, day)[day], {b.id: 1})
        self.db.set_habit_mark(b.id, day, 0)
        self.assertEqual(self.db.habit_marks(day, day), {})
        self.assertEqual([h.start for h in self.db.list_habits()], [date(2026, 10, 1), date(2026, 11, 1)])

    def test_changing_a_start_date_keeps_every_marked_day(self):
        habit = self.habit()
        day = date(2026, 11, 2)
        self.db.set_habit_mark(habit.id, day, 2)
        habit.start = date(2026, 11, 20)
        self.db.save_habit(habit)
        self.assertEqual(self.db.habit_counts(habit.id, day, day), {day: 2})

    def test_deleting_a_habit_removes_its_marks_and_only_its_marks(self):
        a, b = self.habit("Reading"), self.habit("Walking")
        day = date(2026, 11, 2)
        self.db.set_habit_mark(a.id, day, 1)
        self.db.set_habit_mark(b.id, day, 1)
        self.db.delete_habit(a.id)
        self.assertEqual([h.name for h in self.db.list_habits()], ["Walking"])
        self.assertEqual(self.db.habit_marks(day, day)[day], {b.id: 1})

    def test_moving_changes_the_order_and_stops_at_the_ends(self):
        a, _b, c = self.habit("A"), self.habit("B"), self.habit("C")
        self.assertFalse(self.db.move_habit(a, -1))
        self.assertFalse(self.db.move_habit(c, 1))
        self.assertTrue(self.db.move_habit(c, -1))
        self.assertEqual([h.name for h in self.db.list_habits()], ["A", "C", "B"])

    def test_an_invalid_habit_is_refused_and_so_is_a_crowd(self):
        with self.assertRaises(ValueError):
            self.db.save_habit(Habit("", QUIT, START))
        for n in range(MAX_HABITS):
            self.habit(f"H{n}")
        with self.assertRaisesRegex(ValueError, "most habits"):
            self.habit("one too many")

    def test_marks_are_clamped(self):
        habit = self.habit()
        self.db.set_habit_mark(habit.id, START, 500)
        self.assertEqual(self.db.habit_counts(habit.id, START, START)[START], 99)

    def test_the_calendar_can_be_turned_off_without_losing_data(self):
        habit = self.habit()
        self.db.set_habit_mark(habit.id, START, 1)
        self.assertTrue(self.db.settings.habit_calendar)
        self.db.settings.habit_calendar = False
        self.assertFalse(self.db.settings.habit_calendar)
        self.assertEqual(self.db.habit_counts(habit.id, START, START), {START: 1})


class UpgradeTests(DbTestCase):
    def test_the_old_two_habit_calendar_becomes_two_habits_with_every_day(self):
        with self.db.connection() as conn:  # roll back to a version-9 file that was in use
            conn.execute("DROP TABLE habit_marks")
            conn.execute("DROP TABLE habits")
            conn.execute("PRAGMA user_version = 9")
            conn.execute("INSERT INTO habit_days VALUES ('2026-11-02', 2, 1, 'x')")
            conn.execute("INSERT INTO habit_days VALUES ('2026-11-03', 0, 3, 'x')")
            conn.execute("INSERT INTO app_settings(setting_key, setting_value) VALUES ('habit_start_porn', '2026-10-01')")
        db = Database(self.db.path)
        habits = {h.name: h for h in db.list_habits()}
        self.assertEqual(list(habits), ["Masturbation", "Porn"])
        self.assertTrue(all(h.kind == QUIT for h in habits.values()))
        self.assertEqual(habits["Porn"].start, date(2026, 10, 1))
        both = date(2026, 11, 1), date(2026, 11, 30)
        self.assertEqual(db.habit_counts(habits["Masturbation"].id, *both), {date(2026, 11, 2): 2})
        self.assertEqual(db.habit_counts(habits["Porn"].id, *both), {date(2026, 11, 2): 1, date(2026, 11, 3): 3})
        again = Database(self.db.path)  # opening it again must not carry things over twice
        self.assertEqual(len(again.list_habits()), 2)

    def test_someone_who_never_used_it_starts_with_none(self):
        with self.db.connection() as conn:
            conn.execute("DROP TABLE habit_marks")
            conn.execute("DROP TABLE habits")
            conn.execute("PRAGMA user_version = 9")
        self.assertEqual(Database(self.db.path).list_habits(), [])


if __name__ == "__main__":
    unittest.main()
