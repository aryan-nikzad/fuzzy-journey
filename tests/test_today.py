from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta

from fuzzy_journey.models import Alarm, PrayerAlarm
from fuzzy_journey.prayer_times import PrayerDay
from fuzzy_journey.rhythm import DayKind, WorkStatus
from fuzzy_journey.today import RowState, Slot, build_today
from tests.helpers import activity

DAY = date(2026, 1, 1)
PRAYERS = PrayerDay(DAY, {
    "Fajr": time(5, 42), "Sunrise": time(7, 8), "Dhuhr": time(12, 10),
    "Asr": time(14, 54), "Maghrib": time(17, 32), "Isha": time(18, 20),
})


def view(hour, minute, kind=DayKind.STEADY, *, acts=(), reminders=(), prayer_alarms=None, prayers=PRAYERS):
    return build_today(
        datetime(2026, 1, 1, hour, minute), kind, prayer_day=prayers, next_fajr=time(5, 42),
        activities=list(acts), reminders=list(reminders), prayer_alarms=prayer_alarms or {},
    )


class TodayTests(unittest.TestCase):
    def test_midmorning_steady_day(self):
        v = view(9, 0)
        self.assertEqual(v.focus.title, "Morning work")
        self.assertEqual(v.focus.progress.status, WorkStatus.ACTIVE)
        self.assertEqual(v.work_remaining, timedelta(hours=6, minutes=19) - timedelta(hours=3, minutes=18))
        self.assertEqual((v.wake.time(), v.bedtime.time()), (time(5, 42), time(18, 20)))

    def test_push_day_has_two_blocks_and_lost_sleep(self):
        v = view(9, 0, DayKind.PUSH)
        self.assertEqual([w.title for w in v.work], ["Morning work", "Evening work"])
        self.assertEqual(v.sleep_lost, timedelta(minutes=50))
        self.assertIn("50m given up", v.timeline[-1].detail)

    def test_rest_day_has_no_work(self):
        v = view(9, 0, DayKind.REST)
        self.assertEqual((v.work, v.work_remaining), ((), timedelta(0)))
        self.assertTrue(any(r.title == "Rest day" for r in v.timeline))

    def test_done_after_work(self):
        v = view(13, 0)
        self.assertTrue(v.work_done)
        self.assertEqual(v.work_remaining, timedelta(0))

    def test_call_pauses_work(self):
        v = view(7, 45, acts=[activity("Call", "07:30", "08:00")])
        self.assertEqual(v.focus.progress.status, WorkStatus.PAUSED)
        self.assertEqual(v.focus.progress.end.time(), time(12, 31))

    def test_timeline_is_ordered_and_marks_state(self):
        v = view(12, 30)
        times = [r.start for r in v.timeline]
        self.assertEqual(times, sorted(times))
        states = {r.title: r.state for r in v.timeline}
        self.assertEqual(states["Morning work"], RowState.PAST)
        self.assertEqual(states["Isha"], RowState.LATER)
        self.assertEqual(v.timeline[0].slot, Slot.WAKE)
        self.assertEqual(v.timeline[-1].slot, Slot.SLEEP)

    def test_alarms_are_flagged_and_next_alarm_found(self):
        v = view(9, 0, reminders=[Alarm("Vitamins", "10:00", id=1)],
                 prayer_alarms={"Dhuhr": PrayerAlarm("Dhuhr", True)})
        self.assertEqual(v.next_alarm.title, "Vitamins")
        flagged = {r.title for r in v.timeline if r.has_alarm}
        self.assertEqual(flagged, {"Vitamins", "Dhuhr"})

    def test_personal_sleep_and_wake_override_defaults(self):
        acts = [activity("Wake", "06:00", "06:15", "wake"), activity("Sleep", "22:30", "06:00", "sleep")]
        v = view(9, 0, acts=acts)
        self.assertEqual((v.wake.time(), v.bedtime.time()), (time(6, 0), time(22, 30)))
        self.assertEqual(v.sleep, timedelta(hours=7, minutes=30))

    def test_missing_prayer_data_still_shows_reminders(self):
        v = view(9, 0, prayers=None, reminders=[Alarm("Stretch", "10:00", id=2)])
        self.assertFalse(v.has_prayer_data)
        self.assertEqual([r.title for r in v.timeline], ["Stretch"])

    def test_segments_cover_the_day(self):
        v = view(9, 0, DayKind.PUSH)
        kinds = [s.kind for s in v.segments]
        self.assertEqual(kinds.count("work"), 2)
        self.assertEqual(kinds[0], "free")


if __name__ == "__main__":
    unittest.main()
