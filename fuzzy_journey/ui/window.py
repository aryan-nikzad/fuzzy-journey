from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from .. import planner, sound
from ..meta import APP_NAME
from ..timeutil import now as clock_now
from . import service_control
from .context import Context
from .dialogs.preferences import apply_theme
from .gi_setup import Adw, GLib, GObject, Gtk
from .pages.base import Page

TICK_SECONDS = 15
RECORD_EVERY = 4  # ticks: the day's real focus is written down once a minute

log = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=APP_NAME, default_width=880, default_height=860)
        self.set_size_request(480, 480)
        self.ctx = Context()
        self.pages: dict[str, Page] = {}
        self._today = date.today()
        self._ticks = 0
        self._closing = None  # the open check-in, so only one is ever shown

        self.stack = Adw.ViewStack(vexpand=True)
        self._build_pages()

        # Tabs in the header when they fit, in a bar at the bottom when the window is narrow.
        self.switcher = Adw.ViewSwitcherTitle(stack=self.stack, title=APP_NAME)
        self.switcher_bar = Adw.ViewSwitcherBar(stack=self.stack)
        self.switcher.bind_property("title-visible", self.switcher_bar, "reveal", GObject.BindingFlags.SYNC_CREATE)
        header = Adw.HeaderBar(title_widget=self.switcher)
        header.pack_end(self._menu_button())

        self.banner = Adw.Banner(title="Alarms won’t ring: the alarm service isn’t running.", button_label="Start")
        self.banner.connect("button-clicked", self._start_service)

        self.ring_banner = Adw.Banner(title="An alarm is ringing", button_label="Stop")
        self.ring_banner.connect("button-clicked", lambda _b: self.stop_alarm())
        self.review_banner = Adw.Banner(button_label="Settle")
        self.review_banner.connect("button-clicked", lambda _b: self.review_tasks())

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for banner in (self.ring_banner, self.review_banner, self.banner):
            body.append(banner)
        body.append(self.stack)

        self.toasts = Adw.ToastOverlay(child=body)
        self.ctx.toasts = self.toasts
        self.ctx.show_page = self.show_page

        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        view.add_bottom_bar(self.switcher_bar)
        self.set_content(view)

        start_page = os.environ.get("FUZZY_JOURNEY_PAGE")  # used by scripts/screenshots.sh
        if start_page in self.pages:
            self.show_page(start_page)
        self.ctx.connect("changed", self._on_changed)
        apply_theme(self.ctx.settings.theme)
        if not self.ctx.settings.welcome_seen:
            GLib.idle_add(self._welcome)
        GLib.timeout_add_seconds(TICK_SECONDS, self._tick)
        GLib.timeout_add_seconds(1, self._watch_alarm)
        self._check_service()
        self._check_tasks(prompt=True)
        GLib.idle_add(self._record_progress)

    # -- pages -------------------------------------------------------------

    PAGES = (
        ("today", "Today", "weather-clear-symbolic"),
        ("tomorrow", "Tomorrow", "daytime-sunrise-symbolic"),
        ("routine", "Routine", "view-list-symbolic"),
        ("bank", "Bank", "x-office-calendar-symbolic"),
        ("alarms", "Alarms", "alarm-symbolic"),
        ("prayers", "Prayers", "weather-clear-night-symbolic"),
        ("rules", "Rules", "checkbox-checked-symbolic"),
        ("recovery", "Recovery", "document-revert-symbolic"),
        ("recall", "Recall", "dialog-question-symbolic"),
        ("habits", "Habits", "view-grid-symbolic"),
        ("ideas", "Ideas", "starred-symbolic"),
        # Flexibility pack pages: hidden unless the pack is on. They sit last so no shortcut moves.
        ("morning", "Morning", "weather-few-clouds-symbolic"),
        ("worklog", "Work log", "document-open-recent-symbolic"),
    )

    def _build_pages(self) -> None:
        from .pages.alarms import AlarmsPage
        from .pages.bank import BankPage
        from .pages.habits import HabitsPage
        from .pages.ideas import IdeasPage
        from .pages.morning import MorningPage
        from .pages.worklog import WorkLogPage
        from .pages.prayers import PrayersPage
        from .pages.recall import RecallPage
        from .pages.recovery import RecoveryPage
        from .pages.routine import RoutinePage
        from .pages.rules import RulesPage
        from .pages.today import TodayPage
        from .pages.tomorrow import TomorrowPage

        factories = {"today": TodayPage, "tomorrow": TomorrowPage, "routine": RoutinePage, "bank": BankPage,
                     "alarms": AlarmsPage, "prayers": PrayersPage, "rules": RulesPage, "recovery": RecoveryPage,
                     "recall": RecallPage, "habits": HabitsPage, "ideas": IdeasPage,
                     "morning": MorningPage, "worklog": WorkLogPage}
        for name, title, icon in self.PAGES:
            page = factories[name](self.ctx)
            self.pages[name] = page
            self.stack.add_titled_with_icon(page, name, title, icon)
        self._show_habits()
        self._show_flex()

    def _show_flex(self) -> None:
        """The pack's pages exist only while the pack is on; turning it off hides them and deletes nothing."""
        fs = self.ctx.settings.flexibility
        for name, wanted in (("morning", fs.use_routine), ("worklog", fs.controls_work)):
            self.stack.get_page(self.pages[name]).set_visible(wanted)
            if not wanted and self.stack.get_visible_child() is self.pages[name]:
                self.show_page("today")

    def _show_habits(self) -> None:
        """The habit calendar is a page you can turn off; turning it off hides it and deletes nothing."""
        on = self.ctx.settings.habit_calendar
        self.stack.get_page(self.pages["habits"]).set_visible(on)
        if not on and self.stack.get_visible_child() is self.pages["habits"]:
            self.show_page("today")

    def page_index(self, index: int) -> None:
        if 0 <= index < len(self.PAGES):
            self.show_page(self.PAGES[index][0])

    def show_page(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

    def capture_idea(self) -> None:
        """Jump to the Idea Bank with the cursor in the quick-add line (Ctrl+I)."""
        self.show_page("ideas")
        self.pages["ideas"].focus_entry()

    def _welcome(self) -> bool:
        from .dialogs.philosophy import PhilosophyDialog

        def seen() -> None:
            self.ctx.settings.welcome_seen = True

        PhilosophyDialog(self, first_run=True, on_done=seen).present()
        return GLib.SOURCE_REMOVE

    # -- events ------------------------------------------------------------

    def _on_changed(self, _ctx, scope: str) -> None:
        for page in self.pages.values():
            if page.wants(scope):
                page.refresh()
        if scope in ("habits", "all"):
            self._show_habits()
        if scope in ("flex", "all"):
            self._show_flex()
        if scope in ("alarms", "all"):
            self._check_service()
        if scope in ("tasks", "all"):
            self._check_tasks()

    def _tick(self) -> bool:
        if date.today() != self._today:
            self._today = date.today()
            self.ctx.changed("all")
            self._check_tasks(prompt=True)
        else:
            self.ctx.changed("tick")
        self._check_service()
        self._ticks += 1
        if self._ticks % RECORD_EVERY == 0:
            self._record_progress()
        self._check_closing()
        return GLib.SOURCE_CONTINUE

    def _record_progress(self) -> bool:
        """Write down the focus today's clock has run, for the work-done figures on the Bank page."""
        try:
            planner.record_progress(self.ctx.db, self.ctx.library, clock_now())
            self.ctx.changed("progress")
        except Exception:  # noqa: BLE001 - a bookkeeping failure must never disturb the day itself
            log.exception("Could not record today's progress")
        return GLib.SOURCE_REMOVE

    def _check_closing(self) -> None:
        """When the day's work is over and tasks are still open, ask what happened to them."""
        if self._closing is not None or not self.ctx.settings.welcome_seen:
            return
        if any(w is not self and w.get_visible() for w in Gtk.Window.list_toplevels()):
            return  # another dialog is open: do not stack one on top
        view = self.ctx.today_view()
        if not planner.closing_due(self.ctx.db, view, view.now):
            return
        from .dialogs.closing_dialog import ClosingDialog

        dialog = ClosingDialog(self, self.ctx, view.day)
        self._closing = dialog
        dialog.connect("destroy", lambda _d: setattr(self, "_closing", None))
        dialog.present()

    # -- tasks and alarms --------------------------------------------------

    def _check_tasks(self, prompt: bool = False) -> None:
        """Yesterday's tasks must be settled before today's plan means anything."""
        today = clock_now().date()
        for day in (today, today + timedelta(days=1)):
            self.ctx.db.ensure_prayer_tasks(day)
        waiting = self.ctx.db.unset_tasks_before(today)
        n = len(waiting)
        self.review_banner.set_title(
            f"{n} task from an earlier day needs a status" if n == 1 else f"{n} tasks from earlier days need a status"
        )
        self.review_banner.set_revealed(n > 0)
        if prompt and n and self.ctx.settings.welcome_seen:
            GLib.idle_add(lambda: (self.review_tasks(), GLib.SOURCE_REMOVE)[1])

    def review_tasks(self, through: date | None = None) -> None:
        from .dialogs.review_dialog import ReviewDialog

        ReviewDialog(self, self.ctx, through or clock_now().date() - timedelta(days=1)).present()

    def settle_day(self, day: date) -> None:
        """Open the settling window for a day, whenever the person wants it, not only at its time.

        A past day opens the review of everything still without a status up to it. Today opens the
        closing check-in; if today's focus time is not over yet it first says so, and asks."""
        today = clock_now().date()
        if day < today:
            self.review_tasks(day)
            return
        if day > today:
            self.ctx.toast("That day has not come yet. Plan it on the Tomorrow page.")
            return
        from .dialogs.closing_dialog import ClosingDialog

        view = self.ctx.today_view()
        early = view.closing_at is not None and view.now < view.closing_at
        if not early:
            ClosingDialog(self, self.ctx, view.day).present()
            return
        ask = Adw.MessageDialog(
            transient_for=self, modal=True, heading="Settle today’s tasks now?",
            body=f"Your focus time for today is not over yet; it ends around {view.closing_at:%H:%M}. "
                 "You can settle now, but tasks you mark done or move on are decided early.",
        )
        ask.add_response("later", "Not yet")
        ask.add_response("now", "Settle now")
        ask.set_response_appearance("now", Adw.ResponseAppearance.SUGGESTED)
        ask.set_default_response("later")
        ask.set_close_response("later")
        ask.connect("response", lambda _d, r: ClosingDialog(self, self.ctx, view.day, early=True).present()
                    if r == "now" else None)
        ask.present()

    def stop_alarm(self) -> None:
        sound.stop_all()
        self.ring_banner.set_revealed(False)

    def _watch_alarm(self) -> bool:
        self.ring_banner.set_revealed(sound.is_ringing())
        return GLib.SOURCE_CONTINUE

    # -- service banner ----------------------------------------------------

    def _check_service(self) -> None:
        if os.environ.get("FUZZY_JOURNEY_DEMO"):  # screenshots: don't nag about systemd
            return
        service_control.is_active(lambda active: self.banner.set_revealed(active is False))

    def _start_service(self, _banner) -> None:
        def done(ok: bool) -> None:
            self.ctx.toast("Alarm service started" if ok else "Could not start the service. Run install.sh again.")
            self._check_service()

        service_control.start(done)

    # -- menu --------------------------------------------------------------

    def _menu_button(self) -> Gtk.MenuButton:
        from .gi_setup import Gio

        menu = Gio.Menu()
        menu.append("Settle today’s tasks…", "app.settle-today")
        menu.append("Settle earlier days…", "app.settle-earlier")
        menu.append("Preferences", "app.preferences")
        menu.append("Philosophy", "app.philosophy")
        menu.append("About Fuzzy Journey", "app.about")
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                              tooltip_text="Main menu")
