from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fuzzy_journey import planner
from fuzzy_journey.pomodoro import SegmentKind
from fuzzy_journey.prayer_times import PrayerLibrary
from fuzzy_journey.rhythm import DayKind, plan_day, summarize_bank
from tests.helpers import DbTestCase

DAY = date(2026, 11, 2)
KW = {"fajr": time(5, 3), "isha": time(18, 20), "next_fajr": time(5, 5)}
HOUR_AND_HALF = timedelta(minutes=90)


def plan(kind=DayKind.STEADY, **kw):
    return plan_day(DAY, kind, **KW, **kw)


class RuleTests(DbTestCase):
    def test_night_work_starts_at_isha_and_is_paid_for_in_sleep(self):
        p = plan(overtime=HOUR_AND_HALF)
        self.assertEqual((p.overtime.start.time(), p.overtime.end.time()), (time(18, 20), time(19, 50)))
        self.assertEqual((p.bedtime.time(), p.sleep_lost), (time(19, 50), HOUR_AND_HALF))
        self.assertEqual(p.free.end.time(), time(18, 20))  # free time ends where night work begins
        self.assertEqual(p.sleep, plan().sleep - HOUR_AND_HALF)

    def test_without_it_nothing_changes(self):
        self.assertEqual(plan(overtime=timedelta(0)), plan())
        self.assertIsNone(plan().overtime)

    def test_it_follows_evening_work_instead_of_overlapping_it(self):
        push = plan(DayKind.PUSH)
        late = plan(DayKind.PUSH, overtime=HOUR_AND_HALF)
        self.assertEqual(late.overtime.start, push.evening.end)
        self.assertEqual(late.sleep_lost, push.sleep_lost + HOUR_AND_HALF)

    def test_it_works_on_a_recovered_day_and_never_on_a_rest_day(self):
        rec = plan(DayKind.RECOVERED, start=time(10, 0), overtime=HOUR_AND_HALF)
        self.assertEqual(rec.overtime.start.time(), time(18, 20))
        self.assertEqual(rec.morning.end.time(), time(14, 10))
        self.assertIsNone(plan(DayKind.REST, overtime=HOUR_AND_HALF).overtime)

    def test_it_is_neutral_for_the_bank(self):
        self.assertEqual(summarize_bank({DAY: DayKind.STEADY}, DAY, DAY).balance, 0)


class StorageTests(DbTestCase):
    def test_round_trip_and_removal(self):
        self.db.set_day_overtime(DAY, 90)
        entry = self.db.day_entries(DAY, DAY)[DAY]
        self.assertEqual((entry.overtime, entry.kind), (90, DayKind.STEADY))  # an unmarked day stays Steady
        self.db.set_day_overtime(DAY, 0)
        self.assertEqual(self.db.day_entries(DAY, DAY)[DAY].overtime, 0)

    def test_it_survives_changing_the_kind_but_not_a_rest_day(self):
        self.db.set_day_overtime(DAY, 120)
        self.db.set_day_kind(DAY, DayKind.PUSH, "note")
        self.assertEqual(self.db.day_entries(DAY, DAY)[DAY].overtime, 120)
        self.db.set_day_kind(DAY, DayKind.RECOVERED, "", time(10, 0))
        entry = self.db.day_entries(DAY, DAY)[DAY]
        self.assertEqual((entry.kind, entry.overtime), (DayKind.RECOVERED, 120))
        self.db.set_day_kind(DAY, DayKind.REST)
        self.assertEqual(self.db.day_entries(DAY, DAY)[DAY].overtime, 0)

    def test_each_day_has_its_own(self):
        self.db.set_day_overtime(DAY, 60)
        self.assertEqual(self.db.day_entries(DAY + timedelta(days=1), DAY + timedelta(days=1)), {})


class FollowTheWorkTests(DbTestCase):
    def test_pomodoro_alarms_planning_and_task_room_extend_into_the_night(self):
        library = PrayerLibrary()
        before = planner.build_view(self.db, library, datetime(2026, 11, 2, 10, 0))
        self.db.set_day_overtime(DAY, 120)
        after = planner.build_view(self.db, library, datetime(2026, 11, 2, 10, 0))
        self.assertEqual([w.title for w in after.work], ["Morning work", "Night work"])
        self.assertGreater(after.schedule.focus_minutes, before.schedule.focus_minutes)
        last = after.schedule.segments[-1]
        self.assertEqual((last.kind, last.end.time()), (SegmentKind.PLANNING, time(20, 20)))  # planning stays last
        self.assertEqual(after.bedtime.time(), time(20, 20))
        self.assertGreater(after.sleep_lost, timedelta(0))
        self.assertTrue(any(r.slot.value == "work" and r.title == "Night work" for r in after.timeline))

    def test_a_preview_does_not_save(self):
        view = planner.build_view(self.db, PrayerLibrary(), datetime(2026, 11, 2, 10, 0), overtime=60)
        self.assertEqual(view.plan.overtime.duration, timedelta(minutes=60))
        self.assertEqual(self.db.day_entries(DAY, DAY), {})
