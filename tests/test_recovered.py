from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from fuzzy_journey import planner
from fuzzy_journey.models import Task
from fuzzy_journey.pomodoro import SegmentKind
from fuzzy_journey.prayer_times import PrayerLibrary
from fuzzy_journey.rhythm import DayKind, check_recovered_start, plan_day, summarize_bank
from tests.helpers import DbTestCase

DAY = date(2026, 11, 2)
FAJR, ISHA = time(5, 3), time(18, 20)  # the bundled Shahrekord day


def recovered(start, **kw):
    return plan_day(DAY, DayKind.RECOVERED, fajr=FAJR, isha=ISHA, next_fajr=time(5, 5), start=start, **kw)


class RuleTests(DbTestCase):
    def test_work_is_half_of_the_time_awake_and_may_run_into_the_afternoon(self):
        plan = recovered(time(10, 0))
        self.assertEqual(plan.wake, datetime(2026, 11, 2, 10, 0))
        self.assertEqual((plan.target, plan.morning.start.time(), plan.morning.end.time()),
                         (timedelta(hours=4, minutes=10), time(10, 0), time(14, 10)))
        self.assertIsNone(plan.evening)  # no evening block: half of the awake time always fits before Isha
        self.assertEqual((plan.bedtime.time(), plan.sleep_lost), (ISHA, timedelta(0)))
        self.assertEqual(plan.free.start.time(), time(14, 10))

    def test_a_steady_day_is_unchanged_by_the_new_kind(self):
        steady = plan_day(DAY, DayKind.STEADY, fajr=FAJR, isha=ISHA, next_fajr=time(5, 5))
        self.assertEqual(steady.morning.end.time(), time(11, 41))
        self.assertEqual(steady.wake.time(), FAJR)

    def test_a_late_start_cannot_leave_less_than_an_hour(self):
        plan = recovered(time(23, 0))  # clamped, never a negative or silly day
        self.assertEqual(plan.wake.time(), time(17, 20))
        self.assertEqual(recovered(time(3, 0)).wake.time(), FAJR)
        self.assertIsNotNone(check_recovered_start(FAJR, ISHA, time(17, 30)))
        self.assertIsNotNone(check_recovered_start(FAJR, ISHA, time(4, 0)))
        self.assertIsNone(check_recovered_start(FAJR, ISHA, time(10, 0)))

    def test_extra_focus_time_still_applies(self):
        plan = recovered(time(10, 0), flex=timedelta(minutes=30))
        self.assertEqual(plan.target, timedelta(hours=4, minutes=40))

    def test_it_is_neutral_for_the_bank(self):
        self.assertEqual(DayKind.RECOVERED.bank_delta, 0.0)
        bank = summarize_bank({DAY: DayKind.RECOVERED, DAY + timedelta(days=1): DayKind.PUSH}, DAY, DAY + timedelta(days=1))
        self.assertEqual((bank.balance, bank.steady_days, bank.push_days), (0.5, 1, 1))


class StorageTests(DbTestCase):
    def test_start_time_round_trips_and_survives_a_note(self):
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(10, 0))
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "overslept, alarm off")  # a note edit, no start given
        entry = self.db.day_entries(DAY, DAY)[DAY]
        self.assertEqual((entry.kind, entry.start, entry.note), (DayKind.RECOVERED, time(10, 0), "overslept, alarm off"))

    def test_choosing_another_kind_clears_it(self):
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(10, 0))
        self.db.set_day_kind(DAY, DayKind.PUSH)
        entry = self.db.day_entries(DAY, DAY)[DAY]
        self.assertEqual((entry.kind, entry.start), (DayKind.PUSH, None))

    def test_older_versions_read_it_as_a_plain_steady_day(self):
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(10, 0))
        row = sqlite3.connect(self.db.path).execute("SELECT day_type FROM day_entries").fetchone()
        self.assertEqual(row[0], "50")  # the original CHECK constraint is never violated


class FollowTheWorkTests(DbTestCase):
    def test_pomodoro_planning_and_task_room_follow_the_new_window(self):
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(10, 0))
        view = planner.build_view(self.db, PrayerLibrary(), datetime(2026, 11, 2, 10, 5))
        self.assertEqual([w.title for w in view.work], ["Recovered work"])
        segments = view.schedule.segments
        self.assertEqual((segments[0].kind, segments[0].start.time()), (SegmentKind.FOCUS, time(10, 0)))
        self.assertEqual(segments[-1].kind, SegmentKind.PLANNING)
        self.assertEqual(segments[-1].end.time(), time(14, 10))
        self.assertGreater(view.schedule.focus_minutes, 0)
        self.assertLess(view.schedule.focus_minutes, 250 - 30)  # breaks and planning are not focus

    def test_tasks_set_the_day_before_stay_and_are_measured_against_the_new_room(self):
        from fuzzy_journey import tasks

        self.db.save_task(Task("Planned yesterday", 180, DAY))
        steady = planner.build_view(self.db, PrayerLibrary(), datetime(2026, 11, 2, 5, 10)).schedule.focus_minutes
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(10, 0))
        late = planner.build_view(self.db, PrayerLibrary(), datetime(2026, 11, 2, 10, 5)).schedule.focus_minutes
        self.assertGreater(steady, late)
        self.assertEqual([t.title for t in self.db.tasks_on(DAY)], ["Planned yesterday"])
        self.assertEqual(late, 170)
        self.assertTrue(tasks.load(self.db.tasks_on(DAY), late).over)  # 3h no longer fits: shown, never deleted
        self.db.save_task(Task("Small", 5, DAY))
        self.assertIsNotNone(tasks.check_task("one more", 5, self.db.tasks_on(DAY), late))  # and nothing is added
        self.assertEqual(len(self.db.tasks_on(DAY)), 2)
