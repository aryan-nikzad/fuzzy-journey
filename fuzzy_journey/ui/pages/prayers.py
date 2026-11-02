from __future__ import annotations

from datetime import date

from ...models import PRAYER_NAMES
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page


class PrayersPage(Page):
    listens_to = frozenset({"data", "location", "day"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.year = date.today().year
        self.full_year = False

        nav = Gtk.Box(spacing=6)
        prev = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Previous year")
        nxt = Gtk.Button(icon_name="go-next-symbolic", tooltip_text="Next year")
        for b in (prev, nxt):
            b.add_css_class("flat")
        prev.connect("clicked", lambda _b: self._shift(-1))
        nxt.connect("clicked", lambda _b: self._shift(1))
        self.year_label = label("", "title-2", "fj-numeric", xalign=0.5)
        self.year_label.set_width_chars(5)
        self.scope = Gtk.ToggleButton(label="Full year", valign=Gtk.Align.CENTER)
        self.scope.connect("toggled", self._on_scope)
        spacer = Gtk.Box(hexpand=True)
        for w in (prev, self.year_label, nxt, spacer, self.scope):
            nav.append(w)
        self.column.append(nav)

        self.status = label("", "caption", "dim-label", xalign=0.5)
        self.column.append(self.status)

        self.missing = Adw.StatusPage(icon_name="folder-download-symbolic", title="Not on this computer")
        self.download = Gtk.Button(label="Download", halign=Gtk.Align.CENTER)
        self.download.add_css_class("suggested-action")
        self.download.add_css_class("pill")
        self.download.connect("clicked", self._download)
        self.missing.set_child(self.download)
        self.column.append(self.missing)

        self.table = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.table.add_css_class("boxed-list")
        self.column.append(self.table)
        self.refresh()

    def _shift(self, amount: int) -> None:
        self.year += amount
        self.full_year = self.year != date.today().year
        self.scope.set_active(self.full_year)
        self.refresh()

    def _on_scope(self, button: Gtk.ToggleButton) -> None:
        self.full_year = button.get_active()
        self.refresh()

    def _download(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        button.set_label("Downloading…")

        def done(ok: bool, message: str) -> None:
            button.set_sensitive(True)
            button.set_label("Download")
            self.ctx.toast(message if ok else f"Download failed: {message}")

        self.ctx.download_year(self.year, done)

    def refresh(self) -> None:
        loc = self.ctx.location
        self.year_label.set_text(str(self.year))
        clear(self.table)
        table = self.ctx.library.table(loc.slug, self.year)
        self.missing.set_visible(table is None)
        self.table.set_visible(table is not None)
        self.scope.set_sensitive(self.year == date.today().year and table is not None)
        if table is None:
            self.missing.set_description(
                f"The {self.year} timetable for {loc.name} hasn’t been downloaded. "
                "It needs the internet once, then works offline."
            )
            self.status.set_text("")
            return

        today = date.today()
        days = [d for d in table.ordered() if self.full_year or d.day >= today]
        self.status.set_text(f"{loc.name} · {loc.method_name} · {len(days)} days")
        if not days:
            self.status.set_text(f"No upcoming days left in {self.year}. Switch to the full year.")
            return

        self.table.append(self._row(None, today, header=True))
        for entry in days:
            self.table.append(self._row(entry, today))

    @staticmethod
    def _row(entry, today: date, header: bool = False) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        box = Gtk.Box(spacing=4, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        date_col = label("" if header else entry.day.strftime("%a %-d %b"), "fj-prayer-time")
        date_col.set_width_chars(11)
        date_col.set_max_width_chars(11)
        box.append(date_col)
        for name in PRAYER_NAMES:
            if header:
                cell = label(name, "fj-prayer-head", xalign=0.5)
            else:
                at = entry.get(name)
                cell = label(f"{at:%H:%M}" if at else "—", "fj-prayer-time", xalign=0.5)
            cell.set_hexpand(True)
            cell.set_width_chars(6)
            box.append(cell)
        row.set_child(box)
        if not header and entry.day == today:
            row.add_css_class("fj-now")
        return row
