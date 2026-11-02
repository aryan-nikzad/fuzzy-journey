from __future__ import annotations

from datetime import datetime

from ...meta import APP_NAME
from ...models import CALCULATION_METHODS, Location
from ...paths import APP_DATA_DIR, ensure_data_dir
from ..context import Context
from ..gi_setup import Adw, Gio, Gtk

THEMES = ("system", "light", "dark")


def apply_theme(name: str) -> None:
    scheme = {"light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}.get(
        name, Adw.ColorScheme.DEFAULT
    )
    Adw.StyleManager.get_default().set_color_scheme(scheme)


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, ctx: Context) -> None:
        super().__init__(transient_for=parent, modal=True, title="Preferences", default_width=560, default_height=680)
        self.ctx = ctx
        self.set_search_enabled(False)
        page = Adw.PreferencesPage()
        self.add(page)

        # -- appearance
        look = Adw.PreferencesGroup(title="Appearance")
        self.theme_row = Adw.ComboRow(title="Colour scheme")
        self.theme_row.set_model(Gtk.StringList.new(["Follow the system", "Light", "Dark"]))
        self.theme_row.set_selected(THEMES.index(ctx.settings.theme))
        self.theme_row.connect("notify::selected", self._on_theme)
        look.add(self.theme_row)
        page.add(look)

        # -- location
        loc = ctx.location
        place = Adw.PreferencesGroup(
            title="Location",
            description="Your day starts at Fajr and ends at Isha, so these decide its shape.",
        )
        self.name_row = Adw.EntryRow(title="Place name")
        self.name_row.set_text(loc.name)
        self.lat_row = Adw.SpinRow.new_with_range(-90, 90, 0.0001)
        self.lat_row.set_title("Latitude")
        self.lat_row.set_digits(4)
        self.lat_row.set_value(loc.latitude)
        self.lon_row = Adw.SpinRow.new_with_range(-180, 180, 0.0001)
        self.lon_row.set_title("Longitude")
        self.lon_row.set_digits(4)
        self.lon_row.set_value(loc.longitude)
        self.method_ids = list(CALCULATION_METHODS)
        if loc.method not in self.method_ids:
            self.method_ids.append(loc.method)
        self.method_row = Adw.ComboRow(title="Calculation method")
        self.method_row.set_model(Gtk.StringList.new(
            [CALCULATION_METHODS.get(m, f"Method {m}") for m in self.method_ids]
        ))
        self.method_row.set_selected(self.method_ids.index(loc.method))
        for row in (self.name_row, self.lat_row, self.lon_row, self.method_row):
            place.add(row)
        apply = Adw.ActionRow(title="Apply location", subtitle="Timetables are stored per place, so nothing is lost.")
        button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.connect("clicked", self._apply_location)
        apply.add_suffix(button)
        place.add(apply)
        page.add(place)

        # -- prayer data
        data = Adw.PreferencesGroup(
            title="Prayer data", description="Downloaded once, used offline. This is the only thing that ever needs the internet."
        )
        year = datetime.now().year
        self.download_buttons = []
        for y in (year, year + 1):
            row = Adw.ActionRow(title=f"{y} timetable")
            self.download_buttons.append((row, y))
            button = Gtk.Button(valign=Gtk.Align.CENTER)
            button.connect("clicked", self._download, y)
            row.add_suffix(button)
            data.add(row)
            row._button = button
        page.add(data)
        self._refresh_data()

        # -- storage
        store = Adw.PreferencesGroup(title="Your data")
        folder = Adw.ActionRow(title="Data folder", subtitle=str(APP_DATA_DIR), subtitle_selectable=True)
        open_button = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
        open_button.connect("clicked", self._open_folder)
        folder.add_suffix(open_button)
        store.add(folder)
        store.add(Adw.ActionRow(
            title="Private by design",
            subtitle=f"{APP_NAME} has no account, no cloud and no telemetry. Alarms never use the network.",
            activatable=False,
        ))
        page.add(store)

    # -- handlers ----------------------------------------------------------

    def _on_theme(self, row, _pspec) -> None:
        name = THEMES[row.get_selected()]
        self.ctx.settings.theme = name
        apply_theme(name)

    def _apply_location(self, _button) -> None:
        name = self.name_row.get_text().strip()
        if not name:
            self.add_toast(Adw.Toast.new("Give the place a name."))
            return
        self.ctx.settings.location = Location(
            name, round(self.lat_row.get_value(), 4), round(self.lon_row.get_value(), 4),
            self.method_ids[self.method_row.get_selected()],
        )
        self.add_toast(Adw.Toast.new(f"Location set to {name}"))
        self._refresh_data()
        self.ctx.changed("location")

    def _refresh_data(self) -> None:
        slug = self.ctx.location.slug
        for row, year in self.download_buttons:
            have = self.ctx.library.table(slug, year) is not None
            row.set_subtitle("On this computer" if have else "Not downloaded")
            row._button.set_label("Refresh" if have else "Download")
            row._button.remove_css_class("suggested-action")
            if not have:
                row._button.add_css_class("suggested-action")

    def _download(self, button: Gtk.Button, year: int) -> None:
        button.set_sensitive(False)
        button.set_label("Downloading…")

        def done(ok: bool, message: str) -> None:
            button.set_sensitive(True)
            self._refresh_data()
            self.add_toast(Adw.Toast.new(message if ok else f"Download failed: {message}"))

        self.ctx.download_year(year, done)

    def _open_folder(self, _button) -> None:
        ensure_data_dir()
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(APP_DATA_DIR))).launch(self, None, None)
