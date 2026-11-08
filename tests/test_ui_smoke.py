"""Builds the real window under a display and pokes it. Skipped when GTK 4 / libadwaita / a display is missing.

Run headless with:  xvfb-run -a python3 -m unittest tests.test_ui_smoke
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    Gtk.init_check()
    HAVE_GTK = Gdk.Display.get_default() is not None  # no display (plain CI shell) -> skip
except (ImportError, ValueError):
    HAVE_GTK = False


@unittest.skipUnless(HAVE_GTK, "GTK 4 / libadwaita / display not available")
def _buttons(row):
    """The Done / Tomorrow / Cancel buttons of one row in the review dialog."""
    found = []

    def walk(widget):
        child = widget.get_first_child()
        while child:
            if child.__class__.__name__ == "Button":
                found.append(child)
            walk(child)
            child = child.get_next_sibling()

    walk(row)
    return found


class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["FUZZY_JOURNEY_NOW"] = "2026-11-02T10:15"
        from fuzzy_journey import database, paths

        cls._saved = (database.DATABASE_PATH, paths.APP_DATA_DIR)
        database.DATABASE_PATH = Path(cls._tmp.name) / "ui.sqlite3"

        from fuzzy_journey.ui.app import Application
        from fuzzy_journey.ui.window import MainWindow

        cls.app = Application()
        cls.app.register(None)
        cls.window = MainWindow(cls.app)
        cls.ctx = cls.window.ctx
        cls.ctx.settings.welcome_seen = True

    @classmethod
    def tearDownClass(cls):
        from fuzzy_journey import database

        database.DATABASE_PATH = cls._saved[0]
        os.environ.pop("FUZZY_JOURNEY_NOW", None)
        cls.window.destroy()
        cls._tmp.cleanup()

    def test_every_page_renders_and_refreshes(self):
        self.assertEqual(list(self.window.pages), ["today", "tomorrow", "routine", "bank", "alarms", "prayers"])
        for scope in ("all", "tick", "day", "rhythm", "alarms", "data", "location", "tasks", "pomodoro"):
            self.ctx.changed(scope)

    def test_today_shows_the_bundled_day(self):
        page = self.window.pages["today"]
        self.assertEqual(page.stack.get_visible_child_name(), "day")
        self.assertIn("h", page.hero.get_text())  # "1h 56m"-style remaining work
        self.assertEqual(page.overline.get_text(), "WORK LEFT TODAY")

    def test_choosing_a_day_kind_updates_the_database_and_hero(self):
        from fuzzy_journey.rhythm import DayKind

        today = self.window.pages["today"]
        today.selector.emit("kind-selected", "off")
        self.assertIs(self.ctx.db.day_kind(date(2026, 11, 2)), DayKind.REST)
        self.assertEqual(today.hero.get_text(), "Rest day")
        today.selector.emit("kind-selected", "50")
        self.assertEqual(today.overline.get_text(), "WORK LEFT TODAY")

    def test_dialogs_build_and_save(self):
        from fuzzy_journey.ui.dialogs.activity_dialog import ActivityDialog
        from fuzzy_journey.ui.dialogs.alarm_dialog import AlarmDialog
        from fuzzy_journey.ui.dialogs.philosophy import PhilosophyDialog
        from fuzzy_journey.ui.dialogs.preferences import PreferencesWindow

        alarm = AlarmDialog(self.window, self.ctx)
        alarm.title_row.set_text("Smoke alarm")
        self.assertTrue(alarm.save())
        self.assertEqual([a.title for a in self.ctx.db.list_alarms()], ["Smoke alarm"])

        bad = AlarmDialog(self.window, self.ctx)
        bad.days.mask = 0
        self.assertFalse(bad.save())  # no weekday chosen is rejected, not saved

        activity = ActivityDialog(self.window, self.ctx)
        activity.title_row.set_text("Smoke walk")
        self.assertTrue(activity.save())
        self.assertEqual([a.title for a in self.ctx.db.list_activities()], ["Smoke walk"])

        for dialog in (alarm, bad, activity, PhilosophyDialog(self.window), PreferencesWindow(self.window, self.ctx)):
            dialog.destroy()

    def test_bank_selection_and_note(self):
        bank = self.window.pages["bank"]
        bank._select(date(2026, 11, 2))
        self.assertEqual(bank.day_title.get_text(), "Monday, 2 November 2026")

    # -- pomodoro, tasks, planning ------------------------------------------

    def test_tomorrow_opens_on_tomorrow_and_can_browse_any_day(self):
        page = self.window.pages["tomorrow"]
        self.assertEqual(page.selected, date(2026, 11, 3))
        self.assertIn("TOMORROW", page.overline.get_text())
        self.assertIn("h", page.hero.get_text())
        for day in (date(2026, 10, 20), date(2026, 11, 2), date(2026, 12, 1)):  # past, today, future
            page._go(day)
            self.assertEqual(page.selected, day)
            self.assertIn(day.strftime("%A"), page.overline.get_text())
        page._go(date(2026, 11, 3))

    def test_a_days_tasks_can_never_exceed_its_focus_time(self):
        from fuzzy_journey.ui.dialogs.task_dialog import TaskDialog

        day = date(2026, 11, 3)
        focus = self.ctx.day_view(day).schedule.focus_minutes
        self.assertGreater(focus, 0)
        ok = TaskDialog(self.window, self.ctx, day, focus)
        ok.title_row.set_text("Write the chapter")
        ok.length.set_value(37)  # snaps to a five-minute step
        self.assertTrue(ok.save())
        saved = self.ctx.db.tasks_on(day, prayers=False)
        self.assertEqual([(t.title, t.minutes) for t in saved], [("Write the chapter", 35)])
        too_long = TaskDialog(self.window, self.ctx, day, focus)
        too_long.title_row.set_text("Too much")
        too_long.length.set_value(360)
        self.assertFalse(too_long.save())
        self.assertEqual(len(self.ctx.db.tasks_on(day, prayers=False)), 1)
        for t in saved:
            self.ctx.db.delete_task(t.id)
        self.ctx.changed("tasks")

    def test_carrying_a_task_puts_it_on_tomorrows_page(self):
        from fuzzy_journey.models import Task, TaskStatus

        today, tomorrow = date(2026, 11, 2), date(2026, 11, 3)
        tid = self.ctx.db.save_task(Task("Unfinished", 45, today))
        self.window.pages["today"].tasks._set(self.ctx.db.tasks_on(today, prayers=False)[0], TaskStatus.CARRIED)
        self.assertEqual([t.title for t in self.ctx.db.tasks_on(tomorrow, prayers=False)], ["Unfinished"])
        self.assertIs(self.ctx.db.tasks_on(tomorrow, prayers=False)[0].status, TaskStatus.UNSET)
        self.window.pages["today"].tasks._set(self.ctx.db.tasks_on(today, prayers=False)[0], TaskStatus.DONE)
        self.assertEqual(self.ctx.db.tasks_on(tomorrow, prayers=False), [])
        self.ctx.db.delete_task(tid)
        self.ctx.changed("tasks")

    def test_the_pomodoro_can_be_paused_and_resumed(self):
        today = date(2026, 11, 2)
        card = self.window.pages["today"].card
        self.assertTrue(card.get_visible())
        self.assertEqual(card.pause.get_label(), "Pause")
        card._on_pause(None)
        self.assertEqual(self.ctx.db.pomodoro_pauses(today)[0][1], None)
        self.assertEqual(card.pause.get_label(), "Resume")
        self.assertEqual(card.overline.get_text(), "PAUSED")
        card._on_pause(None)
        self.assertIsNotNone(self.ctx.db.pomodoro_pauses(today)[0][1])
        self.assertEqual(card.pause.get_label(), "Pause")
        with self.ctx.db.transaction() as conn:
            conn.execute("DELETE FROM pomodoro_pauses")
        self.ctx.changed("pomodoro")

    def test_unsettled_tasks_from_earlier_days_are_reviewed_first(self):
        from fuzzy_journey.models import Task, TaskStatus
        from fuzzy_journey.ui.dialogs.review_dialog import ReviewDialog

        stale = Task("Left over", 30, date(2026, 11, 1))
        self.ctx.db.save_task(stale)
        self.window._check_tasks()
        self.assertTrue(self.window.review_banner.get_revealed())
        dialog = ReviewDialog(self.window, self.ctx, date(2026, 11, 1))
        self.assertEqual(len(dialog._rows), 1)
        dialog._settle(stale, TaskStatus.CANCELLED)
        self.assertEqual(self.ctx.db.unset_tasks_before(date(2026, 11, 2)), [])
        self.assertFalse(self.window.review_banner.get_revealed())
        self.ctx.db.delete_task(stale.id)

    def test_focus_preferences_save_and_hide_what_is_off(self):
        from dataclasses import replace

        from fuzzy_journey.ui.dialogs.preferences import PreferencesWindow

        saved = self.ctx.settings.pomodoro
        prefs = PreferencesWindow(self.window, self.ctx)
        try:
            self.assertTrue(prefs.pomo_on.get_active() and prefs.long_row.get_visible())
            prefs.long_on.set_active(False)
            self.assertFalse(self.ctx.settings.pomodoro.long_enabled)
            self.assertTrue(self.ctx.settings.pomodoro.short_enabled)  # independent switches
            self.assertFalse(prefs.long_row.get_visible() or prefs.every_row.get_visible())
            prefs.focus_row.set_value(25)
            self.assertEqual(self.ctx.settings.pomodoro.focus, 25)
            prefs.pomo_on.set_active(False)
            self.assertFalse(prefs.focus_row.get_visible() or prefs.short_on.get_visible())
            card = self.window.pages["today"].card  # no pomodoro: nothing to pause, planning still comes
            self.assertFalse(card.pause.get_visible())
            self.assertIn("Planning", card.detail.get_text())
        finally:
            self.ctx.settings.pomodoro = replace(saved)
            self.ctx.changed("rhythm")
            prefs.destroy()
        self.assertEqual(self.ctx.settings.pomodoro, saved)

    def test_overslept_starts_the_day_later_and_can_be_undone(self):
        from datetime import time

        from fuzzy_journey.rhythm import DayKind
        from fuzzy_journey.ui.dialogs.recovered_dialog import RecoveredDialog

        today = self.window.pages["today"]
        self.assertTrue(today.overslept.get_visible() and today.selector.get_visible())
        self.assertFalse(today.recovered.get_visible())
        dialog = RecoveredDialog(self.window, self.ctx, date(2026, 11, 2))
        dialog.start.time = time(4, 0)  # before Fajr: refused, nothing saved
        self.assertFalse(dialog.save())
        self.assertIs(self.ctx.db.day_kind(date(2026, 11, 2)), DayKind.STEADY)
        dialog.start.time = time(10, 0)
        self.assertTrue(dialog.save())
        self.assertIs(self.ctx.db.day_kind(date(2026, 11, 2)), DayKind.RECOVERED)
        self.assertTrue(today.recovered.get_visible())
        self.assertFalse(today.selector.get_visible() or today.overslept.get_visible())
        self.assertIn("10:00", today.recovered.get_subtitle())
        self.assertEqual(today.card.timer.get_text()[2], ":")  # the pomodoro clock follows the new window
        today._on_undo(None)
        self.assertIs(self.ctx.db.day_kind(date(2026, 11, 2)), DayKind.STEADY)
        self.assertTrue(today.selector.get_visible() and today.overslept.get_visible())

    def test_night_work_asks_you_to_move_tasks_first_and_shows_its_cost(self):
        from fuzzy_journey.models import Task
        from fuzzy_journey.rhythm import DayKind
        from fuzzy_journey.ui.dialogs.overtime_dialog import OvertimeDialog

        day = date(2026, 11, 2)
        today = self.window.pages["today"]
        self.assertTrue(today.night_button.get_visible())
        self.assertFalse(today.night_row.get_visible())
        tid = self.ctx.db.save_task(Task("Still open", 45, day))

        dialog = OvertimeDialog(self.window, self.ctx, day)
        self.assertEqual(dialog.move.get_label(), "Move tasks to tomorrow")  # the better way is offered first
        self.assertFalse(dialog.save_button.get_visible() or dialog.revealer.get_reveal_child())  # hours need a 2nd step
        dialog._reveal()
        dialog.length.set_value(90)
        self.assertIn("given up", dialog.cost.get_text())
        self.assertIn("18:20 to 19:50", dialog.cost.get_text())
        dialog._on_save(None)
        self.assertEqual(self.ctx.db.day_entries(day, day)[day].overtime, 90)
        self.assertTrue(today.night_row.get_visible() and not today.night_button.get_visible())
        self.assertIn("not recommended", today.night_row.get_subtitle())
        self.assertIn("19:50", today.night_row.get_subtitle())

        change = OvertimeDialog(self.window, self.ctx, day, 90)  # changing skips the warning step
        self.assertTrue(change.save_button.get_visible() and change.revealer.get_reveal_child())
        change.length.set_value(60)
        change._on_save(None)
        self.assertEqual(self.ctx.db.day_entries(day, day)[day].overtime, 60)

        today._on_remove_night(None)
        self.assertEqual(self.ctx.db.day_entries(day, day)[day].overtime, 0)
        self.assertTrue(today.night_button.get_visible())

        again = OvertimeDialog(self.window, self.ctx, day)
        again._on_move(None)  # opens the settle dialog instead of adding hours
        self.assertEqual(self.ctx.db.day_entries(day, day)[day].overtime, 0)
        self.ctx.db.delete_task(tid)

        try:
            self.ctx.db.set_day_kind(day, DayKind.REST)  # no work, so nothing to add to
            self.ctx.changed("day")
            self.assertFalse(today.night_button.get_visible())
        finally:
            self.ctx.db.set_day_kind(day, DayKind.STEADY)
            self.ctx.changed("day")

    def test_prayers_are_one_folded_row_that_never_uses_focus_time(self):
        from fuzzy_journey.models import TaskStatus
        from fuzzy_journey.ui.dialogs.review_dialog import ReviewDialog

        today, tomorrow = date(2026, 11, 2), date(2026, 11, 3)
        page = self.window.pages["today"]
        first = page.tasks.list.get_row_at_index(0)
        self.assertEqual(first.get_title(), "Prayers")
        self.assertIn("of 5 done", first.get_subtitle())
        before = page.tasks.meter_label.get_text()
        fajr = next(t for t in self.ctx.db.tasks_on(today) if t.title == "Fajr")
        page.tasks._set(fajr, TaskStatus.DONE)
        self.assertIn("1 of 5 done", page.tasks.list.get_row_at_index(0).get_subtitle())
        self.assertEqual(page.tasks.meter_label.get_text(), before)  # focus time is untouched

        dhuhr = next(t for t in self.ctx.db.tasks_on(today) if t.title == "Dhuhr")
        page.tasks._set(dhuhr, TaskStatus.CARRIED)
        copy = next(t for t in self.ctx.db.tasks_on(tomorrow) if t.title == "Dhuhr" and t.origin_id)
        dialog = ReviewDialog(self.window, self.ctx, tomorrow)  # the copy may only be done or cancelled
        rows = [row for row in dialog._rows if row.get_title() == "Dhuhr"]
        self.assertEqual(len(rows), 2)  # tomorrow's own Dhuhr, and the one carried over from today
        own, carried = ([b.get_label() for b in _buttons(row)] for row in rows)
        self.assertEqual(own, ["Done", "Tomorrow", "Cancel"][:2])  # an original prayer may wait a day, not be cancelled
        self.assertEqual(carried, ["Done", "Cancel"])  # the copy has waited its day already
        dialog.destroy()
        self.ctx.db.set_task_status(dhuhr.id, TaskStatus.UNSET)
        self.ctx.db.set_task_status(fajr.id, TaskStatus.UNSET)
        self.assertIsNone(self.ctx.db.tasks_on(tomorrow) and next(
            (t for t in self.ctx.db.tasks_on(tomorrow) if t.id == copy.id), None))
        self.ctx.changed("tasks")

    def test_theme_switch(self):
        from fuzzy_journey.ui.dialogs.preferences import apply_theme

        for name in ("dark", "light", "system"):
            apply_theme(name)
        self.assertIsInstance(Adw.StyleManager.get_default(), Adw.StyleManager)


if __name__ == "__main__":
    unittest.main()
