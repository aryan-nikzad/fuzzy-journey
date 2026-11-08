from __future__ import annotations

import os
from datetime import date, timedelta

from .. import sound
from ..meta import APP_NAME
from ..timeutil import now as clock_now
from . import service_control
from .context import Context
from .dialogs.preferences import apply_theme
from .gi_setup import Adw, GLib, GObject, Gtk
from .pages.base import Page

TICK_SECONDS = 15


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=APP_NAME, default_width=880, default_height=860)
        self.set_size_request(480, 480)
        self.ctx = Context()
        self.pages: dict[str, Page] = {}
        self._today = date.today()

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

    # -- pages -------------------------------------------------------------

    PAGES = (
        ("today", "Today", "weather-clear-symbolic"),
        ("tomorrow", "Tomorrow", "daytime-sunrise-symbolic"),
        ("routine", "Routine", "view-list-symbolic"),
        ("bank", "Bank", "x-office-calendar-symbolic"),
        ("alarms", "Alarms", "alarm-symbolic"),
        ("prayers", "Prayers", "weather-clear-night-symbolic"),
    )

    def _build_pages(self) -> None:
        from .pages.alarms import AlarmsPage
        from .pages.bank import BankPage
        from .pages.prayers import PrayersPage
        from .pages.routine import RoutinePage
        from .pages.today import TodayPage
        from .pages.tomorrow import TomorrowPage

        factories = {"today": TodayPage, "tomorrow": TomorrowPage, "routine": RoutinePage, "bank": BankPage,
                     "alarms": AlarmsPage, "prayers": PrayersPage}
        for name, title, icon in self.PAGES:
            page = factories[name](self.ctx)
            self.pages[name] = page
            self.stack.add_titled_with_icon(page, name, title, icon)

    def page_index(self, index: int) -> None:
        if 0 <= index < len(self.PAGES):
            self.show_page(self.PAGES[index][0])

    def show_page(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

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
        return GLib.SOURCE_CONTINUE

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

    def review_tasks(self) -> None:
        from .dialogs.review_dialog import ReviewDialog

        ReviewDialog(self, self.ctx, clock_now().date() - timedelta(days=1)).present()

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
        menu.append("Preferences", "app.preferences")
        menu.append("Philosophy", "app.philosophy")
        menu.append("About Fuzzy Journey", "app.about")
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                              tooltip_text="Main menu")
