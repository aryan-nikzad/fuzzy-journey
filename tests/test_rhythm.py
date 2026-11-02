from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

from fuzzy_journey.rhythm import (
    DayKind,
    WorkStatus,
    calculate_work_blocks,
    collect_pauses,
    finish_with_pauses,
    parse_evening_start,
    plan_day,
    summarize_bank,
    work_progress,
)
from tests.helpers import activity

D = date(2026, 1, 1)
FAJR, ISHA, NEXT_FAJR = time(5, 42), time(18, 20), time(5, 42)


class BankTests(unittest.TestCase):
    def test_two_push_days_earn_one_day_and_rest_can_create_debt(self):
        start = date(2026, 11, 2)
        entries = {date(2026, 11, 2): DayKind.PUSH, date(2026, 11, 3): DayKind.PUSH}
        self.assertEqual(summarize_bank(entries, start, date(2026, 11, 5)).balance, 1.0)
        entries[date(2026, 11, 4)] = DayKind.REST
        self.assertEqual(summarize_bank(entries, start, date(2026, 11, 5)).balance, 0.0)
        entries[date(2026, 11, 5)] = DayKind.REST
        bank = summarize_bank(entries, start, date(2026, 11, 5))
        self.assertEqual(bank.balance, -1.0)
        self.assertTrue(bank.in_debt)

    def test_days_outside_tracking_window_are_ignored(self):
        entries = {date(2026, 1, 1): DayKind.PUSH, date(2026, 3, 1): DayKind.PUSH}
        bank = summarize_bank(entries, date(2026, 2, 1), date(2026, 2, 10))
        self.assertEqual((bank.push_days, bank.balance), (0, 0.0))
        self.assertEqual(bank.steady_days, 10)

    def test_push_days_needed(self):
        none = summarize_bank({}, D, D)
        self.assertEqual(none.push_days_to_next_whole_day, 2)
        half = summarize_bank({D: DayKind.PUSH}, D, D)
        self.assertEqual(half.push_days_to_next_whole_day, 1)
        debt = summarize_bank({D: DayKind.REST}, D, D)
        self.assertEqual(debt.push_days_to_next_whole_day, 2)
        self.assertEqual(half.whole_rest_days, 0)


class PlanTests(unittest.TestCase):
    def plan(self, kind, **kw):
        return plan_day(D, kind, fajr=FAJR, isha=ISHA, next_fajr=NEXT_FAJR, **kw)

    def test_steady_day_fits_in_the_morning(self):
        plan = self.plan(DayKind.STEADY)
        self.assertEqual(plan.target, timedelta(hours=6, minutes=19))
        self.assertIsNone(plan.evening)
        self.assertEqual((plan.morning.start.time(), plan.morning.end.time()), (time(5, 42), time(12, 1)))
        self.assertEqual(plan.bedtime.time(), ISHA)
        self.assertEqual(plan.sleep_lost, timedelta(0))
        self.assertEqual(plan.free.start.time(), time(12, 1))

    def test_push_day_overflows_into_the_evening_and_costs_sleep(self):
        plan = self.plan(DayKind.PUSH)
        self.assertEqual(plan.morning.end.time(), time(14, 0))
        self.assertEqual((plan.evening.start.time(), plan.evening.end.time()), (time(18, 0), time(19, 10)))
        self.assertEqual(plan.bedtime.time(), time(19, 10))
        self.assertEqual(plan.sleep_lost, timedelta(minutes=50))
        self.assertEqual(plan.free.start.time(), time(14, 0))
        self.assertEqual(plan.free.end.time(), time(18, 0))

    def test_rest_day_has_no_work(self):
        plan = self.plan(DayKind.REST)
        self.assertEqual((plan.target, plan.blocks), (timedelta(0), ()))
        self.assertEqual(plan.bedtime.time(), ISHA)

    def test_evening_start_is_configurable(self):
        plan = self.plan(DayKind.PUSH, evening_start=time(19, 30))
        self.assertEqual(plan.evening.start.time(), time(19, 30))
        self.assertEqual(plan.bedtime.time(), time(20, 40))

    def test_empty_evening_does_not_delay_bedtime(self):
        plan = self.plan(DayKind.STEADY, evening_start=time(19, 30))
        self.assertIsNone(plan.evening)
        self.assertEqual(plan.bedtime.time(), ISHA)

    def test_flex_lands_in_the_morning_first(self):
        plan = self.plan(DayKind.STEADY, flex=timedelta(minutes=30))
        self.assertEqual(plan.morning.end.time(), time(12, 31))
        self.assertIsNone(plan.evening)

    def test_evening_work_past_midnight_is_handled(self):
        plan = self.plan(DayKind.PUSH, flex=timedelta(hours=7))
        self.assertGreater(plan.evening.end, datetime(2026, 1, 2, 0, 0))
        self.assertEqual(plan.bedtime, plan.evening.end)
        self.assertGreater(plan.sleep_lost, timedelta(hours=4))

    def test_parse_evening_start(self):
        self.assertEqual(parse_evening_start("19:30"), time(19, 30))
        for bad in ("25:00", "13:59", "abc"):
            with self.assertRaises(ValueError):
                parse_evening_start(bad)

    def test_calculate_work_blocks_matches_cli_contract(self):
        blocks = calculate_work_blocks(datetime(1900, 1, 1, 5, 42), datetime(1900, 1, 1, 18, 20), 0.75)
        self.assertEqual(blocks.block2_start.strftime("%H:%M"), "18:00")
        self.assertEqual(blocks.block2_end.strftime("%H:%M"), "19:10")


class WorkClockTests(unittest.TestCase):
    def test_call_during_work_extends_the_finish(self):
        # README example: 05:42-12:01 with a 07:30-08:00 call finishes at 12:31.
        start = datetime(2026, 1, 1, 5, 42)
        planned = timedelta(hours=6, minutes=19)
        pauses = collect_pauses([activity("Call", "07:30", "08:00")], D)
        self.assertEqual(finish_with_pauses(start, planned, pauses), datetime(2026, 1, 1, 12, 31))

    def test_long_activity_preserves_eight_hours_of_work(self):
        start = datetime(2026, 1, 1, 8, 0)
        pauses = collect_pauses([activity("Class", "10:00", "14:00")], D)
        self.assertEqual(finish_with_pauses(start, timedelta(hours=8), pauses), datetime(2026, 1, 1, 20, 0))

    def test_activity_ending_exactly_at_start_changes_nothing(self):
        start = datetime(2026, 1, 1, 8, 0)
        pauses = collect_pauses([activity("Call", "07:30", "08:00")], D)
        self.assertEqual(finish_with_pauses(start, timedelta(hours=2), pauses), datetime(2026, 1, 1, 10, 0))

    def test_disabled_and_work_activities_do_not_pause(self):
        items = [activity("Off", "07:30", "08:00", enabled=False), activity("Other work", "09:00", "10:00", "work")]
        self.assertEqual(collect_pauses(items, D), [])

    def test_overlapping_pauses_merge(self):
        items = [activity("A", "07:00", "08:00"), activity("B", "07:30", "08:30")]
        (pause,) = [p for p in collect_pauses(items, D) if p.span.start.date() == D]
        self.assertEqual((pause.span.start.hour, pause.span.end.hour, pause.title), (7, 8, "Other activity"))

    def test_progress_states(self):
        start = datetime(2026, 1, 1, 5, 42)
        planned = timedelta(hours=6, minutes=19)
        pauses = collect_pauses([activity("Call", "07:30", "08:00")], D)

        before = work_progress(start, planned, pauses, datetime(2026, 1, 1, 5, 0))
        self.assertEqual((before.status, before.remaining), (WorkStatus.UPCOMING, planned))

        paused = work_progress(start, planned, pauses, datetime(2026, 1, 1, 7, 45))
        self.assertEqual(paused.status, WorkStatus.PAUSED)
        self.assertEqual(paused.pause.title, "Call")
        self.assertEqual(paused.remaining, planned - timedelta(hours=1, minutes=48))

        active = work_progress(start, planned, pauses, datetime(2026, 1, 1, 9, 0))
        self.assertEqual(active.status, WorkStatus.ACTIVE)
        self.assertEqual(active.remaining, planned - timedelta(hours=2, minutes=48))

        done = work_progress(start, planned, pauses, datetime(2026, 1, 1, 12, 31))
        self.assertEqual((done.status, done.remaining), (WorkStatus.DONE, timedelta(0)))


if __name__ == "__main__":
    unittest.main()
