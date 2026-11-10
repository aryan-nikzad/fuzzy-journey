"""One pause model, bedtime as a hard stop, the closing check-in, optional evening work, work done."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fuzzy_journey import planner, pomodoro
from fuzzy_journey.database import Database
from fuzzy_journey.models import DayProgress, Task, TaskStatus, describe_progress
from fuzzy_journey.pomodoro import PomodoroSettings
from fuzzy_journey.prayer_times import PrayerDay, PrayerLibrary
from fuzzy_journey.rhythm import DayKind, Pause, Span, WorkStatus, work_progress
from fuzzy_journey.today import build_today
from tests.helpers import activity

D = date(2026, 11, 10)
PRAYERS = PrayerDay(D, {"Fajr": time(5, 9), "Sunrise": time(6, 31), "Dhuhr": time(11, 50),
                        "Asr": time(14, 49), "Maghrib": time(17, 28), "Isha": time(18, 14)})


def at(h, m=0):
    return datetime(2026, 11, 10, h, m)


def view(now, kind=DayKind.RECOVERED, manual=(), start=time(11, 4), acts=(), **kw):
    return build_today(
        now, kind, prayer_day=PRAYERS, next_fajr=time(5, 9), activities=list(acts), reminders=[],
        prayer_alarms={}, start=start if kind is DayKind.RECOVERED else None,
        pomodoro=PomodoroSettings(), pomodoro_pauses=list(manual), **kw,
    )


GYM = [activity("gym!", "14:00", "16:00", "health")]


class OnePauseModelTests(unittest.TestCase):
    """The screenshot: a Recovered day, the gym 14:00-16:00, a manual pause opened at 13:07."""

    def setUp(self):
        self.now = at(14, 9)
        self.v = view(self.now, manual=[(at(13, 7), None)], acts=GYM)
        self.work = self.v.work[0].progress

    def test_the_work_clock_and_the_pomodoro_clock_agree(self):
        # They used to disagree: the work clock said 39m / 16:39 while the focus block had 47m left.
        planning = self.v.schedule.planning
        self.assertEqual(planning.end, self.work.end)
        last_focus = max((s for s in self.v.schedule.segments if s.kind is pomodoro.SegmentKind.FOCUS),
                         key=lambda s: s.end)
        self.assertLessEqual(last_focus.end, planning.start)
        self.assertGreater(self.v.work_remaining, timedelta(minutes=39))

    def test_the_focus_block_waits_for_the_gym_instead_of_ending_inside_it(self):
        cur = pomodoro.current(self.v.schedule.segments, self.now)
        self.assertEqual(cur.kind, pomodoro.SegmentKind.FOCUS)
        self.assertGreaterEqual(cur.end, at(16, 0))  # it used to say 14:56, in the middle of the gym
        self.assertEqual(pomodoro.left_in(cur, self.v.pauses, self.now), timedelta(minutes=47))

    def test_the_gym_and_the_open_pause_are_one_pause_named_for_the_gym(self):
        today = [p for p in self.v.pauses if p.span.start.date() == D and p.span.end.date() == D]
        self.assertEqual(len(today), 1)  # merged: one pause, not a gym and a second pause on top
        pause = today[0]
        self.assertEqual((pause.title, pause.manual, pause.open), ("gym!", False, True))
        self.assertEqual(self.work.status, WorkStatus.PAUSED)

    def test_nothing_rings_while_the_pause_is_open(self):
        starts = [e.due for e in self.v.pomodoro_events]
        self.assertTrue(all(due < at(13, 7) for due in starts))

    def test_resuming_never_leaves_the_schedule_past_bedtime(self):
        for resume in (at(14, 9), at(16, 0), at(17, 30)):
            v = view(resume + timedelta(minutes=1), manual=[(at(13, 7), resume)], acts=GYM)
            self.assertLessEqual(v.schedule.segments[-1].end, v.bedtime)
            self.assertLessEqual(v.work[0].progress.end, v.bedtime)

    def test_a_late_resume_cuts_the_focus_and_planning_keeps_its_place(self):
        v = view(at(17, 31), manual=[(at(13, 7), at(17, 30))], acts=GYM)
        self.assertGreater(v.work_cut, timedelta(0))
        self.assertEqual(v.schedule.planning.end, v.bedtime)
        self.assertEqual(v.work[0].progress.cut, v.work_cut)
        self.assertIn("cut", v.timeline[-1].detail + " ".join(r.detail for r in v.timeline))


class DeadlineTests(unittest.TestCase):
    def test_work_progress_stops_at_the_deadline(self):
        start, planned = at(9), timedelta(hours=4)
        pause = [Pause(Span(at(10), at(12)), "class")]
        p = work_progress(start, planned, pause, at(11), deadline=at(14))
        self.assertEqual(p.end, at(14))
        self.assertEqual(p.cut, timedelta(hours=1))
        self.assertEqual(p.planned, timedelta(hours=3))
        self.assertEqual(work_progress(start, planned, pause, at(14), deadline=at(14)).status, WorkStatus.DONE)
        free = work_progress(start, planned, pause, at(11), deadline=at(20))
        self.assertEqual((free.cut, free.end), (timedelta(0), at(15)))


class EveningTests(unittest.TestCase):
    def test_any_working_day_can_have_an_evening_block_that_costs_sleep(self):
        plain = view(at(9), DayKind.STEADY)
        self.assertIsNone(plain.plan.evening)
        v = view(at(9), DayKind.STEADY, evening=60)
        self.assertEqual((v.plan.evening.start, v.plan.evening.end), (at(18), at(19)))
        self.assertEqual(v.bedtime, at(19))  # past Isha, so bed moves
        self.assertGreater(v.sleep_lost, timedelta(0))
        self.assertGreater(v.schedule.focus_minutes, plain.schedule.focus_minutes)

    def test_planning_moves_to_the_end_of_the_evening_and_a_rest_day_ignores_it(self):
        v = view(at(9), DayKind.STEADY, evening=60)
        self.assertEqual(v.schedule.planning.end, at(19))
        self.assertIsNone(view(at(9), DayKind.REST, evening=60).plan.evening)

    def test_a_recovered_day_gets_its_evening_after_the_recovered_work(self):
        v = view(at(9), DayKind.RECOVERED, start=time(17, 0), evening=30)
        self.assertGreaterEqual(v.plan.evening.start, v.plan.morning.end)

    def test_it_extends_an_existing_evening(self):
        base = view(at(9), DayKind.PUSH)
        more = view(at(9), DayKind.PUSH, evening=30)
        self.assertEqual(more.plan.evening.end - base.plan.evening.end, timedelta(minutes=30))


class DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "t.sqlite3")
        self.library = PrayerLibrary()


class StorageTests(DbCase):
    def test_evening_minutes_round_trip_and_a_rest_day_clears_them(self):
        self.db.set_day_evening(D, 90)
        self.assertEqual(self.db.day_entries(D, D)[D].evening, 90)
        self.db.set_day_kind(D, DayKind.REST)
        self.assertEqual(self.db.day_entries(D, D)[D].evening, 0)

    def test_a_final_day_is_never_rewritten(self):
        h = timedelta(hours=1)
        self.db.record_progress(D, h, 3 * h, 3 * h, 50)
        self.db.record_progress(D, 2 * h, 3 * h, 3 * h, 50, final=True)
        self.db.record_progress(D, 9 * h, 3 * h, 3 * h, 50)  # too late
        [day] = self.db.progress(D, D)
        self.assertEqual((day.worked, day.final), (2 * h, True))

    def test_closing_state_and_units(self):
        self.assertEqual(self.db.closing_state(D), (False, None))
        self.db.snooze_closing(D, at(15))
        self.assertEqual(self.db.closing_state(D), (False, at(15)))
        self.db.close_day(D)
        self.assertEqual(self.db.closing_state(D), (True, None))
        self.assertEqual(self.db.settings.progress_units, ("hours", "percent", "blocks"))
        self.db.settings.progress_units = ["blocks", "hours"]
        self.assertEqual(self.db.settings.progress_units, ("hours", "blocks"))
        self.db.settings.progress_units = []
        self.assertEqual(self.db.settings.progress_units, ("hours",))


class DescribeTests(unittest.TestCase):
    def test_every_unit_and_a_day_with_nothing_to_compare(self):
        p = DayProgress(D, timedelta(hours=2, minutes=40), timedelta(hours=3), timedelta(hours=4), 50)
        self.assertEqual(describe_progress(p, ("hours", "percent", "blocks")), "2h 40m · 67% · 3.2 blocks")
        self.assertEqual(describe_progress(p, ("blocks",)), "3.2 blocks")
        none = DayProgress(D, timedelta(0), timedelta(0), timedelta(0), 50)
        self.assertEqual(describe_progress(none, ("hours", "percent")), "0m · —")


class ClosingTests(DbCase):
    """The bundled day for 2 Nov 2026: planning runs 11:11-11:41."""

    DAY = date(2026, 11, 2)

    def due(self, h, m):
        now = datetime(2026, 11, 2, h, m)
        return planner.closing_due(self.db, planner.build_view(self.db, self.library, now), now)

    def test_asks_when_planning_begins_if_tasks_are_open(self):
        self.db.save_task(Task("Write", 30, self.DAY))
        self.assertFalse(self.due(11, 10))
        self.assertTrue(self.due(11, 11))
        self.assertTrue(self.due(12, 30))  # and keeps asking until it is answered

    def test_nothing_to_ask_without_open_tasks_and_prayers_do_not_count(self):
        self.db.ensure_prayer_tasks(self.DAY)
        self.assertFalse(self.due(11, 20))
        task = Task("Write", 30, self.DAY)
        self.db.save_task(task)
        self.db.set_task_status(task.id, TaskStatus.DONE)
        self.assertFalse(self.due(11, 20))

    def test_snooze_and_close_are_respected(self):
        self.db.save_task(Task("Write", 30, self.DAY))
        self.db.snooze_closing(self.DAY, datetime(2026, 11, 2, 11, 41))
        self.assertFalse(self.due(11, 30))
        self.assertTrue(self.due(11, 41))
        self.db.close_day(self.DAY)
        self.assertFalse(self.due(12, 0))

    def test_never_asks_in_the_night(self):
        self.db.save_task(Task("Write", 30, self.DAY))
        self.assertFalse(self.due(23, 30))

    def test_each_judgement_call_can_be_changed(self):
        self.db.save_task(Task("Write", 30, self.DAY))
        self.db.settings.closing_prompt = False
        self.assertFalse(self.due(11, 30))  # never by itself
        self.db.settings.closing_prompt = True
        self.db.settings.closing_snooze = 45
        self.assertEqual(planner.snooze(self.db), timedelta(minutes=45))
        self.db.settings.closing_snooze = 5000
        self.assertEqual(self.db.settings.closing_snooze, 120)  # kept in range

    def test_the_reminder_opens_it_even_with_nothing_open_but_only_if_asked_for(self):
        self.assertFalse(self.due(11, 30))
        self.db.settings.closing_reminder = True
        self.assertTrue(self.due(11, 30))
        self.db.close_day(self.DAY)
        self.assertFalse(self.due(11, 30))

    def test_bedtime_protection_can_be_switched_off(self):
        now = datetime(2026, 11, 2, 9, 0)
        self.db.pause_pomodoro(self.DAY, datetime(2026, 11, 2, 8, 30))
        self.db.resume_pomodoro(self.DAY, datetime(2026, 11, 2, 17, 30))  # a pause that eats the whole day
        kept = planner.build_view(self.db, self.library, now)
        self.assertGreater(kept.work_cut, timedelta(0))
        self.db.settings.protect_bedtime = False
        free = planner.build_view(self.db, self.library, now)
        self.assertEqual(free.work_cut, timedelta(0))
        self.assertGreater(free.work[0].progress.end, kept.work[0].progress.end)

    def test_a_longer_day_asks_later_not_now(self):
        self.db.save_task(Task("Write", 30, self.DAY))
        self.db.set_day_evening(self.DAY, 60)  # planning moves to the end of the evening block
        self.assertFalse(self.due(11, 30))
        view = planner.build_view(self.db, self.library, datetime(2026, 11, 2, 9, 0))
        self.assertGreater(view.closing_at, datetime(2026, 11, 2, 18, 0))


class RecordingTests(DbCase):
    def test_today_is_recorded_and_a_finished_day_is_closed_but_never_invented(self):
        day = date(2026, 11, 2)
        planner.record_progress(self.db, self.library, datetime(2026, 11, 2, 11, 30))
        [today] = self.db.progress(day, day)
        self.assertGreater(today.worked, timedelta(0))
        self.assertGreater(today.steady, timedelta(0))
        self.assertFalse(today.final)
        planner.record_progress(self.db, self.library, datetime(2026, 11, 3, 8, 0))
        days = {p.day: p for p in self.db.progress(date(2026, 10, 25), date(2026, 11, 3))}
        self.assertTrue(days[day].final)
        self.assertNotIn(date(2026, 11, 1), days)  # nobody was around that day: nothing is made up
        self.assertGreaterEqual(days[day].worked, today.worked)

    def test_the_work_done_counts_only_focus_and_not_pauses(self):
        day = date(2026, 11, 2)
        now = datetime(2026, 11, 2, 11, 30)
        base = planner.build_view(self.db, self.library, now).worked
        self.db.pause_pomodoro(day, datetime(2026, 11, 2, 10, 0))
        self.db.resume_pomodoro(day, datetime(2026, 11, 2, 10, 40))
        paused = planner.build_view(self.db, self.library, now).worked
        self.assertLess(paused, base)


if __name__ == "__main__":
    unittest.main()
