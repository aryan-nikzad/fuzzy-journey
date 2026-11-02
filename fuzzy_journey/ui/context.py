"""Shared state for every page: the database, the timetable library and a change signal."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta

from .. import prayer_times
from ..database import Database
from ..prayer_times import PrayerLibrary
from ..rhythm import BankSummary, summarize_bank
from ..timeutil import now as clock_now
from ..today import TodayView, build_today
from .gi_setup import Adw, GLib, GObject


class Context(GObject.Object):
    """One per window. Pages read from it and call :meth:`changed` after they write."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self) -> None:
        super().__init__()
        self.db = Database()
        self.settings = self.db.settings
        self.library = PrayerLibrary()
        self.toasts: Adw.ToastOverlay | None = None
        self.show_page: Callable[[str], None] = lambda _name: None
        self._downloading = False

    # -- events ------------------------------------------------------------

    def changed(self, scope: str = "all") -> None:
        self.emit("changed", scope)

    def toast(self, text: str) -> None:
        if self.toasts:
            self.toasts.add_toast(Adw.Toast.new(text))

    # -- derived data ------------------------------------------------------

    @property
    def location(self):
        return self.settings.location

    def today_view(self, now: datetime | None = None) -> TodayView:
        now = now or clock_now()
        day = now.date()
        slug = self.location.slug
        tomorrow = self.library.day(slug, day + timedelta(days=1))
        return build_today(
            now,
            self.db.day_kind(day),
            prayer_day=self.library.day(slug, day),
            next_fajr=tomorrow.fajr if tomorrow else None,
            activities=self.db.list_activities(),
            reminders=self.db.list_alarms(),
            prayer_alarms=self.db.prayer_alarms(),
            evening_start=self.settings.evening_start,
            flex=self.settings.flex,
        )

    def bank(self, today: date | None = None) -> BankSummary:
        today = today or clock_now().date()
        start = self.settings.bank_start
        entries = {d: e.kind for d, e in self.db.day_entries(start, today).items()}
        return summarize_bank(entries, start, today)

    # -- downloads ---------------------------------------------------------

    @property
    def downloading(self) -> bool:
        return self._downloading

    def download_year(self, year: int, on_done: Callable[[bool, str], None]) -> None:
        """Download a year in a worker thread; ``on_done(ok, message)`` runs on the main loop."""
        if self._downloading:
            return
        self._downloading = True
        location = self.location
        evening, flex = self.settings.evening_start, self.settings.flex

        def work() -> None:
            try:
                result = prayer_times.download_year(location, year, evening_start=evening, flex=flex)
                ok, message = True, f"Saved {result.days} days of {year} for {location.name}."
            except (prayer_times.FetchError, OSError) as exc:
                ok, message = False, str(exc)

            def finish() -> bool:
                self._downloading = False
                on_done(ok, message)
                if ok:
                    self.changed("data")
                return GLib.SOURCE_REMOVE

            GLib.idle_add(finish)

        threading.Thread(target=work, daemon=True).start()
