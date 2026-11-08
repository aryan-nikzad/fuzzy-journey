from __future__ import annotations

import calendar
from datetime import date

from ...rhythm import DayKind
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import DateButton, KindSelector, clear, label
from .base import Page


class BankPage(Page):
    listens_to = frozenset({"day", "data"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.month = date.today().replace(day=1)
        self.selected = date.today()
        self._quiet = False

        # -- balance
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hero.append(label("TIME BANK", "fj-overline"))
        self.balance = label("", "fj-balance")
        hero.append(self.balance)
        self.balance_sub = label("", "fj-hero-sub", wrap=True)
        hero.append(self.balance_sub)
        self.progress = Gtk.ProgressBar(margin_top=10)
        hero.append(self.progress)
        self.column.append(hero)

        stats = Gtk.Box(spacing=12, homogeneous=True)
        self.stat_push = self._stat("Push days")
        self.stat_rest = self._stat("Rest days")
        self.stat_steady = self._stat("Steady days")
        for box, _value in (self.stat_push, self.stat_rest, self.stat_steady):
            stats.append(box)
        self.column.append(stats)

        # -- month
        month_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        month_card.add_css_class("fj-card")
        nav = Gtk.Box(spacing=6)
        prev = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Previous month")
        nxt = Gtk.Button(icon_name="go-next-symbolic", tooltip_text="Next month")
        for b in (prev, nxt):
            b.add_css_class("flat")
        prev.connect("clicked", lambda _b: self._shift(-1))
        nxt.connect("clicked", lambda _b: self._shift(1))
        self.month_title = label("", "heading", xalign=0.5)
        self.month_title.set_hexpand(True)
        nav.append(prev)
        nav.append(self.month_title)
        nav.append(nxt)
        month_card.append(nav)
        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=4, column_spacing=4)
        month_card.append(self.grid)
        self.column.append(month_card)

        # -- selected day
        day_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.day_title = label("", "heading")
        day_box.append(self.day_title)
        self.selector = KindSelector()
        self.selector.connect("kind-selected", self._on_kind)
        day_box.append(self.selector)
        self.day_note_hint = label("", "caption", "dim-label", wrap=True)
        day_box.append(self.day_note_hint)
        notes = Adw.PreferencesGroup()
        self.note = Adw.EntryRow(title="Note for this day", show_apply_button=True)
        self.note.connect("apply", self._on_note)
        notes.add(self.note)
        day_box.append(notes)
        self.column.append(day_box)

        # -- tracking
        tracking = Adw.PreferencesGroup(title="Tracking")
        row = Adw.ActionRow(title="Counting since", subtitle="Earlier days are ignored, so your bank starts at zero.")
        self.start_button = DateButton(ctx.settings.bank_start)
        self.start_button.connect("changed", self._on_start)
        row.add_suffix(self.start_button)
        tracking.add(row)
        self.column.append(tracking)

        self.refresh()

    @staticmethod
    def _stat(caption: str):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("fj-card")
        value = label("0", "fj-stat-value")
        box.append(value)
        box.append(label(caption, "caption", "dim-label"))
        return box, value

    # -- helpers -----------------------------------------------------------

    def _counts(self, day: date) -> bool:
        return self.ctx.settings.bank_start <= day <= date.today()

    def _shift(self, amount: int) -> None:
        year, month = self.month.year, self.month.month + amount
        if month < 1:
            year, month = year - 1, 12
        elif month > 12:
            year, month = year + 1, 1
        self.month = date(year, month, 1)
        self._render_month()

    def _select(self, day: date) -> None:
        self.selected = day
        self.refresh()

    # -- events ------------------------------------------------------------

    def _on_kind(self, _selector, code: str) -> None:
        if self._quiet or not self._counts(self.selected):
            return
        existing = self.ctx.db.day_entries(self.selected, self.selected).get(self.selected)
        self.ctx.db.set_day_kind(self.selected, DayKind.from_code(code), existing.note if existing else "")
        self.ctx.changed("day")

    def _on_note(self, row: Adw.EntryRow) -> None:
        if self._quiet or not self._counts(self.selected):
            return
        self.ctx.db.set_day_kind(self.selected, self.ctx.db.day_kind(self.selected), row.get_text().strip())
        self.ctx.toast("Note saved")

    def _on_start(self, button: DateButton) -> None:
        self.ctx.settings.bank_start = button.date
        self.ctx.toast(f"Counting from {button.date:%d %b %Y}")
        self.ctx.changed("day")

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        self._quiet = True
        bank = self.ctx.bank()
        shown = f"{bank.balance:+g}" if bank.balance else "0"
        self.balance.set_text(f"{shown} {'day' if abs(bank.balance) == 1 else 'days'}")
        if bank.in_debt:
            self.balance_sub.set_text(
                f"You’ve borrowed rest. {bank.push_days_to_next_whole_day} Push days bring you back to zero."
            )
            self.progress.set_fraction(0.0)
        else:
            self.balance_sub.set_text(
                f"{bank.whole_rest_days} whole rest day{'s' if bank.whole_rest_days != 1 else ''} ready to take. "
                f"{bank.push_days_to_next_whole_day} more Push day{'s' if bank.push_days_to_next_whole_day != 1 else ''} "
                "for the next."
            )
            self.progress.set_fraction(bank.balance % 1)
        self.stat_push[1].set_text(str(bank.push_days))
        self.stat_rest[1].set_text(str(bank.rest_days))
        self.stat_steady[1].set_text(str(bank.steady_days))
        self.start_button.date = self.ctx.settings.bank_start

        counts = self._counts(self.selected)
        self.day_title.set_text(self.selected.strftime("%A, %-d %B %Y"))
        entry = self.ctx.db.day_entries(self.selected, self.selected).get(self.selected)
        self.selector.set_kind(entry.kind if entry and counts else DayKind.STEADY)
        self.selector.set_sensitive(counts)
        self.note.set_sensitive(counts)
        self.note.set_text(entry.note if entry and counts else "")
        if self.selected < self.ctx.settings.bank_start:
            self.day_note_hint.set_text("Before the bank started counting. This day has no effect.")
        elif self.selected > date.today():
            self.day_note_hint.set_text("A future day. You can classify it once it arrives.")
        elif entry and entry.kind is DayKind.RECOVERED:
            self.day_note_hint.set_text(
                f"A recovered day: it began at {entry.start:%H:%M}. It counts as Steady. Choosing a kind replaces it."
            )
        else:
            self.day_note_hint.set_text("Unmarked days count as Steady. You can change past days too.")
        self._render_month()
        self._quiet = False

    def _render_month(self) -> None:
        clear(self.grid)
        self.month_title.set_text(self.month.strftime("%B %Y"))
        for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            self.grid.attach(label(name, "fj-weekday", xalign=0.5), col, 0, 1, 1)
        last = calendar.monthrange(self.month.year, self.month.month)[1]
        entries = self.ctx.db.day_entries(self.month, self.month.replace(day=last))
        today = date.today()
        for row, week in enumerate(calendar.Calendar().monthdatescalendar(self.month.year, self.month.month), start=1):
            for col, day in enumerate(week):
                if day.month != self.month.month:
                    continue
                button = Gtk.Button(label=str(day.day))
                button.add_css_class("fj-day")
                entry = entries.get(day)
                if entry and self._counts(day):
                    if entry.kind is DayKind.PUSH:
                        button.add_css_class("fj-day-push")
                    elif entry.kind is DayKind.REST:
                        button.add_css_class("fj-day-rest")
                    elif entry.kind is DayKind.RECOVERED:
                        button.add_css_class("fj-day-recovered")
                if day == today:
                    button.add_css_class("fj-day-today")
                if day == self.selected:
                    button.add_css_class("fj-day-selected")
                if day > today:
                    button.add_css_class("dim-label")
                button.connect("clicked", lambda _b, d=day: self._select(d))
                self.grid.attach(button, col, row, 1, 1)
