from __future__ import annotations

from datetime import date

from fuzzy_journey import tasks
from fuzzy_journey.models import Task, TaskStatus
from tests.helpers import DbTestCase

DAY = date(2026, 11, 2)


def task(title="T", minutes=30, **kw):
    return Task(title, minutes, kw.pop("day", DAY), **kw)


class RuleTests(DbTestCase):
    def test_my_order_follows_position_and_settled_tasks_sink(self):
        a, b, c = task("a", position=0), task("b", position=1), task("c", position=2)
        a.status = TaskStatus.DONE
        order = [t.title for t in tasks.in_order([a, b, c], tasks.ORDER_SEQUENCE)]
        self.assertEqual(order, ["b", "c", "a"])

    def test_importance_order_puts_high_first_then_position(self):
        low, high, normal = task("low", level=3), task("high", level=1, position=5), task("n", level=2)
        order = [t.title for t in tasks.in_order([low, normal, high], tasks.ORDER_LEVEL)]
        self.assertEqual(order, ["high", "n", "low"])

    def test_cannot_plan_more_than_the_days_focus_time(self):
        existing = [task(minutes=120), task(minutes=100)]
        self.assertIsNone(tasks.check_task("x", 80, existing, 300))
        self.assertIn("Only 1h 20m", tasks.check_task("x", 85, existing, 300))
        self.assertIn("full", tasks.check_task("x", 5, [task(minutes=300)], 300))
        self.assertIn("no focus time", tasks.check_task("x", 5, [], 0))

    def test_cancelled_tasks_do_not_use_focus_time(self):
        gone = task(minutes=200)
        gone.status = TaskStatus.CANCELLED
        self.assertEqual(tasks.load([gone, task(minutes=60)], 300).planned, 60)

    def test_lengths_are_five_minute_steps_from_5_to_360(self):
        for bad in (0, 3, 7, 365, 361):
            self.assertIsNotNone(tasks.check_task("x", bad, [], 600), bad)
        for good in (5, 10, 335, 360):
            self.assertIsNone(tasks.check_task("x", good, [], 600), good)
        self.assertIsNotNone(tasks.check_task("  ", 30, [], 600))

    def test_load_flags_the_ninety_percent_line(self):
        self.assertFalse(tasks.load([task(minutes=270)], 300).over_recommended)
        self.assertTrue(tasks.load([task(minutes=275)], 300).over_recommended)


class StoreTests(DbTestCase):
    def test_new_tasks_start_unset_and_keep_their_order(self):
        for name in "abc":
            self.db.save_task(task(name))
        got = self.db.tasks_on(DAY)
        self.assertEqual([t.title for t in got], ["a", "b", "c"])
        self.assertTrue(all(t.status is TaskStatus.UNSET for t in got))
        self.db.move_task(got[2], -1, got)
        self.assertEqual([t.title for t in self.db.tasks_on(DAY)], ["a", "c", "b"])

    def test_tasks_belong_to_their_day(self):
        self.db.save_task(task("today"))
        self.assertEqual(self.db.tasks_on(date(2026, 11, 3)), [])

    def test_carrying_copies_to_tomorrow_and_undoing_removes_it(self):
        task_id = self.db.save_task(task("write", 45, level=1))
        self.db.set_task_status(task_id, TaskStatus.CARRIED)
        copy = self.db.tasks_on(date(2026, 11, 3))
        self.assertEqual([(t.title, t.minutes, t.level, t.status) for t in copy],
                         [("write", 45, 1, TaskStatus.UNSET)])
        self.assertEqual(copy[0].origin_id, task_id)
        self.db.set_task_status(task_id, TaskStatus.CARRIED)  # again: no second copy
        self.assertEqual(len(self.db.tasks_on(date(2026, 11, 3))), 1)
        self.db.set_task_status(task_id, TaskStatus.DONE)
        self.assertEqual(self.db.tasks_on(date(2026, 11, 3)), [])

    def test_a_stale_task_is_carried_to_today_not_into_the_past(self):
        old = self.db.save_task(task("old", day=date(2026, 10, 28)))
        self.db.set_task_status(old, TaskStatus.CARRIED, today=DAY)
        self.assertEqual([t.title for t in self.db.tasks_on(DAY)], ["old"])
        self.assertEqual(self.db.tasks_on(date(2026, 10, 29)), [])

    def test_done_and_cancelled_do_not_move_anywhere(self):
        a, b = self.db.save_task(task("a")), self.db.save_task(task("b"))
        self.db.set_task_status(a, TaskStatus.DONE)
        self.db.set_task_status(b, TaskStatus.CANCELLED)
        self.assertEqual(self.db.tasks_on(date(2026, 11, 3)), [])

    def test_unset_tasks_from_earlier_days_are_found(self):
        a = self.db.save_task(task("old", day=date(2026, 11, 1)))
        self.db.save_task(task("today"))
        self.assertEqual([t.title for t in self.db.unset_tasks_before(DAY)], ["old"])
        self.db.set_task_status(a, TaskStatus.DONE)
        self.assertEqual(self.db.unset_tasks_before(DAY), [])

    def test_editing_keeps_status_and_position(self):
        t = task("a")
        self.db.save_task(t)
        self.db.set_task_status(t.id, TaskStatus.DONE)
        edited = self.db.tasks_on(DAY)[0]
        edited.title, edited.minutes = "renamed", 90
        self.db.save_task(edited)
        got = self.db.tasks_on(DAY)[0]
        self.assertEqual((got.title, got.minutes, got.status), ("renamed", 90, TaskStatus.DONE))

    def test_settings_round_trip_and_defaults(self):
        s = self.db.settings
        self.assertTrue(s.pomodoro.enabled and s.pomodoro.planning_enabled)
        self.assertEqual((s.pomodoro.focus, s.pomodoro.short, s.pomodoro.long, s.pomodoro.long_every), (50, 10, 30, 3))
        self.assertEqual(s.task_order, tasks.ORDER_SEQUENCE)
        from dataclasses import replace

        s.pomodoro = replace(s.pomodoro, enabled=False, long_enabled=False, focus=25)
        s.task_order = tasks.ORDER_LEVEL
        self.assertEqual((s.pomodoro.enabled, s.pomodoro.long_enabled, s.pomodoro.focus), (False, False, 25))
        self.assertTrue(s.pomodoro.short_enabled)
        self.assertEqual(s.task_order, tasks.ORDER_LEVEL)


class PrayerTests(DbTestCase):
    def prayers(self, day=DAY):
        return [t for t in self.db.tasks_on(day) if t.is_prayer]

    def test_every_day_gets_the_five_prayers_once(self):
        self.db.ensure_prayer_tasks(DAY)
        self.db.ensure_prayer_tasks(DAY)  # idempotent
        got = self.prayers()
        self.assertEqual([t.title for t in got], list(tasks.PRAYERS))
        self.assertTrue(all(t.minutes == 0 and t.status is TaskStatus.UNSET for t in got))
        self.assertEqual(self.prayers(date(2026, 11, 3)), [])  # other days are created for themselves

    def test_prayers_never_count_as_focus_time_or_block_a_task(self):
        self.db.ensure_prayer_tasks(DAY)
        mine = self.db.tasks_on(DAY)
        self.assertEqual(tasks.load(mine, 300).planned, 0)
        self.assertIsNone(tasks.check_task("x", 300, mine, 300))  # all the focus time is still free

    def test_they_cannot_be_deleted_or_edited(self):
        self.db.ensure_prayer_tasks(DAY)
        fajr = self.prayers()[0]
        self.db.delete_task(fajr.id)
        fajr.title, fajr.minutes = "Renamed", 45
        self.db.save_task(fajr)
        again = self.prayers()[0]
        self.assertEqual((again.title, again.minutes), ("Fajr", 0))
        self.assertEqual(len(self.prayers()), 5)

    def test_a_prayer_can_wait_one_day_and_no_more(self):
        self.db.ensure_prayer_tasks(DAY)
        dhuhr = self.prayers()[1]
        self.db.set_task_status(dhuhr.id, TaskStatus.CARRIED)
        copy = next(t for t in self.db.tasks_on(date(2026, 11, 3)) if t.is_prayer)
        self.assertEqual((copy.title, copy.minutes, copy.origin_id), ("Dhuhr", 0, dhuhr.id))
        self.db.set_task_status(copy.id, TaskStatus.CARRIED)  # refused: it already waited a day
        self.assertEqual(self.db.tasks_on(date(2026, 11, 4)), [])
        self.assertIs(self.db.tasks_on(date(2026, 11, 3), prayers=True)[0].status, TaskStatus.UNSET)
        self.db.set_task_status(copy.id, TaskStatus.CANCELLED)  # the way out, so it is never asked for ever
        self.assertIs(self.db.tasks_on(date(2026, 11, 3))[0].status, TaskStatus.CANCELLED)

    def test_an_original_prayer_cannot_be_cancelled(self):
        self.db.ensure_prayer_tasks(DAY)
        isha = self.prayers()[4]
        self.db.set_task_status(isha.id, TaskStatus.CANCELLED)
        self.assertIs(self.prayers()[4].status, TaskStatus.UNSET)
        self.db.set_task_status(isha.id, TaskStatus.DONE)
        self.assertIs(self.prayers()[4].status, TaskStatus.DONE)

    def test_undoing_a_carry_removes_the_copy_and_two_of_a_kind_can_share_a_day(self):
        tomorrow = date(2026, 11, 3)
        self.db.ensure_prayer_tasks(DAY)
        self.db.ensure_prayer_tasks(tomorrow)
        asr = self.prayers()[2]
        self.db.set_task_status(asr.id, TaskStatus.CARRIED)
        self.assertEqual([t.title for t in self.db.tasks_on(tomorrow) if t.title == "Asr"], ["Asr", "Asr"])
        self.db.set_task_status(asr.id, TaskStatus.DONE)
        self.assertEqual([t.title for t in self.db.tasks_on(tomorrow) if t.title == "Asr"], ["Asr"])

    def test_unsettled_prayers_of_an_earlier_day_are_asked_about(self):
        self.db.ensure_prayer_tasks(DAY)
        self.assertEqual(len(self.db.unset_tasks_before(date(2026, 11, 3))), 5)
