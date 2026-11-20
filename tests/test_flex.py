"""The Flexibility pack: a morning routine, Start work, flexible blocks, End work, Do nothing.

The rule that matters most is the first one: with the pack off, the app is exactly what it was.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fuzzy_journey import planner
from fuzzy_journey.database import SCHEMA_VERSION, Database
from fuzzy_journey.flex import (
    AFTER_WORK,
    BEFORE_WORK,
    FIXED_TIME,
    FlexDay,
    FlexInput,
    FlexSettings,
    Phase,
    RoutineItem,
    Run,
    check_routine_item,
    flex_state,
    next_kind,
    routine_plan,
)
from fuzzy_journey.pomodoro import PomodoroSettings, SegmentKind
from fuzzy_journey.prayer_times import PrayerDay, PrayerLibrary
from fuzzy_journey.rhythm import DayKind, Pause, Span, plan_day
from fuzzy_journey.today import Slot, build_today
from tests.helpers import DbTestCase, activity

D = date(2026, 11, 10)
PRAYERS = PrayerDay(D, {"Fajr": time(5, 9), "Sunrise": time(6, 31), "Dhuhr": time(11, 50),
                        "Asr": time(14, 49), "Maghrib": time(17, 28), "Isha": time(18, 14)})
F, S, L = SegmentKind.FOCUS, SegmentKind.SHORT, SegmentKind.LONG
ROUTINE = (RoutineItem("Wash and dress", 20), RoutineItem("Breakfast", 25), RoutineItem("Read the plan", 10))


def at(h, m=0, s=0):
    return datetime(2026, 11, 10, h, m, s)


def view(now, settings=None, day=None, routine=ROUTINE, kind=DayKind.STEADY, acts=(), pomodoro=PomodoroSettings(),
         manual=(), **kw):
    pack = None if settings is None else FlexInput(settings, tuple(routine), day or FlexDay())
    return build_today(
        now, kind, prayer_day=PRAYERS, next_fajr=time(5, 9), activities=list(acts), reminders=[],
        prayer_alarms={}, pomodoro=pomodoro, pomodoro_pauses=list(manual), flexpack=pack, **kw,
    )


ON = FlexSettings(enabled=True, buffer=15, nothing=False, blocks=False)


# --------------------------------------------------------------------------
# Off means off
# --------------------------------------------------------------------------


class PackOffTests(unittest.TestCase):
    def snapshot(self, v):
        return (v.plan, v.work, v.schedule, v.timeline, v.worked, v.closing_at, v.pomodoro_events,
                v.segments, v.wake, v.bedtime, v.focus, v.work_remaining)

    def test_no_pack_and_a_disabled_pack_are_the_same_as_before(self):
        now = at(8, 10)
        plain = view(now)
        for settings in (FlexSettings(), FlexSettings(enabled=False, manual_start=True, nothing=True, buffer=60)):
            off = view(now, settings, FlexDay(started_at=at(7, 0)), routine=ROUTINE)
            self.assertEqual(self.snapshot(off), self.snapshot(plain))
            self.assertIsNone(off.flexpack)

    def test_a_fresh_database_has_the_pack_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "x.sqlite3")
            self.assertFalse(db.settings.flexibility.enabled)
            self.assertFalse(db.settings.flexibility.controls_work)
            self.assertFalse(db.settings.flexibility.use_routine)
            self.assertFalse(db.settings.flexibility.use_nothing)

    def test_the_sub_options_mean_nothing_while_the_pack_is_off(self):
        s = FlexSettings(enabled=False, routine=True, manual_start=True, blocks=True, nothing=True)
        self.assertFalse(any((s.use_routine, s.use_start, s.use_blocks, s.use_nothing, s.controls_work)))

    def test_work_start_none_changes_nothing_in_the_plan(self):
        kw = dict(fajr=time(5, 9), isha=time(18, 14), next_fajr=time(5, 9))
        for kind in (DayKind.STEADY, DayKind.PUSH, DayKind.RECOVERED, DayKind.REST):
            extra = {"start": time(10, 0)} if kind is DayKind.RECOVERED else {}
            self.assertEqual(plan_day(D, kind, **kw, **extra), plan_day(D, kind, **kw, **extra, work_start=None))


# --------------------------------------------------------------------------
# The morning routine
# --------------------------------------------------------------------------


class RoutineTests(unittest.TestCase):
    def test_steps_run_back_to_back_then_the_buffer(self):
        plan = routine_plan(at(5, 9), ROUTINE, 15)
        self.assertEqual([(s.title, s.span.start.time(), s.span.end.time()) for s in plan.steps], [
            ("Wash and dress", time(5, 9), time(5, 29)),
            ("Breakfast", time(5, 29), time(5, 54)),
            ("Read the plan", time(5, 54), time(6, 4)),
            ("Buffer", time(6, 4), time(6, 19)),
        ])
        self.assertEqual(plan.end, at(6, 19))
        self.assertEqual(plan.total, timedelta(minutes=70))
        self.assertTrue(plan.steps[-1].buffer)

    def test_no_steps_means_no_routine_even_with_a_buffer(self):
        self.assertIsNone(routine_plan(at(5, 9), [], 30))
        self.assertIsNone(routine_plan(at(5, 9), [RoutineItem("x", 10, enabled=False)], 30))

    def test_a_disabled_step_is_skipped_and_zero_buffer_adds_none(self):
        plan = routine_plan(at(5, 0), [RoutineItem("a", 10), RoutineItem("b", 20, enabled=False), RoutineItem("c", 5)], 0)
        self.assertEqual([s.title for s in plan.steps], ["a", "c"])
        self.assertEqual(plan.end, at(5, 15))

    def test_current_and_following_step(self):
        plan = routine_plan(at(5, 0), ROUTINE, 10)
        self.assertEqual(plan.current(at(5, 25)).title, "Breakfast" if False else "Breakfast")
        self.assertEqual(plan.following(plan.current(at(5, 25))).title, "Read the plan")
        self.assertIsNone(plan.current(plan.end))

    def test_checking_a_step(self):
        self.assertIsNone(check_routine_item("Shower", 10))
        self.assertIn("name", check_routine_item("  ", 10))
        self.assertIn("minutes", check_routine_item("Shower", 0))

    def test_work_begins_after_the_routine_not_at_fajr(self):
        v = view(at(5, 30), ON)
        self.assertEqual(v.flexpack.routine.end, at(6, 19))
        morning = v.work[0].progress
        self.assertEqual(morning.start, at(6, 19))
        self.assertEqual(v.schedule.segments[0].start, at(6, 19))
        # The share of the day is still the share: the same 6h32 of work, only later.
        plain = view(at(5, 30))
        self.assertEqual(v.plan.target, plain.plan.target)
        self.assertEqual(morning.end - morning.start, plain.work[0].progress.end - plain.work[0].progress.start)

    def test_the_routine_is_on_the_timeline(self):
        v = view(at(5, 30), ON)
        rows = [r for r in v.timeline if r.slot is Slot.ROUTINE]
        self.assertEqual([r.title for r in rows], ["Wash and dress", "Breakfast", "Read the plan", "Buffer"])

    def test_a_routine_that_pushes_work_past_14h_sends_the_rest_to_the_evening(self):
        long_routine = [RoutineItem("Everything", 240)]
        v = view(at(5, 30), ON, routine=long_routine)
        self.assertIsNotNone(v.plan.evening)
        self.assertLessEqual(v.plan.morning.end.time(), time(14, 0))
        self.assertEqual(v.plan.target, view(at(5, 30)).plan.target)

    def test_a_rest_day_keeps_its_routine_but_gains_no_work(self):
        v = view(at(6, 0), ON, kind=DayKind.REST)
        self.assertEqual(v.work, ())
        self.assertIsNotNone(v.flexpack.routine)

    def test_pack_on_without_a_routine_changes_nothing_in_the_plan(self):
        for routine in ((), [RoutineItem("x", 10, enabled=False)]):
            v = view(at(5, 30), ON, routine=routine)
            self.assertEqual(v.plan, view(at(5, 30)).plan)
            self.assertIsNone(v.flexpack.routine)

    def test_the_routine_switch_turns_it_off(self):
        v = view(at(5, 30), FlexSettings(enabled=True, routine=False, blocks=False, nothing=False))
        self.assertEqual(v.plan, view(at(5, 30)).plan)


# --------------------------------------------------------------------------
# Start work by button
# --------------------------------------------------------------------------

START = FlexSettings(enabled=True, routine=False, manual_start=True, blocks=False, nothing=False)


class StartButtonTests(unittest.TestCase):
    def test_before_the_press_the_plan_is_what_starting_now_would_mean(self):
        v = view(at(9, 4, 30), START)
        self.assertTrue(v.flexpack.waiting)
        self.assertEqual(v.flexpack.state.phase, Phase.WAITING)
        self.assertEqual(v.work[0].progress.start, at(9, 4))
        self.assertEqual(v.plan.target, view(at(9, 4)).plan.target)

    def test_nothing_rings_while_waiting(self):
        self.assertEqual(view(at(9, 4), START).pomodoro_events, ())

    def test_the_press_anchors_the_day(self):
        day = FlexDay(started_at=at(7, 30))
        v = view(at(8, 0), START, day)
        self.assertFalse(v.flexpack.waiting)
        self.assertEqual(v.work[0].progress.start, at(7, 30))
        self.assertEqual(v.schedule.segments[0].start, at(7, 30))
        self.assertEqual(v.flexpack.state.phase, Phase.RUNNING)
        self.assertTrue(v.pomodoro_events)

    def test_starting_early_is_allowed_even_before_fajr(self):
        v = view(at(4, 0), START, FlexDay(started_at=at(4, 0)))
        self.assertEqual(v.work[0].progress.start, at(5, 9))  # the day still begins at Fajr

    def test_the_closing_check_in_waits_for_end_work(self):
        day = FlexDay(started_at=at(7, 30))
        self.assertIsNone(view(at(20, 0), START, day).closing_at)
        ended = FlexDay(started_at=at(7, 30), ended_at=at(13, 10))
        v = view(at(13, 11), START, ended)
        self.assertEqual(v.closing_at, at(13, 10))
        self.assertTrue(v.closing_due)
        self.assertEqual(v.flexpack.state.phase, Phase.ENDED)

    def test_a_late_press_spills_into_the_evening_and_says_what_it_costs(self):
        v = view(at(13, 0), START, FlexDay(started_at=at(13, 0)))
        self.assertIsNotNone(v.plan.evening)
        self.assertEqual(v.plan.target, view(at(13, 0)).plan.target)

    def test_a_day_that_was_never_started_has_no_work_once_it_is_over(self):
        v = view(datetime(2026, 11, 10, 23, 59), START)
        self.assertTrue(v.flexpack.never_started)
        self.assertEqual(v.work, ())
        self.assertEqual(v.worked, timedelta(0))

    def test_no_work_days_have_no_button(self):
        v = view(at(9, 0), START, kind=DayKind.REST)
        self.assertIsNone(v.flexpack.state)
        self.assertFalse(v.flexpack.waiting)

    def test_the_static_planning_slot_gives_way_to_end_work(self):
        v = view(at(9, 0), START, FlexDay(started_at=at(8, 0)))
        self.assertIsNone(v.schedule.planning)


# --------------------------------------------------------------------------
# Flexible blocks
# --------------------------------------------------------------------------

BLOCKS = FlexSettings(enabled=True, routine=False, manual_start=False, blocks=True, nothing=False)
POMO = PomodoroSettings()  # 50 / 10 / 30, long break after 3


def state(runs, now, **kw):
    started = runs[0].start if runs else None
    return flex_state(FlexDay(started, kw.pop("ended", None), tuple(runs)), now=now, pauses=kw.pop("pauses", ()),
                      pomodoro=kw.pop("pomodoro", POMO), target=kw.pop("target", timedelta(hours=5)),
                      deadline=kw.pop("deadline", None), settings=kw.pop("settings", BLOCKS))


class BlockTests(unittest.TestCase):
    def test_nothing_started_is_ready_for_a_focus_block(self):
        s = state([], at(8))
        self.assertEqual((s.phase, s.next_kind, s.nominal), (Phase.READY, F, 50))

    def test_with_manual_start_the_same_moment_is_waiting(self):
        s = state([], at(8), settings=FlexSettings(enabled=True, manual_start=True, blocks=True))
        self.assertEqual(s.phase, Phase.WAITING)

    def test_a_running_block_counts_down_then_runs_over(self):
        runs = [Run(F, at(8, 0), None, 1)]
        s = state(runs, at(8, 20))
        self.assertEqual((s.phase, s.current.kind, s.left, s.over), (Phase.RUNNING, F, timedelta(minutes=30), False))
        over = state(runs, at(8, 58))
        self.assertEqual(over.left, timedelta(minutes=-8))
        self.assertTrue(over.over)  # it never stops by itself: you work more, or you stop it

    def test_stopping_early_is_ready_for_the_break_and_counts_the_real_time(self):
        s = state([Run(F, at(8, 0), at(8, 20), 1)], at(8, 21))
        self.assertEqual((s.phase, s.next_kind, s.nominal), (Phase.READY, S, 10))
        self.assertEqual(s.worked, timedelta(minutes=20))
        self.assertEqual(s.idle_since, at(8, 20))

    def test_stopping_late_counts_the_extra_work(self):
        s = state([Run(F, at(8, 0), at(9, 10), 1)], at(9, 11))
        self.assertEqual(s.worked, timedelta(minutes=70))

    def test_breaks_do_not_count_as_work(self):
        runs = [Run(F, at(8, 0), at(8, 50), 1), Run(S, at(8, 50), at(9, 0), 2), Run(F, at(9, 0), None, 3)]
        s = state(runs, at(9, 25))
        self.assertEqual(s.worked, timedelta(minutes=75))
        self.assertEqual(s.focus_blocks, 2)

    def test_the_third_block_earns_a_long_break_then_the_cycle_restarts(self):
        runs = [Run(F, at(8, 0), at(8, 50)), Run(S, at(8, 50), at(9, 0)), Run(F, at(9, 0), at(9, 50)),
                Run(S, at(9, 50), at(10, 0)), Run(F, at(10, 0), at(10, 50))]
        self.assertEqual(next_kind(runs, POMO), L)
        runs += [Run(L, at(10, 50), at(11, 20))]
        self.assertEqual(next_kind(runs, POMO), F)
        runs += [Run(F, at(11, 20), at(12, 10))]
        self.assertEqual(next_kind(runs, POMO), S)  # the count began again after the long break

    def test_a_break_stopped_early_is_ready_for_focus(self):
        self.assertEqual(next_kind([Run(F, at(8), at(8, 50)), Run(S, at(8, 50), at(8, 53))], POMO), F)

    def test_breaks_switched_off_means_focus_again(self):
        no_breaks = PomodoroSettings(short_enabled=False, long_enabled=False)
        self.assertEqual(next_kind([Run(F, at(8), at(8, 50))], no_breaks), F)

    def test_pomodoro_off_is_one_stretch_of_all_that_is_left(self):
        off = PomodoroSettings(enabled=False)
        s = state([], at(8), pomodoro=off, target=timedelta(hours=4))
        self.assertEqual((s.next_kind, s.nominal), (F, 240))

    def test_pauses_are_not_work(self):
        gym = [Pause(Span(at(8, 30), at(9, 0)), "gym")]
        s = state([Run(F, at(8, 0), None, 1)], at(9, 10), pauses=gym)
        self.assertEqual(s.worked, timedelta(minutes=40))
        self.assertEqual(s.left, timedelta(minutes=10))

    def test_an_open_manual_pause_freezes_the_block(self):
        pause = [Pause(Span(at(8, 20), at(8, 40)), "your pause", manual=True, open=True)]
        s = state([Run(F, at(8, 0), None, 1)], at(8, 40), pauses=pause)
        self.assertEqual(s.left, timedelta(minutes=30))

    def test_the_target_is_reached_but_nothing_forces_the_end(self):
        s = state([Run(F, at(8, 0), at(9, 0))], at(9, 1), target=timedelta(minutes=55))
        self.assertTrue(s.target_reached)
        self.assertEqual(s.phase, Phase.READY)
        self.assertEqual(s.focus_left, timedelta(0))

    def test_end_work_ends_it_and_stops_the_clock(self):
        s = state([Run(F, at(8, 0), at(8, 40))], at(9, 0), ended=at(8, 40))
        self.assertEqual(s.phase, Phase.ENDED)
        self.assertEqual(s.worked, timedelta(minutes=40))

    def test_bedtime_ends_a_day_that_was_left_open_and_counts_nothing_past_it(self):
        bed = at(18, 14)
        s = state([Run(F, at(17, 0), None, 1)], at(22, 0), deadline=bed)
        self.assertEqual(s.phase, Phase.ENDED)
        self.assertEqual(s.worked, timedelta(hours=1, minutes=14))

    def test_the_projected_end_follows_the_cycle(self):
        # 2h of focus left from 08:00 with nothing running: 50 +10 +50 +10 +20 = 2h20
        s = state([], at(8), target=timedelta(hours=2))
        self.assertEqual(s.projected_end, at(10, 20))
        self.assertIsNone(state([], at(8), target=timedelta(0)).projected_end)

    def test_the_projection_counts_what_is_running(self):
        s = state([Run(F, at(8, 0), None, 1)], at(8, 30), target=timedelta(minutes=100))
        # 30 worked, 20 left in this block (08:50), a break (09:00), then the last 50 of focus.
        self.assertEqual(s.projected_end, at(9, 50))

    def test_blocks_in_a_started_day_with_manual_start_run_after_the_button(self):
        s = state([Run(F, at(8, 0), None, 1)], at(8, 5),
                  settings=FlexSettings(enabled=True, manual_start=True, blocks=True))
        self.assertEqual(s.phase, Phase.RUNNING)


class BlockViewTests(unittest.TestCase):
    def test_the_view_uses_the_real_time_worked(self):
        runs = (Run(F, at(8, 0), at(8, 20), 1),)
        v = view(at(8, 30), BLOCKS, FlexDay(at(8, 0), None, runs), routine=())
        self.assertEqual(v.worked, timedelta(minutes=20))
        self.assertEqual(v.flexpack.state.phase, Phase.READY)

    def test_the_only_alarm_is_the_end_of_the_running_block(self):
        runs = (Run(F, at(8, 0), None, 7),)
        v = view(at(8, 10), BLOCKS, FlexDay(at(8, 0), None, runs), routine=())
        self.assertEqual([(e.key, e.due) for e in v.pomodoro_events], [("flex:7", at(8, 50))])
        self.assertIn("stop when you are ready", v.pomodoro_events[0].title)

    def test_no_alarm_when_nothing_runs_or_while_paused(self):
        self.assertEqual(view(at(8, 10), BLOCKS, routine=()).pomodoro_events, ())
        runs = (Run(F, at(8, 0), None, 7),)
        paused = view(at(8, 10), BLOCKS, FlexDay(at(8, 0), None, runs), routine=(), manual=[(at(8, 5), None)])
        self.assertEqual(paused.pomodoro_events, ())

    def test_the_timeline_lists_each_block_that_really_ran(self):
        runs = (Run(F, at(8, 0), at(8, 52), 1), Run(S, at(8, 52), at(9, 0), 2), Run(F, at(9, 0), None, 3))
        v = view(at(9, 20), BLOCKS, FlexDay(at(8, 0), None, runs), routine=())
        rows = [(r.title, r.detail) for r in v.timeline if r.title in ("Focus", "Short break")]
        self.assertEqual(rows[0], ("Focus", "08:00–08:52 · 52 min"))
        self.assertEqual(rows[1], ("Short break", "08:52–09:00 · 8 min"))
        self.assertEqual(rows[2][1], "09:00–now · 20 min")

    def test_planning_follows_end_work(self):
        day = FlexDay(at(8, 0), at(13, 0), (Run(F, at(8, 0), at(13, 0), 1),))
        v = view(at(13, 5), BLOCKS, day, routine=())
        planning = [r for r in v.timeline if r.title == "Planning"]
        self.assertEqual([(r.start, r.end) for r in planning], [(at(13, 0), at(13, 30))])

    def test_the_planning_row_respects_the_planning_switch(self):
        day = FlexDay(at(8, 0), at(13, 0), (Run(F, at(8, 0), at(13, 0), 1),))
        v = view(at(13, 5), BLOCKS, day, routine=(), pomodoro=PomodoroSettings(planning_enabled=False))
        self.assertFalse([r for r in v.timeline if r.title == "Planning"])


# --------------------------------------------------------------------------
# Do nothing
# --------------------------------------------------------------------------


def nothing(where, minutes=20, at_time=time(15, 0), alarm=True, **kw):
    return FlexSettings(enabled=True, routine=False, blocks=False, nothing=True, nothing_minutes=minutes,
                        nothing_where=where, nothing_at=at_time, nothing_alarm=alarm, **kw)


class DoNothingTests(unittest.TestCase):
    def test_after_work_it_follows_planning(self):
        v = view(at(8), nothing(AFTER_WORK))
        planning = v.schedule.planning
        self.assertEqual(v.flexpack.nothing, Span(planning.end, planning.end + timedelta(minutes=20)))
        self.assertEqual(v.flexpack.nothing_note, "")

    def test_after_work_with_planning_off_follows_the_last_block(self):
        v = view(at(8), nothing(AFTER_WORK), pomodoro=PomodoroSettings(planning_enabled=False))
        self.assertEqual(v.flexpack.nothing.start, v.work[-1].progress.end)

    def test_after_work_when_you_end_it_yourself_waits_for_you(self):
        both = nothing(AFTER_WORK, manual_start=True)
        before = view(at(9), both, FlexDay(started_at=at(8)))
        self.assertEqual(before.flexpack.nothing_note, "after you end work")
        self.assertFalse([e for e in before.pomodoro_events if e.key.startswith("nothing")])
        after = view(at(13, 10), both, FlexDay(at(8), at(13, 0)))
        self.assertEqual(after.flexpack.nothing.start, at(13, 30))  # after the 30 minutes of planning
        self.assertEqual(after.flexpack.nothing_note, "")

    def test_a_fixed_time_is_a_pause_like_the_gym(self):
        plain = view(at(8))
        v = view(at(8), nothing(FIXED_TIME, at_time=time(10, 0)))
        self.assertEqual(v.flexpack.nothing, Span(at(10, 0), at(10, 20)))
        self.assertIn(Pause(Span(at(10, 0), at(10, 20)), "Do nothing"), v.pauses)
        self.assertEqual(v.work[0].progress.end - plain.work[0].progress.end, timedelta(minutes=20))

    def test_a_fixed_time_outside_work_changes_no_work(self):
        plain = view(at(8))
        v = view(at(8), nothing(FIXED_TIME, at_time=time(16, 0)))
        self.assertEqual(v.work[0].progress.end, plain.work[0].progress.end)

    def test_before_work_it_sits_between_the_routine_and_the_work(self):
        s = FlexSettings(enabled=True, routine=True, buffer=0, blocks=False, nothing=True,
                         nothing_minutes=15, nothing_where=BEFORE_WORK)
        v = view(at(5, 30), s)
        self.assertEqual(v.flexpack.routine.end, at(6, 4))
        self.assertEqual(v.flexpack.nothing, Span(at(6, 4), at(6, 19)))
        self.assertEqual(v.work[0].progress.start, at(6, 19))

    def test_on_a_rest_day_it_keeps_a_fixed_time(self):
        v = view(at(9), nothing(AFTER_WORK, at_time=time(15, 30)), kind=DayKind.REST)
        self.assertEqual(v.flexpack.nothing, Span(at(15, 30), at(15, 50)))

    def test_it_rings_at_both_ends_unless_the_alarm_is_off(self):
        v = view(at(8), nothing(FIXED_TIME, at_time=time(16, 0)))
        keys = {e.key: e.due for e in v.pomodoro_events if e.key.startswith("nothing")}
        self.assertEqual(keys, {"nothing:start": at(16, 0), "nothing:end": at(16, 20)})
        quiet = view(at(8), nothing(FIXED_TIME, at_time=time(16, 0), alarm=False))
        self.assertFalse([e for e in quiet.pomodoro_events if e.key.startswith("nothing")])

    def test_it_is_on_the_timeline_with_its_rule(self):
        v = view(at(8), nothing(FIXED_TIME, at_time=time(16, 0)))
        row = next(r for r in v.timeline if r.slot is Slot.NOTHING)
        self.assertEqual((row.title, row.detail), ("Do nothing", "16:00–16:20 · 20 min · computer off"))

    def test_switched_off_there_is_none(self):
        s = FlexSettings(enabled=True, nothing=False, blocks=False)
        self.assertIsNone(view(at(8), s).flexpack.nothing)

    def test_the_routine_over_reminder_only_exists_while_waiting_for_start(self):
        s = FlexSettings(enabled=True, routine=True, manual_start=True, blocks=False, nothing=False, buffer=0)
        waiting = view(at(5, 30), s)
        self.assertIn("flex:routine-over", [e.key for e in waiting.pomodoro_events])
        started = view(at(6, 10), s, FlexDay(started_at=at(6, 5)))
        self.assertNotIn("flex:routine-over", [e.key for e in started.pomodoro_events])


# --------------------------------------------------------------------------
# The database and the buttons
# --------------------------------------------------------------------------


class DatabaseTests(DbTestCase):
    def test_routine_items_keep_their_order_and_can_move(self):
        db = self.db
        a, b, c = (RoutineItem(t, m) for t, m in (("a", 10), ("b", 20), ("c", 30)))
        for item in (a, b, c):
            db.save_routine_item(item)
        self.assertEqual([i.title for i in db.routine_items()], ["a", "b", "c"])
        self.assertTrue(db.move_routine_item(c, -1))
        self.assertEqual([i.title for i in db.routine_items()], ["a", "c", "b"])
        self.assertFalse(db.move_routine_item(a, -1))
        a.title, a.minutes, a.enabled = "A!", 15, False
        db.save_routine_item(a)
        self.assertEqual([(i.title, i.minutes, i.enabled) for i in db.routine_items()][0], ("A!", 15, False))
        db.delete_routine_item(b.id)
        self.assertEqual([i.title for i in db.routine_items()], ["A!", "c"])

    def test_a_bad_step_is_refused(self):
        with self.assertRaises(ValueError):
            self.db.save_routine_item(RoutineItem("", 10))
        with self.assertRaises(ValueError):
            self.db.save_routine_item(RoutineItem("x", 0))

    def test_only_the_first_press_of_start_counts(self):
        self.assertTrue(self.db.start_flex_day(D, at(7, 30)))
        self.assertFalse(self.db.start_flex_day(D, at(9, 0)))
        self.assertEqual(self.db.flex_day(D).started_at, at(7, 30))

    def test_blocks_round_trip_and_only_one_runs_at_a_time(self):
        db = self.db
        first = db.start_flex_run(D, F, at(8))
        self.assertIsNotNone(first)
        self.assertIsNone(db.start_flex_run(D, S, at(8, 10)))
        self.assertTrue(db.stop_flex_run(D, at(8, 50)))
        self.assertFalse(db.stop_flex_run(D, at(8, 51)))
        db.start_flex_run(D, S, at(8, 52))
        day = db.flex_day(D)
        self.assertEqual(day.started_at, at(8))  # the first block is also the start of the day
        self.assertEqual([(r.kind, r.start, r.stop) for r in day.runs], [(F, at(8), at(8, 50)), (S, at(8, 52), None)])

    def test_end_stops_a_running_block_and_can_be_taken_back(self):
        db = self.db
        db.start_flex_run(D, F, at(8))
        db.end_flex_day(D, at(9))
        day = db.flex_day(D)
        self.assertEqual((day.ended_at, day.runs[0].stop), (at(9), at(9)))
        db.reopen_flex_day(D)
        self.assertIsNone(db.flex_day(D).ended_at)

    def test_clearing_a_day_forgets_its_start_and_blocks(self):
        self.db.start_flex_run(D, F, at(8))
        self.db.clear_flex_day(D)
        self.assertEqual(self.db.flex_day(D), FlexDay())

    def test_the_calendar_query_returns_each_day_in_range(self):
        db = self.db
        db.start_flex_day(D, at(7))
        db.start_flex_day(D + timedelta(days=1), at(7) + timedelta(days=1))
        db.start_flex_day(D + timedelta(days=40), at(7) + timedelta(days=40))
        found = db.flex_days(D, D + timedelta(days=30))
        self.assertEqual(sorted(found), [D, D + timedelta(days=1)])

    def test_settings_round_trip_and_default_off(self):
        s = self.db.settings
        self.assertFalse(s.flex_pack)
        chosen = FlexSettings(True, False, 25, True, False, True, 30, FIXED_TIME, time(16, 45), False)
        s.flexibility = chosen
        self.assertEqual(s.flexibility, chosen)
        s.flex_pack = False
        self.assertFalse(s.flexibility.enabled)
        self.assertFalse(s.flexibility.use_routine)

    def test_out_of_range_values_are_clamped_and_junk_ignored(self):
        s = self.db.settings
        s.set("flex_buffer", "9999")
        s.set("flex_nothing_where", "somewhere")
        s.set("flex_nothing_at", "soon")
        f = s.flexibility
        self.assertEqual((f.buffer, f.nothing_where, f.nothing_at), (120, AFTER_WORK, time(15, 0)))

    def test_a_version_11_database_gains_the_tables_and_keeps_its_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            db = Database(path)
            with db.transaction() as conn:
                conn.execute("DROP TABLE routine_items")
                conn.execute("DROP TABLE flex_days")
                conn.execute("DROP TABLE flex_runs")
                conn.execute("PRAGMA user_version = 11")
            db.settings.set("theme", "dark")
            upgraded = Database(path)
            self.assertEqual(upgraded.routine_items(), [])
            self.assertEqual(upgraded.flex_day(D), FlexDay())
            self.assertEqual(upgraded.settings.theme, "dark")
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)


NOV2 = date(2026, 11, 2)


def moment(h, m=0):
    return datetime(2026, 11, 2, h, m)


class ButtonTests(DbTestCase):
    """The buttons, against the real timetable (2 November: Fajr 05:03, Isha 18:20)."""

    def setUp(self):
        super().setUp()
        self.library = PrayerLibrary()

    def pack(self, **kw):
        base = dict(enabled=True, routine=False, manual_start=True, blocks=True, nothing=False)
        self.db.settings.flexibility = FlexSettings(**{**base, **kw})

    def test_they_do_nothing_while_the_pack_is_off(self):
        self.assertFalse(planner.start_work(self.db, self.library, moment(8)))
        self.assertFalse(planner.end_work(self.db, moment(9)))
        self.assertFalse(planner.stop_block(self.db, moment(9)))
        self.assertEqual(self.db.flex_day(NOV2), FlexDay())

    def test_start_work_records_the_day_and_begins_the_first_block(self):
        self.pack()
        self.assertTrue(planner.start_work(self.db, self.library, moment(7, 30)))
        day = self.db.flex_day(NOV2)
        self.assertEqual(day.started_at, moment(7, 30))
        self.assertEqual([(r.kind, r.open) for r in day.runs], [(F, True)])

    def test_with_blocks_off_start_work_only_records_the_start(self):
        self.pack(blocks=False)
        planner.start_work(self.db, self.library, moment(7, 30))
        day = self.db.flex_day(NOV2)
        self.assertEqual((day.started_at, day.runs), (moment(7, 30), ()))

    def test_stop_then_start_walks_the_cycle(self):
        self.pack()
        planner.start_work(self.db, self.library, moment(7, 30))
        self.assertTrue(planner.stop_block(self.db, moment(8, 10)))  # worked less than planned
        self.assertTrue(planner.start_block(self.db, self.library, moment(8, 12)))
        self.assertEqual(self.db.flex_day(NOV2).runs[-1].kind, S)
        self.assertFalse(planner.start_block(self.db, self.library, moment(8, 13)))  # one at a time
        planner.stop_block(self.db, moment(8, 22))
        planner.start_block(self.db, self.library, moment(8, 23))
        self.assertEqual(self.db.flex_day(NOV2).runs[-1].kind, F)

    def test_end_work_then_resume(self):
        self.pack()
        planner.start_work(self.db, self.library, moment(7, 30))
        self.assertTrue(planner.end_work(self.db, moment(11)))
        self.assertFalse(planner.end_work(self.db, moment(11, 1)))
        self.assertFalse(planner.start_block(self.db, self.library, moment(11, 2)))
        self.assertTrue(planner.resume_work(self.db, moment(11, 5)))
        self.assertTrue(planner.start_block(self.db, self.library, moment(11, 6)))

    def test_end_work_needs_a_start(self):
        self.pack()
        self.assertFalse(planner.end_work(self.db, moment(11)))

    def test_the_built_view_follows_the_database(self):
        self.pack(routine=True, buffer=15)
        self.db.save_routine_item(RoutineItem("Breakfast", 30))
        waiting = planner.build_view(self.db, self.library, moment(5, 20))
        self.assertTrue(waiting.flexpack.waiting)
        self.assertEqual(waiting.flexpack.routine.end, moment(5, 48))
        planner.start_work(self.db, self.library, moment(5, 50))
        running = planner.build_view(self.db, self.library, moment(6, 10))
        self.assertEqual(running.flexpack.state.phase, Phase.RUNNING)
        self.assertEqual(running.worked, timedelta(minutes=20))
        planner.end_work(self.db, moment(6, 30))
        done = planner.build_view(self.db, self.library, moment(6, 31))
        self.assertTrue(done.closing_due)
        self.assertEqual(done.worked, timedelta(minutes=40))

    def test_turning_the_pack_off_puts_the_ordinary_day_back(self):
        self.pack(routine=True)
        self.db.save_routine_item(RoutineItem("Breakfast", 30))
        with_pack = planner.build_view(self.db, self.library, moment(8))
        self.db.settings.flex_pack = False
        without = planner.build_view(self.db, self.library, moment(8))
        self.assertIsNone(without.flexpack)
        self.assertEqual(without.work[0].progress.start, moment(5, 3))
        self.assertNotEqual(with_pack.work[0].progress.start, without.work[0].progress.start)

    def test_the_alarm_service_hears_the_pack(self):
        from fuzzy_journey import service

        # Pomodoro and planning are both off, so the service used to skip the day's own alarms entirely.
        self.pack(blocks=False, manual_start=False, nothing=True, nothing_where=FIXED_TIME,
                  nothing_at=time(7, 30), nothing_minutes=20)
        self.db.settings.pomodoro = PomodoroSettings(enabled=False, planning_enabled=False)
        rings = service.due_rings(self.db, self.library, moment(7, 31))
        self.assertIn("nothing:start", [r.key for r in rings])
        self.db.settings.flex_pack = False
        self.assertNotIn("nothing:end", [r.key for r in service.due_rings(self.db, self.library, moment(7, 51))])


class MixedTests(unittest.TestCase):
    def test_a_gym_session_during_a_flexible_block_is_not_work(self):
        gym = [activity("gym", "09:00", "09:30", "health")]
        runs = (Run(F, at(8, 30), None, 1),)
        v = view(at(9, 40), BLOCKS, FlexDay(at(8, 30), None, runs), routine=(), acts=gym)
        self.assertEqual(v.worked, timedelta(minutes=40))


if __name__ == "__main__":
    unittest.main()
