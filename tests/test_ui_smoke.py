"""Builds the real window under a display and pokes it. Skipped when GTK 4 / libadwaita / a display is missing.

Run headless with:  xvfb-run -a python3 -m unittest tests.test_ui_smoke
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime
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
        self.assertEqual(list(self.window.pages), ["today", "tomorrow", "routine", "bank", "alarms", "prayers", "rules", "recovery", "recall", "habits"])
        for scope in ("all", "tick", "day", "rhythm", "alarms", "data", "location", "tasks", "pomodoro", "principles", "habits"):
            self.ctx.changed(scope)

    # -- rules and recovery ------------------------------------------------

    @staticmethod
    def _texts(widget) -> list[str]:
        found = []

        def walk(w):
            child = w.get_first_child()
            while child:
                if child.__class__.__name__ == "Label":
                    found.append(child.get_label())
                walk(child)
                child = child.get_next_sibling()

        walk(widget)
        return found

    def test_the_rules_page_shows_the_written_rules_and_follows_edits(self):
        from fuzzy_journey.principles import SECTION_RULES, Principle
        from fuzzy_journey.ui.dialogs.principle_dialog import PrincipleDialog

        page = self.window.pages["rules"]
        shown = self._texts(page.cards)
        self.assertIn("Computer-use boundary", shown)
        self.assertIn("The PC is for work only.", shown)
        self.assertIn("Disruption Mode", shown)
        before = len(self.ctx.db.list_principles(SECTION_RULES))

        dialog = PrincipleDialog(self.window, self.ctx, SECTION_RULES)
        dialog.title_row.set_text("Phone off at night")
        dialog.text.get_buffer().set_text("Off by 23:00.\nCharges outside the bedroom.")
        self.assertTrue(dialog.save())
        dialog.destroy()
        self.assertIn("Phone off at night", self._texts(page.cards))
        self.assertIn("Charges outside the bedroom.", self._texts(page.cards))

        item = self.ctx.db.list_principles(SECTION_RULES)[-1]
        edit = PrincipleDialog(self.window, self.ctx, SECTION_RULES, item)
        edit.title_row.set_text("")
        self.assertFalse(edit.save())  # a rule needs a title
        edit.destroy()
        self.ctx.db.delete_principle(item.id)
        self.ctx.changed("principles")
        self.assertEqual(len(self.ctx.db.list_principles(SECTION_RULES)), before)
        self.assertNotIn("Phone off at night", self._texts(page.cards))
        self.assertIsInstance(item, Principle)

    def test_the_recovery_page_lists_the_steps_in_order_and_can_test_memory(self):
        page = self.window.pages["recovery"]
        steps = self.ctx.db.list_principles("recovery")
        self.assertEqual(self._texts(page.list).count(steps[0].title), 1)
        self.assertIn("Check reality", self._texts(page.list))

        page.test.set_active(True)  # Test myself: titles and details are hidden
        hidden = self._texts(page.list)
        self.assertNotIn("Check reality", hidden)
        self.assertIn("Step 2", hidden)
        page._reveal(steps[1])
        self.assertIn("Check reality", self._texts(page.list))
        self.assertNotIn(steps[0].title, self._texts(page.list))

        page.test.set_active(False)  # leaving the mode shows everything again
        self.assertIn(steps[0].title, self._texts(page.list))

    def test_moving_a_recovery_step_reorders_the_page(self):
        page = self.window.pages["recovery"]
        steps = self.ctx.db.list_principles("recovery")
        self.ctx.db.move_principle(steps[0], 1)
        self.ctx.changed("principles")
        texts = [t for t in self._texts(page.list) if t in (steps[0].title, steps[1].title)]
        self.assertEqual(texts, [steps[1].title, steps[0].title])
        self.ctx.db.move_principle(steps[0], -1)
        self.ctx.changed("principles")

    # -- recall, disruption days, prayers and settling -----------------------

    def test_the_recall_page_hides_everything_until_tapped(self):
        page = self.window.pages["recall"]
        names = [r.item.cue for r in page._rows]
        self.assertIn("Rule 1", names)
        self.assertIn("Step 1", names)
        self.assertIn("Fajr", names)  # prayers are shown while they are switched on
        self.assertTrue(all(not r.revealed for r in page._rows))
        self.assertNotIn("Computer-use boundary", self._texts(page.groups))

        rule = next(r for r in page._rows if r.item.cue == "Rule 1")
        rule.emit("activated")
        self.assertIn("Computer-use boundary", self._texts(page.groups))
        self.assertIn("The PC is for work only.", rule.get_subtitle())
        page._hide_all(None)
        self.assertNotIn("Computer-use boundary", self._texts(page.groups))

    def test_recall_keeps_what_was_revealed_when_data_changes(self):
        page = self.window.pages["recall"]
        next(r for r in page._rows if r.item.cue == "Step 2").emit("activated")
        self.ctx.changed("tasks")
        again = next(r for r in page._rows if r.item.cue == "Step 2")
        self.assertTrue(again.revealed)
        page._hide_all(None)

    def test_recall_follows_the_prayers_setting_and_todays_tasks(self):
        from fuzzy_journey.models import Task

        page = self.window.pages["recall"]
        today = self.ctx.today_view().day
        task_id = self.ctx.db.save_task(Task("Write the report", 60, today))
        self.ctx.changed("tasks")
        self.assertIn("Write the report", [r.item.title for r in page._rows])
        self.ctx.db.delete_task(task_id)
        self.ctx.settings.show_prayers = False
        self.ctx.changed("tasks")
        self.assertNotIn("Fajr", [r.item.cue for r in page._rows])
        self.assertNotIn("Prayers", self._texts(self.window.pages["today"].tasks.list))
        self.ctx.settings.show_prayers = True
        self.ctx.changed("tasks")
        self.assertIn("Fajr", [r.item.cue for r in page._rows])

    def test_a_disruption_day_can_be_started_changed_and_undone_from_today(self):
        from fuzzy_journey.rhythm import DayKind
        from fuzzy_journey.ui.dialogs.disruption_dialog import DisruptionDialog

        page = self.window.pages["today"]
        day = self.ctx.today_view().day
        self.assertTrue(page.disrupt.get_visible())
        self.assertFalse(page.disruption.get_visible())

        dialog = DisruptionDialog(self.window, self.ctx, day)
        self.assertTrue(dialog.save())
        dialog.destroy()
        self.assertEqual(self.ctx.db.day_kind(day), DayKind.DISRUPTION)
        self.assertTrue(page.disruption.get_visible())
        self.assertFalse(page.selector.get_visible())
        self.assertFalse(page.night_button.get_visible())
        self.assertFalse(page.disrupt.get_visible())
        self.assertIn("25%", page.disruption.get_title())

        dialog = DisruptionDialog(self.window, self.ctx, day, DayKind.DISRUPTION)
        dialog.offline.set_active(True)
        self.assertTrue(dialog.save())
        dialog.destroy()
        self.assertEqual(self.ctx.db.day_kind(day), DayKind.OFFLINE)
        self.assertEqual(page.hero.get_text(), "Offline day")

        page._on_undo(None)
        self.assertEqual(self.ctx.db.day_kind(day), DayKind.STEADY)
        self.assertFalse(page.disruption.get_visible())
        self.assertTrue(page.selector.get_visible())

    def test_settling_is_always_reachable_and_warns_when_it_is_early(self):
        from datetime import timedelta

        page = self.window.pages["today"]
        footer = page.tasks
        self.assertTrue(footer.settle_day.get_visible())
        self.assertEqual(footer.settle_day.get_label(), "Settle today…")
        self.assertTrue(footer.settle_earlier.get_visible() and footer.plan_next.get_visible())

        view = self.ctx.today_view()  # 10:15: the morning's work is not over, so settling now is early
        self.assertGreater(view.closing_at, view.now)
        dialogs = Gtk.Window.list_toplevels()
        before = len(dialogs)
        self.window.settle_day(view.day)  # asks before opening anything
        asked = [w for w in Gtk.Window.list_toplevels()
                 if isinstance(w, Adw.MessageDialog) and "not over yet" in (w.get_body() or "")]
        self.assertTrue(asked, "an early settle must ask first")
        for w in Gtk.Window.list_toplevels()[before:]:
            w.destroy()

        self.window.settle_day(view.day - timedelta(days=1))  # a past day: the review (or "all settled")
        self.window.settle_day(view.day + timedelta(days=1))  # a future day only explains

        tomorrow = self.window.pages["tomorrow"]
        tomorrow.tasks.show_day(view.day + timedelta(days=1), 60)
        self.assertFalse(tomorrow.tasks.settle_day.get_visible())  # nothing to settle on a future day
        tomorrow.tasks.show_day(view.day - timedelta(days=1), 60)
        self.assertEqual(tomorrow.tasks.settle_day.get_label(), "Settle this day…")

    def test_an_early_closing_dialog_does_not_snooze_itself_when_dismissed(self):
        from fuzzy_journey.models import Task
        from fuzzy_journey.ui.dialogs.closing_dialog import ClosingDialog

        day = self.ctx.today_view().day
        task_id = self.ctx.db.save_task(Task("Still open", 30, day))
        dialog = ClosingDialog(self.window, self.ctx, day, early=True)
        self.assertFalse(dialog.later.get_visible())
        self.assertIn("not over yet", dialog.status.get_subtitle())
        dialog._on_close_request(dialog)
        self.assertIsNone(self.ctx.db.closing_state(day)[1])  # no "ask me again" was set
        dialog.destroy()
        self.ctx.db.delete_task(task_id)

    def test_self_test_tasks_appear_in_the_task_list_and_lead_to_recall(self):
        page = self.window.pages["today"]
        self.assertNotIn("Test myself", self._texts(page.tasks.list))
        self.ctx.settings.selftest_mode = "prayers"
        self.ctx.changed("tasks")  # 10:15: Fajr has passed, so one test is due
        self.assertIn("Test myself", self._texts(page.tasks.list))
        self.assertTrue(any(t.startswith("Test myself ·") for t in self._texts(page.tasks.list)))
        self.ctx.settings.selftest_mode = "off"
        self.ctx.changed("tasks")
        self.assertNotIn("Test myself", self._texts(page.tasks.list))
        with self.ctx.db.transaction() as conn:
            conn.execute("DELETE FROM tasks WHERE kind='selftest'")


    def test_the_habit_calendar_records_each_habit_on_its_own(self):
        from datetime import date

        page = self.window.pages["habits"]
        today = date(2026, 11, 2)
        self.assertEqual(page.selected, today)
        self.assertFalse(any(s.get_sensitive() for s in page.spins.values()))  # nothing happened yet

        page.checks["masturbation"].set_active(True)  # one habit only
        self.assertEqual(self.ctx.db.habit_counts(today, today)[today], {"masturbation": 1, "porn": 0})
        page.spins["masturbation"].set_value(3)
        page.checks["porn"].set_active(True)
        self.assertEqual(self.ctx.db.habit_counts(today, today)[today], {"masturbation": 3, "porn": 1})
        self.assertTrue(page.spins["masturbation"].get_sensitive())

        page.checks["masturbation"].set_active(False)
        self.assertEqual(self.ctx.db.habit_counts(today, today)[today], {"masturbation": 0, "porn": 1})
        page.checks["porn"].set_active(False)
        self.assertEqual(self.ctx.db.habit_counts(today, today), {})

    def test_habit_figures_wait_for_the_days_to_pass_and_a_new_start_date_keeps_marks(self):
        from datetime import date, timedelta

        page = self.window.pages["habits"]
        today = date(2026, 11, 2)
        for key in ("masturbation", "porn"):
            self.ctx.settings.set_habit_start(key, today - timedelta(days=3))
        self.ctx.changed("habits")
        self.assertIn("4 more days", page.groups["porn"]["week"].get_subtitle())
        self.assertIn("27 more days", page.groups["porn"]["month"].get_subtitle())

        self.ctx.db.set_habit_day(today - timedelta(days=2), {"porn": 2})
        self.ctx.settings.set_habit_start("porn", today - timedelta(days=10))
        self.ctx.changed("habits")
        self.assertIn("2 time", page.groups["porn"]["week"].get_subtitle())
        self.assertIn("4 more days", page.groups["masturbation"]["week"].get_subtitle())  # its own start
        self.ctx.settings.set_habit_start("porn", today - timedelta(days=1))  # moving later wipes nothing
        self.assertEqual(self.ctx.db.habit_counts(today - timedelta(days=2), today)[today - timedelta(days=2)]["porn"], 2)
        self.ctx.db.set_habit_day(today - timedelta(days=2), {})

    def test_the_habit_page_can_be_hidden_and_shown_again(self):
        stack_page = self.window.stack.get_page(self.window.pages["habits"])
        self.assertTrue(stack_page.get_visible())
        self.window.show_page("habits")
        self.ctx.settings.habit_calendar = False
        self.ctx.changed("habits")
        self.assertFalse(stack_page.get_visible())
        self.assertEqual(self.window.stack.get_visible_child_name(), "today")  # it does not strand you there
        self.ctx.settings.habit_calendar = True
        self.ctx.changed("habits")
        self.assertTrue(stack_page.get_visible())


    def test_closing_hides_into_the_tray_only_while_a_tray_really_exists(self):
        from types import SimpleNamespace

        app, window = self.app, self.window
        app.window = window
        self.addCleanup(setattr, app, "tray", None)
        self.addCleanup(setattr, app, "window", None)
        window.present()
        app.tray = SimpleNamespace(active=False)  # a desktop with no tray must never trap the window
        self.assertFalse(app._on_window_close(window))
        self.assertTrue(window.is_visible())
        app.tray = SimpleNamespace(active=True)
        self.assertTrue(app._on_window_close(window))  # handled: hidden, not destroyed
        self.assertFalse(window.is_visible())
        app.toggle_window()  # the tray icon was clicked
        self.assertTrue(window.is_visible())
        app.tray = None
        self.assertFalse(app._on_window_close(window))

    def test_the_tray_follows_its_setting(self):
        app = self.app
        self.assertIsNone(app.tray)
        self.ctx.settings.tray_icon = False
        app.apply_tray()
        self.assertIsNone(app.tray)
        self.assertFalse(self.ctx.settings.tray_icon)


    def _prefs(self):
        from fuzzy_journey.ui.dialogs.preferences import PreferencesWindow

        known = set(Gtk.Window.list_toplevels())
        prefs = PreferencesWindow(self.window, self.ctx)

        def cleanup() -> None:  # also close any message the window opened
            for w in Gtk.Window.list_toplevels():
                if w not in known:
                    w.destroy()

        self.addCleanup(cleanup)
        return prefs

    def test_preferences_can_back_up_and_restore_everything(self):
        from fuzzy_journey import backup as backup_module

        prefs = self._prefs()
        folder = Path(tempfile.mkdtemp())
        self.ctx.settings.selftest_hours = 6
        self.assertTrue(prefs.make_backup(folder / "mine"))  # no extension: ".zip" is added
        archive = folder / "mine.zip"
        self.assertTrue(archive.is_file())
        self.assertEqual(backup_module.read_backup_info(archive).schema, backup_module.SCHEMA_VERSION)

        self.ctx.settings.selftest_hours = 2  # changed after the backup
        original = backup_module.restore_backup  # keep the safety copy and sounds out of the real data folder
        backup_module.restore_backup = lambda db, src: original(
            db, src, sound_dir=folder / "sounds", safety_dir=folder / "safe")
        try:
            self.assertTrue(prefs.restore_backup(archive))
        finally:
            backup_module.restore_backup = original
        self.assertEqual(self.ctx.settings.selftest_hours, 6)  # back to what it was when saved
        self.assertTrue(list((folder / "safe").glob("before-restore-*.sqlite3")))

    def test_preferences_refuse_a_file_that_is_not_a_backup_and_change_nothing(self):
        prefs = self._prefs()
        junk = Path(tempfile.mkdtemp()) / "x.zip"
        junk.write_text("not a zip")
        before = self.ctx.settings.selftest_hours
        self.assertFalse(prefs.restore_backup(junk))
        self.assertEqual(self.ctx.settings.selftest_hours, before)

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

    # -- closing the day, evening work, work done --------------------------

    def _pin(self, stamp):
        saved = os.environ.get("FUZZY_JOURNEY_NOW")
        os.environ["FUZZY_JOURNEY_NOW"] = stamp
        self.addCleanup(lambda: os.environ.__setitem__("FUZZY_JOURNEY_NOW", saved) if saved
                        else os.environ.pop("FUZZY_JOURNEY_NOW", None))

    def _clear_dialogs(self):
        """Other tests leave windows open; the check-in rightly waits for them, so close them."""
        for w in Gtk.Window.list_toplevels():
            if w is not self.window and w.get_visible():
                w.destroy()
        self.window._closing = None

    def test_the_check_in_opens_once_when_work_is_over_and_settling_closes_the_day(self):
        from fuzzy_journey.models import Task, TaskStatus
        from fuzzy_journey.ui.dialogs.closing_dialog import ClosingDialog

        self._pin("2026-11-02T11:20")  # planning began at 11:11
        self._clear_dialogs()
        task = Task("Write the report", 30, date(2026, 11, 2))
        self.ctx.db.save_task(task)
        self.addCleanup(lambda: self.ctx.db.delete_task(task.id))
        self.window._check_closing()
        dialog = self.window._closing
        self.assertIsInstance(dialog, ClosingDialog)
        self.window._check_closing()
        self.assertIs(self.window._closing, dialog)  # never a second one on top
        self.assertEqual(len(dialog._rows), 1)
        self.assertTrue(dialog.evening_group.get_visible())
        self.assertIn("add new tasks for tomorrow", dialog.tomorrow_row.get_subtitle())
        dialog._settle(task, TaskStatus.DONE)
        self.assertEqual(dialog.status.get_title(), "Everything is settled")
        dialog._on_close_day(None)
        self.assertEqual(self.ctx.db.closing_state(date(2026, 11, 2)), (True, None))
        self.window._closing = None
        self.window._check_closing()
        self.assertIsNone(self.window._closing)  # nothing open, and the day is closed

    def test_escaping_the_check_in_only_asks_again_later(self):
        from datetime import datetime

        from fuzzy_journey.models import Task

        self._pin("2026-11-02T11:20")
        self._clear_dialogs()
        day = date(2026, 11, 2)
        task = Task("Still open", 30, day)
        self.ctx.db.save_task(task)
        self.addCleanup(lambda: (self.ctx.db.delete_task(task.id), self.ctx.db.snooze_closing(day, datetime(2000, 1, 1))))
        self.window._check_closing()
        dialog = self.window._closing
        dialog.close()
        closed, until = self.ctx.db.closing_state(day)
        self.assertFalse(closed)
        self.assertEqual(until, datetime(2026, 11, 2, 11, 50))
        self.window._closing = None
        self.window._check_closing()
        self.assertIsNone(self.window._closing)  # snoozed for half an hour
        self._pin("2026-11-02T11:51")
        self.window._check_closing()
        self.assertIsNotNone(self.window._closing)
        self.window._closing.destroy()
        self.window._closing = None

    def test_evening_work_can_be_added_changed_and_removed_from_the_today_page(self):
        from fuzzy_journey.ui.dialogs.evening_dialog import EveningDialog

        self._pin("2026-11-02T11:20")
        day, page = date(2026, 11, 2), self.window.pages["today"]
        self.assertTrue(page.evening_button.get_visible())
        dialog = EveningDialog(self.window, self.ctx, day, 0)
        dialog.length.set_value(60)
        self.assertTrue(dialog.save_button.get_sensitive())
        self.assertIn("given up", dialog.cost.get_text())  # it says what it costs
        dialog._on_save(None)
        self.assertEqual(self.ctx.db.day_entries(day, day)[day].evening, 60)
        self.assertTrue(page.evening_row.get_visible() and not page.evening_button.get_visible())
        self.assertIn("not recommended", page.evening_row.get_subtitle())
        page._on_remove_evening(None)
        self.assertTrue(page.evening_button.get_visible() and not page.evening_row.get_visible())

    def test_an_evening_that_already_started_cannot_be_added(self):
        from fuzzy_journey.ui.dialogs.evening_dialog import EveningDialog

        self._pin("2026-11-02T20:00")  # the evening block would have begun at 18:00
        dialog = EveningDialog(self.window, self.ctx, date(2026, 11, 2), 0)
        self.assertFalse(dialog.save_button.get_sensitive())
        self.assertIn("has passed", dialog.cost.get_text())
        dialog.destroy()

    def test_a_manual_pause_shows_paused_with_a_frozen_timer_and_resume(self):
        from datetime import datetime

        self._pin("2026-11-02T10:30")
        day, card = date(2026, 11, 2), self.window.pages["today"].card
        self.ctx.db.pause_pomodoro(day, datetime(2026, 11, 2, 10, 28))
        self.addCleanup(lambda: self.ctx.db.resume_pomodoro(day, datetime(2026, 11, 2, 10, 31)))
        self.ctx.changed("pomodoro")
        self.assertEqual(card.overline.get_text(), "PAUSED")
        self.assertEqual(card.pause.get_label(), "Resume")
        before = card.timer.get_text()
        self._pin("2026-11-02T10:34")
        self.ctx.changed("pomodoro")
        self.assertEqual(card.timer.get_text(), before)  # the block waits; nothing runs down
        self.assertEqual(self.window.pages["today"].hero_sub.get_text().startswith("Paused by you"), True)

    def test_the_bank_lists_the_work_done_in_the_chosen_units(self):
        from fuzzy_journey.ui.dialogs.preferences import PreferencesWindow

        self._pin("2026-11-02T11:20")
        self.window._record_progress()
        bank = self.window.pages["bank"]
        self.assertGreaterEqual(len(bank._done_rows), 1)
        shown = bank._done_rows[0].get_subtitle()
        self.assertEqual(shown.count("·"), 2)  # hours · percent · blocks
        prefs = PreferencesWindow(self.window, self.ctx)
        try:
            prefs._unit_rows["percent"].set_active(False)
            prefs._unit_rows["blocks"].set_active(False)
            self.assertEqual(self.ctx.settings.progress_units, ("hours",))
            prefs._unit_rows["hours"].set_active(False)  # something must stay on
            self.assertEqual(self.ctx.settings.progress_units, ("hours",))
            self.assertNotIn("·", bank._done_rows[0].get_subtitle())
        finally:
            self.ctx.settings.progress_units = ["hours", "percent", "blocks"]
            prefs.destroy()

    def test_the_tasks_meter_says_by_how_much_a_day_is_over(self):
        from fuzzy_journey.models import Task

        self._pin("2026-11-02T10:15")
        day, page = date(2026, 11, 2), self.window.pages["today"]
        focus = self.ctx.today_view().schedule.focus_minutes
        big = Task("Too big", focus + 45, day)
        self.ctx.db.save_task(big)
        self.addCleanup(lambda: (self.ctx.db.delete_task(big.id), self.ctx.changed("tasks")))
        self.ctx.changed("tasks")
        self.assertIn("over by 45m", page.tasks.meter_label.get_text())

    def test_the_judgement_call_switches_change_the_behaviour(self):
        from fuzzy_journey.models import Task
        from fuzzy_journey.ui.dialogs.preferences import PreferencesWindow

        self._pin("2026-11-02T11:20")
        self._clear_dialogs()
        day, page = date(2026, 11, 2), self.window.pages["today"]
        task = Task("Open task", 30, day)
        self.ctx.db.save_task(task)
        prefs = PreferencesWindow(self.window, self.ctx)

        def restore():
            for key, value in (("closing_prompt", True), ("evening_offer", True)):
                setattr(self.ctx.settings, key, value)
            self.ctx.db.delete_task(task.id)
            self.ctx.db.snooze_closing(day, datetime(2000, 1, 1))
            prefs.destroy()
            self.ctx.changed("day")
        self.addCleanup(restore)
        prefs._flag_rows["closing_prompt"].set_active(False)
        self.window._check_closing()
        self.assertIsNone(self.window._closing)  # it no longer asks by itself
        prefs._flag_rows["evening_offer"].set_active(False)
        self.assertFalse(page.evening_button.get_visible())
        prefs._flag_rows["evening_offer"].set_active(True)
        self.assertTrue(page.evening_button.get_visible())

    def test_theme_switch(self):
        from fuzzy_journey.ui.dialogs.preferences import apply_theme

        for name in ("dark", "light", "system"):
            apply_theme(name)
        self.assertIsInstance(Adw.StyleManager.get_default(), Adw.StyleManager)


if __name__ == "__main__":
    unittest.main()
