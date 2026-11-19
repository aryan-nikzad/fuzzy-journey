from __future__ import annotations

import sys

from ..meta import APP_ID, APP_NAME, AUTHOR, DESCRIPTION, ISSUES, TAGLINE, VERSION, WEBSITE
from ..paths import RESOURCE_DIR
from ..timeutil import now as clock_now
from .gi_setup import Adw, Gdk, Gio, Gtk


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.tray = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(RESOURCE_DIR / "style.css"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._add_action("preferences", self._preferences, "<Ctrl>comma")
        self._add_action("philosophy", self._philosophy, "F1")
        self._add_action("settle-today", lambda *_: self.window and self.window.settle_day(clock_now().date()))
        self._add_action("settle-earlier", lambda *_: self.window and self.window.review_tasks())
        self._add_action("about", self._about)
        self._add_action("quit", lambda *_: self.quit(), "<Ctrl>q")
        self._add_action("stop-alarm", lambda *_: self.window and self.window.stop_alarm(), "<Ctrl>period")
        for index in range(9):
            self._add_action(f"page-{index}", lambda *_, i=index: self.window and self.window.page_index(i), f"<Ctrl>{index + 1}")

    def _add_action(self, name: str, callback, accel: str | None = None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accel:
            self.set_accels_for_action(f"app.{name}", [accel])

    def _preferences(self, *_args) -> None:
        from .dialogs.preferences import PreferencesWindow

        PreferencesWindow(self.window, self.window.ctx).present()

    def _philosophy(self, *_args) -> None:
        from .dialogs.philosophy import PhilosophyDialog

        PhilosophyDialog(self.window).present()

    def _about(self, *_args) -> None:
        about = Adw.AboutWindow(
            transient_for=self.window, application_name=APP_NAME, application_icon=APP_ID,
            version=VERSION, developer_name=AUTHOR, website=WEBSITE, issue_url=ISSUES,
            comments=f"{TAGLINE}. {DESCRIPTION}", license_type=Gtk.License.MIT_X11, copyright=f"© {AUTHOR}",
        )
        about.present()

    def do_activate(self) -> None:
        from .window import MainWindow

        if self.window is None:
            self.window = MainWindow(self)
            self.window.connect("close-request", self._on_window_close)
            self.apply_tray()
        self.window.present()

    # -- the tray ------------------------------------------------------------------

    def apply_tray(self) -> None:
        """Show or remove the tray icon to match the setting."""
        wanted = bool(self.window and self.window.ctx.settings.tray_icon)
        if wanted and self.tray is None:
            from .tray import Tray

            self.tray = Tray(
                APP_NAME, APP_ID, self.toggle_window,
                [(f"Show {APP_NAME}", self.show_window), ("Settle today’s tasks…", self._settle_from_tray),
                 (None, None), ("Quit", self.quit)],
            )
            self.tray.start()
        elif not wanted and self.tray is not None:
            self.tray.stop()
            self.tray = None

    def show_window(self) -> None:
        if self.window:
            self.window.present()

    def toggle_window(self) -> None:
        if self.window and self.window.is_visible() and self.window.is_active():
            self.window.set_visible(False)
        else:
            self.show_window()

    def _settle_from_tray(self) -> None:
        self.show_window()
        if self.window:
            self.window.settle_day(clock_now().date())

    def _on_window_close(self, window) -> bool:
        """Closing hides the window into the tray, but only while a tray really exists: otherwise quit."""
        if self.tray is not None and self.tray.active:
            window.set_visible(False)
            return True
        return False


def main() -> int:
    # Launcher arguments are not files; stop GApplication from interpreting them.
    return Application().run(None)


if __name__ == "__main__":
    sys.exit(main())
