from __future__ import annotations

import sys

from ..meta import APP_ID, APP_NAME, AUTHOR, DESCRIPTION, ISSUES, TAGLINE, VERSION, WEBSITE
from ..paths import RESOURCE_DIR
from .gi_setup import Adw, Gdk, Gio, Gtk


class Application(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(RESOURCE_DIR / "style.css"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._add_action("preferences", self._preferences, "<Ctrl>comma")
        self._add_action("philosophy", self._philosophy, "F1")
        self._add_action("about", self._about)
        self._add_action("quit", lambda *_: self.quit(), "<Ctrl>q")
        self._add_action("stop-alarm", lambda *_: self.window and self.window.stop_alarm(), "<Ctrl>period")
        for index in range(6):
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
        self.window.present()


def main() -> int:
    # Launcher arguments are not files; stop GApplication from interpreting them.
    return Application().run(None)


if __name__ == "__main__":
    sys.exit(main())
