from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from fuzzy_journey import pomodoro, sound
from fuzzy_journey.models import Sound
from fuzzy_journey.pomodoro import PomodoroSettings, SegmentKind, build_schedule
from fuzzy_journey.rhythm import Pause, Span

START = datetime(2026, 11, 2, 6, 0)
F, S, L, P = SegmentKind.FOCUS, SegmentKind.SHORT, SegmentKind.LONG, SegmentKind.PLANNING


def kinds(schedule):
    return [(s.kind, s.minutes) for s in schedule.segments]


def work(minutes):
    return [(START, timedelta(minutes=minutes))]


class LayoutTests(unittest.TestCase):
    def test_the_requested_cycle(self):
        # 3 x 50 focus, short breaks between, then a 30 minute long break; planning last.
        s = build_schedule(work(200 + 200 + 30), [], PomodoroSettings())
        self.assertEqual(
            kinds(s)[:6], [(F, 50), (S, 10), (F, 50), (S, 10), (F, 50), (L, 30)]
        )
        self.assertEqual(kinds(s)[6:11], [(F, 50), (S, 10), (F, 50), (S, 10), (F, 50)])
        self.assertEqual([k for k, _ in kinds(s)[-2:]], [F, P])  # the cycle ends on focus, then planning
        self.assertEqual(s.focus_minutes, 300)

    def test_segments_are_back_to_back_and_inside_the_window(self):
        s = build_schedule(work(395), [], PomodoroSettings())
        for a, b in zip(s.segments, s.segments[1:]):
            self.assertLessEqual(a.end, b.start)
        self.assertEqual(s.segments[-1].end, START + timedelta(minutes=395))

    def test_no_trailing_break_and_tiny_leftovers_are_dropped(self):
        s = build_schedule(work(105), [], PomodoroSettings(planning_enabled=False))
        self.assertEqual(kinds(s), [(F, 50), (S, 10), (F, 45)])
        s = build_schedule(work(65), [], PomodoroSettings(planning_enabled=False))
        self.assertEqual(kinds(s), [(F, 50)])  # 15 left: a break would leave no room for another block

    def test_short_and_long_breaks_switch_off_independently(self):
        long_off = build_schedule(work(400), [], PomodoroSettings(long_enabled=False, planning_enabled=False))
        self.assertNotIn(L, [k for k, _ in kinds(long_off)])
        self.assertEqual(kinds(long_off)[:6], [(F, 50), (S, 10)] * 3)
        short_off = build_schedule(work(400), [], PomodoroSettings(short_enabled=False, planning_enabled=False))
        self.assertEqual(kinds(short_off)[:4], [(F, 50), (F, 50), (F, 50), (L, 30)])
        none = build_schedule(work(160), [], PomodoroSettings(short_enabled=False, long_enabled=False,
                                                              planning_enabled=False))
        self.assertTrue(all(k is F for k, _ in kinds(none)))

    def test_everything_is_adjustable(self):
        s = build_schedule(work(300), [], PomodoroSettings(focus=25, short=5, long=15, long_every=4,
                                                           planning_enabled=False))
        self.assertEqual(kinds(s)[:8], [(F, 25), (S, 5), (F, 25), (S, 5), (F, 25), (S, 5), (F, 25), (L, 15)])

    def test_pomodoro_off_keeps_planning_and_all_the_focus(self):
        s = build_schedule(work(240), [], PomodoroSettings(enabled=False))
        self.assertEqual(kinds(s), [(P, 30)])
        self.assertEqual(s.focus_minutes, 210)
        s = build_schedule(work(240), [], PomodoroSettings(enabled=False, planning_enabled=False))
        self.assertEqual((s.segments, s.focus_minutes), ((), 240))

    def test_planning_comes_off_the_end_of_the_last_block_only(self):
        both = [(START, timedelta(hours=3)), (START + timedelta(hours=12), timedelta(hours=2))]
        s = build_schedule(both, [], PomodoroSettings(enabled=False))
        self.assertEqual(s.planning.end, START + timedelta(hours=14))
        self.assertEqual(s.focus_minutes, 180 + 90)

    def test_an_interruption_moves_the_end_not_the_focus(self):
        call = Pause(Span(START + timedelta(minutes=20), START + timedelta(minutes=35)), "Call")
        s = build_schedule(work(120), [call], PomodoroSettings(planning_enabled=False))
        first = s.segments[0]
        self.assertEqual((first.minutes, first.end - first.start), (50, timedelta(minutes=65)))

    def test_recommended_is_ninety_percent(self):
        self.assertEqual(pomodoro.recommended(300), 270)
        self.assertEqual(pomodoro.recommended(298), 265)


class PauseTests(unittest.TestCase):
    def setUp(self):
        self.schedule = build_schedule(work(200), [], PomodoroSettings(planning_enabled=False))
        self.at = START + timedelta(minutes=20)

    def test_a_pause_moves_only_what_comes_after(self):
        pauses = [(self.at, self.at + timedelta(minutes=7))]
        live = pomodoro.live_segments(self.schedule, pauses, START + timedelta(hours=1))
        self.assertEqual(live[0].start, START)
        self.assertEqual(live[0].end, START + timedelta(minutes=57))
        self.assertEqual(live[1].start, START + timedelta(minutes=57))

    def test_focus_number_survives_a_resumed_pause(self):
        # Regression: the card looked the shifted block up in the unshifted schedule and crashed.
        pauses = [(self.at, self.at + timedelta(minutes=7))]
        now = START + timedelta(hours=1, minutes=20)  # inside the second focus block
        live = pomodoro.live_segments(self.schedule, pauses, now)
        cur = pomodoro.current(live, now)
        self.assertEqual(cur.kind, pomodoro.SegmentKind.FOCUS)
        self.assertNotIn((cur.start, cur.kind), [(s.start, s.kind) for s in self.schedule.segments])
        self.assertEqual(pomodoro.focus_number(live, cur), (2, 3))

    def test_while_paused_the_current_block_waits(self):
        now = self.at + timedelta(minutes=9)
        live = pomodoro.live_segments(self.schedule, [(self.at, None)], now)
        self.assertEqual(pomodoro.current(live, now), live[0])
        self.assertEqual(live[0].end - now, timedelta(minutes=30))  # still the 30 minutes left at the pause

    def test_nothing_rings_while_paused_and_alarms_shift_after_resuming(self):
        day = START.date()
        sound_ = Sound()
        open_ = pomodoro.schedule_events(self.schedule, [(self.at, None)], day, sound_)
        self.assertEqual([e.key for e in open_], ["pomo:0"])
        done = pomodoro.schedule_events(self.schedule, [(self.at, self.at + timedelta(minutes=5))], day, sound_)
        self.assertEqual(done[1].due, START + timedelta(minutes=55))

    def test_every_segment_and_the_end_of_work_ring(self):
        s = build_schedule(work(120), [], PomodoroSettings(planning_enabled=False))
        events = pomodoro.schedule_events(s, [], START.date(), Sound())
        self.assertEqual(len(events), len(s.segments) + 1)
        self.assertEqual(events[-1].title, "Focus finished")
        s = build_schedule(work(120), [], PomodoroSettings())
        events = pomodoro.schedule_events(s, [], START.date(), Sound())
        self.assertEqual(len(events), len(s.segments))  # planning start replaces "finished"

    def test_database_pauses_round_trip(self):
        from tests.helpers import DbTestCase  # noqa: F401  (imported for its temp-dir pattern)

        with tempfile.TemporaryDirectory() as tmp:
            from fuzzy_journey.database import Database

            db = Database(Path(tmp) / "p.sqlite3")
            day = START.date()
            db.pause_pomodoro(day, self.at)
            db.pause_pomodoro(day, self.at + timedelta(minutes=1))  # already paused: ignored
            self.assertEqual(db.pomodoro_pauses(day), [(self.at, None)])
            db.resume_pomodoro(day, self.at + timedelta(minutes=4))
            self.assertEqual(db.pomodoro_pauses(day), [(self.at, self.at + timedelta(minutes=4))])
            self.assertEqual(db.pomodoro_pauses(date(2026, 11, 3)), [])


class StopAlarmTests(unittest.TestCase):
    def test_stop_silences_a_playing_alarm(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = sound.RINGING_FILE
            sound.RINGING_FILE = Path(tmp) / "ringing.json"
            player = subprocess.Popen(["sleep", "97"], start_new_session=True)
            try:
                sound._write_ringing([{"pid": player.pid, "file": "97"}])
                self.assertTrue(sound.is_ringing())
                self.assertTrue(sound.stop_all())
                self.assertEqual(player.wait(timeout=5), -signal.SIGTERM)
                self.assertFalse(sound.is_ringing())
            finally:
                sound.RINGING_FILE = saved
                if player.poll() is None:
                    os.killpg(player.pid, signal.SIGKILL)

    def test_a_reused_pid_is_never_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = sound.RINGING_FILE
            sound.RINGING_FILE = Path(tmp) / "ringing.json"
            bystander = subprocess.Popen(["sleep", "96"], start_new_session=True)
            try:
                sound._write_ringing([{"pid": bystander.pid, "file": "/not/the/alarm.mp3"}])
                self.assertFalse(sound.is_ringing())
                self.assertFalse(sound.stop_all())
                self.assertIsNone(bystander.poll())
            finally:
                sound.RINGING_FILE = saved
                os.killpg(bystander.pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()


class ServiceTests(unittest.TestCase):
    """The alarm service rings each pomodoro boundary exactly once, and nothing while paused."""

    def setUp(self):
        from fuzzy_journey.database import Database
        from fuzzy_journey.prayer_times import PrayerLibrary

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db, self.library = Database(Path(self._tmp.name) / "s.sqlite3"), PrayerLibrary()

    def test_a_boundary_rings_once_with_its_own_title(self):
        from fuzzy_journey import service

        # The bundled day for 2 Nov 2026: focus 10:23-11:11 follows the short break.
        first = service.due_rings(self.db, self.library, datetime(2026, 11, 2, 10, 23, 5))
        self.assertEqual([r.title for r in first], ["Focus · 48 min"])
        self.assertEqual(service.due_rings(self.db, self.library, datetime(2026, 11, 2, 10, 23, 20)), [])

    def test_nothing_rings_while_paused_and_the_shifted_time_rings_after_resuming(self):
        from fuzzy_journey import service

        day = date(2026, 11, 2)
        self.db.pause_pomodoro(day, datetime(2026, 11, 2, 10, 15))
        self.assertEqual(service.due_rings(self.db, self.library, datetime(2026, 11, 2, 10, 23, 5)), [])
        self.db.resume_pomodoro(day, datetime(2026, 11, 2, 10, 20))  # five minutes of water
        self.assertEqual(service.due_rings(self.db, self.library, datetime(2026, 11, 2, 10, 23, 5)), [])
        late = service.due_rings(self.db, self.library, datetime(2026, 11, 2, 10, 28, 5))
        self.assertEqual([r.title for r in late], ["Focus · 48 min"])

    def test_pomodoro_off_still_rings_planning_and_planning_off_rings_nothing(self):
        from dataclasses import replace

        from fuzzy_journey import service

        s = self.db.settings
        s.pomodoro = replace(s.pomodoro, enabled=False)
        self.assertEqual(service.due_rings(self.db, self.library, datetime(2026, 11, 2, 10, 23, 5)), [])
        planning = service.due_rings(self.db, self.library, datetime(2026, 11, 2, 11, 11, 5))
        self.assertEqual([r.title for r in planning], ["Planning · 30 min"])
        s.pomodoro = replace(s.pomodoro, planning_enabled=False)
        self.assertEqual(service.due_rings(self.db, self.library, datetime(2026, 11, 2, 11, 41, 5)), [])


class PlayRecordsTests(unittest.TestCase):
    def test_a_started_alarm_can_be_found_and_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = (sound.RINGING_FILE, sound._player_command, sound.ensure_tone)
            sound.RINGING_FILE = Path(tmp) / "ringing.json"
            tone = Path(tmp) / "tone.wav"
            tone.write_bytes(b"")
            sound.ensure_tone = lambda key="classic": tone
            sound._player_command = lambda path: ["python3", "-c", "import time; time.sleep(60)", str(path)]
            try:
                self.assertFalse(sound.is_ringing())
                self.assertTrue(sound.play(Sound()))
                self.assertTrue(sound.is_ringing())
                self.assertTrue(sound.stop_all())
                for _ in range(50):  # the service reaps its player; give it a moment to exit
                    if not sound.is_ringing():
                        break
                    import time

                    time.sleep(0.05)
                self.assertFalse(sound.is_ringing())
            finally:
                for child in sound._children:
                    child.wait(timeout=5)
                sound._children.clear()
                sound.RINGING_FILE, sound._player_command, sound.ensure_tone = saved
