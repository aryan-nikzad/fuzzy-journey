"""Self-test tasks: when they fall, that they are added once, and that they never nag."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

from fuzzy_journey import planner, selftest
from fuzzy_journey.models import TaskStatus
from fuzzy_journey.tasks import can_carry

from .helpers import DbTestCase

DAY = date(2026, 11, 2)
PRAYERS = {"Fajr": time(5, 30), "Dhuhr": time(12, 0), "Asr": time(15, 0), "Maghrib": time(17, 30), "Isha": time(18, 45)}
WAKE, BED = datetime(2026, 11, 2, 5, 30), datetime(2026, 11, 2, 21, 0)


class TimesTests(unittest.TestCase):
    def test_off_gives_nothing(self):
        self.assertEqual(selftest.times_for("off", 4, DAY, PRAYERS, WAKE, BED), [])

    def test_prayer_mode_follows_the_five_prayers(self):
        times = selftest.times_for("prayers", 4, DAY, PRAYERS, WAKE, BED)
        self.assertEqual([t.strftime("%H:%M") for t in times], ["05:30", "12:00", "15:00", "17:30", "18:45"])

    def test_interval_mode_runs_from_waking_until_bed(self):
        times = selftest.times_for("interval", 4, DAY, PRAYERS, WAKE, BED)
        self.assertEqual([t.strftime("%H:%M") for t in times], ["05:30", "09:30", "13:30", "17:30"])
        self.assertEqual(len(selftest.times_for("interval", 1, DAY, PRAYERS, WAKE, BED)), 16)

    def test_interval_mode_needs_a_known_day(self):
        self.assertEqual(selftest.times_for("interval", 4, DAY, PRAYERS, None, None), [])

    def test_only_the_latest_due_time_counts(self):
        times = selftest.times_for("prayers", 4, DAY, PRAYERS, WAKE, BED)
        self.assertIsNone(selftest.latest_due(times, datetime(2026, 11, 2, 5, 0)))
        self.assertEqual(selftest.latest_due(times, datetime(2026, 11, 2, 16, 0)).strftime("%H:%M"), "15:00")


class TaskTests(DbTestCase):
    def test_a_test_is_added_once_and_is_zero_length(self):
        moment = datetime(2026, 11, 2, 12, 0)
        self.db.settings.selftest_mode = "prayers"
        self.assertTrue(self.db.add_selftest_task(DAY, moment))
        self.assertFalse(self.db.add_selftest_task(DAY, moment))
        (task,) = self.db.tasks_on(DAY)
        self.assertEqual((task.title, task.minutes, task.is_selftest), ("Test myself · 12:00", 0, True))

    def test_they_are_hidden_when_off_and_never_count_as_open_work(self):
        self.db.settings.selftest_mode = "prayers"
        self.db.add_selftest_task(DAY, datetime(2026, 11, 2, 12, 0))
        self.assertEqual(len(self.db.tasks_on(DAY)), 1)
        self.assertEqual(self.db.tasks_on(DAY, prayers=False), [])  # the closing check-in ignores them
        self.db.settings.selftest_mode = "off"
        self.assertEqual(self.db.tasks_on(DAY), [])

    def test_an_unticked_test_never_appears_in_a_later_review(self):
        self.db.settings.selftest_mode = "prayers"
        self.db.add_selftest_task(DAY, datetime(2026, 11, 2, 12, 0))
        self.assertEqual(self.db.unset_tasks_before(DAY + timedelta(days=1)), [])

    def test_a_test_can_be_ticked_but_never_carried_to_another_day(self):
        self.db.settings.selftest_mode = "interval"
        self.db.add_selftest_task(DAY, datetime(2026, 11, 2, 12, 0))
        (task,) = self.db.tasks_on(DAY)
        self.assertFalse(can_carry(task))
        self.db.set_task_status(task.id, TaskStatus.CARRIED, today=DAY)
        self.assertEqual(self.db.tasks_on(DAY + timedelta(days=1)), [])
        self.db.set_task_status(task.id, TaskStatus.DONE)
        self.assertEqual(self.db.tasks_on(DAY)[0].status, TaskStatus.DONE)

    def test_settings_have_safe_defaults_and_limits(self):
        s = self.db.settings
        self.assertEqual((s.selftest_mode, s.selftest_hours), ("off", 4))
        s.selftest_mode = "nonsense"
        self.assertEqual(s.selftest_mode, "off")
        s.selftest_hours = 99
        self.assertEqual(s.selftest_hours, 12)

    def test_the_planner_adds_the_latest_due_test_once(self):
        from types import SimpleNamespace

        class Library:
            def day(self, _slug, _day):
                return SimpleNamespace(times=PRAYERS)

        self.db.settings.selftest_mode = "prayers"
        view = SimpleNamespace(day=DAY, now=datetime(2026, 11, 2, 16, 0), wake=WAKE, bedtime=BED)
        self.assertTrue(planner.add_due_selftest(self.db, Library(), view))
        self.assertFalse(planner.add_due_selftest(self.db, Library(), view))
        self.assertEqual([t.title for t in self.db.tasks_on(DAY)], ["Test myself · 15:00"])  # 12:00 was skipped
        view.now = datetime(2026, 11, 2, 17, 31)
        self.assertTrue(planner.add_due_selftest(self.db, Library(), view))
        self.assertEqual(len(self.db.tasks_on(DAY)), 2)
        self.db.settings.selftest_mode = "off"
        self.assertFalse(planner.add_due_selftest(self.db, Library(), view))


class ServiceTests(DbTestCase):
    def test_the_service_adds_the_task_and_rings_once_even_with_the_window_closed(self):
        from fuzzy_journey import service
        from fuzzy_journey.prayer_times import PrayerLibrary

        library = PrayerLibrary()
        now = datetime(2026, 11, 2, 12, 40)  # the bundled Dhuhr of 2 Nov 2026 has passed by now
        self.assertEqual([r.key for r in service.due_rings(self.db, library, now)], [])  # off: nothing
        self.db.settings.selftest_mode = "prayers"
        rings = [r for r in service.due_rings(self.db, library, now) if r.key == "selftest"]
        self.assertEqual(len(rings), 1)
        self.assertFalse(rings[0].sound.enabled)  # a quiet notification, not an alarm
        self.assertEqual(len(self.db.tasks_on(DAY)), 1)
        self.assertEqual([r.key for r in service.due_rings(self.db, library, now) if r.key == "selftest"], [])


if __name__ == "__main__":
    unittest.main()
