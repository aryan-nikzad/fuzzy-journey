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
        self.assertEqual(list(self.window.pages), ["today", "routine", "bank", "alarms", "prayers"])
        for scope in ("all", "tick", "day", "rhythm", "alarms", "data", "location"):
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

    def test_theme_switch(self):
        from fuzzy_journey.ui.dialogs.preferences import apply_theme

        for name in ("dark", "light", "system"):
            apply_theme(name)
        self.assertIsInstance(Adw.StyleManager.get_default(), Adw.StyleManager)


if __name__ == "__main__":
    unittest.main()
