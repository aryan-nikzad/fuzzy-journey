from __future__ import annotations

import calendar
from datetime import date

from ...habits import HABITS, MAX_COUNT, MONTH, WEEK, HabitStat, days_left, since_start, window_stat
from ...timeutil import now as clock_now
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import DateButton, clear, label
from .base import Page


def describe(stat: HabitStat | None, wait: int) -> str:
    """One line for a figure, or what must happen before there is one."""
    if stat is None:
        return f"Shown after {wait} more day{'s' if wait != 1 else ''} have passed."
    times = f"{stat.total} time{'s' if stat.total != 1 else ''}"
    return (f"{stat.average:.2f} a day · {times} · happened on {stat.days_with} of {stat.days} days "
            f"· {stat.clean_days} without")


class HabitsPage(Page):
    """A private calendar of two habits: per day, whether it happened and how many times.

    Each habit counts from its own start date. Moving the date changes what the figures include and
    never erases a day; earlier days keep their marks and can still be edited.
    """

    listens_to = frozenset({"habits", "day"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        today = clock_now().date()
        self.month = today.replace(day=1)
        self.selected = today
        self._quiet = False

        self.column.append(label(
            "A private record, only for you. Figures appear after enough days have passed: seven for the "
            "week, thirty for the month. Today is counted tomorrow, when it is finished.",
            "dim-label", wrap=True,
        ))

        # -- the figures, one card per habit
        self.groups: dict[str, dict] = {}
        for key, name in HABITS:
            group = Adw.PreferencesGroup(title=name)
            start_row = Adw.ActionRow(title="Counting from", subtitle="Earlier days keep their marks; they just are not counted.",
                                      subtitle_lines=0)
            button = DateButton(ctx.settings.habit_start(key))
            button.connect("changed", lambda b, k=key: self._on_start(k, b))
            start_row.add_suffix(button)
            group.add(start_row)
            rows = {}
            for tag, title in (("week", "Last 7 days"), ("month", "Last 30 days"), ("all", "Since the start")):
                row = Adw.ActionRow(title=title, subtitle_lines=0, activatable=False)
                group.add(row)
                rows[tag] = row
            self.groups[key] = {"button": button, **rows}
            self.column.append(group)

        # -- the month
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("fj-card")
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
        card.append(nav)
        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=4, column_spacing=4)
        card.append(self.grid)
        card.append(label("Tinted: one habit · strongly tinted: both. Tap a day to edit it.", "caption", "dim-label",
                          xalign=0.5))
        self.column.append(card)

        # -- the selected day
        self.day_title = label("", "heading", xalign=0.0)
        self.column.append(self.day_title)
        editor = Adw.PreferencesGroup()
        self.checks: dict[str, Gtk.CheckButton] = {}
        self.spins: dict[str, Gtk.SpinButton] = {}
        for key, name in HABITS:
            row = Adw.ActionRow(title=name, subtitle="Happened this day", activatable=False)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.connect("toggled", lambda _b, k=key: self._on_check(k))
            spin = Gtk.SpinButton.new_with_range(1, MAX_COUNT, 1)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_tooltip_text("How many times")
            spin.connect("value-changed", lambda _s, k=key: self._on_count(k))
            row.add_prefix(check)
            row.add_suffix(label("times", "dim-label"))
            row.add_suffix(spin)
            editor.add(row)
            self.checks[key], self.spins[key] = check, spin
        self.column.append(editor)
        self.refresh()

    # -- events ----------------------------------------------------------------

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

    def _on_start(self, key: str, button: DateButton) -> None:
        self.ctx.settings.set_habit_start(key, button.date)
        self.ctx.toast(f"Counting from {button.date:%d %b %Y}")
        self.ctx.changed("habits")

    def _on_check(self, key: str) -> None:
        if self._quiet:
            return
        self._save()

    def _on_count(self, key: str) -> None:
        if self._quiet or not self.checks[key].get_active():
            return
        self._save()

    def _save(self) -> None:
        counts = {key: (int(self.spins[key].get_value()) if self.checks[key].get_active() else 0)
                  for key, _name in HABITS}
        self.ctx.db.set_habit_day(self.selected, counts)
        self.ctx.changed("habits")

    # -- rendering ---------------------------------------------------------------

    def refresh(self) -> None:
        self._quiet = True
        today = clock_now().date()
        for key, _name in HABITS:
            start = self.ctx.settings.habit_start(key)
            counts = {day: marks[key] for day, marks in self.ctx.db.habit_counts(start, today).items()}
            rows = self.groups[key]
            rows["button"].date = start
            rows["week"].set_subtitle(describe(window_stat(counts, start, today, WEEK), days_left(start, today, WEEK)))
            rows["month"].set_subtitle(describe(window_stat(counts, start, today, MONTH), days_left(start, today, MONTH)))
            rows["all"].set_subtitle(describe(since_start(counts, start, today), 1))

        self.day_title.set_text(self.selected.strftime("%A, %-d %B %Y"))
        marks = self.ctx.db.habit_counts(self.selected, self.selected).get(self.selected, {})
        editable = self.selected <= today
        for key, _name in HABITS:
            count = marks.get(key, 0)
            self.checks[key].set_active(count > 0)
            self.checks[key].set_sensitive(editable)
            self.spins[key].set_value(max(1, count))
            self.spins[key].set_sensitive(editable and count > 0)
        self._render_month()
        self._quiet = False

    def _render_month(self) -> None:
        clear(self.grid)
        self.month_title.set_text(self.month.strftime("%B %Y"))
        for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            self.grid.attach(label(name, "fj-weekday", xalign=0.5), col, 0, 1, 1)
        last = calendar.monthrange(self.month.year, self.month.month)[1]
        marks = self.ctx.db.habit_counts(self.month, self.month.replace(day=last))
        today = clock_now().date()
        for row, week in enumerate(calendar.Calendar().monthdatescalendar(self.month.year, self.month.month), start=1):
            for col, day in enumerate(week):
                if day.month != self.month.month:
                    continue
                button = Gtk.Button(label=str(day.day))
                button.add_css_class("fj-day")
                counts = marks.get(day, {})
                hit = [key for key, _name in HABITS if counts.get(key, 0) > 0]
                if len(hit) == 2:
                    button.add_css_class("fj-day-both")
                elif hit:
                    button.add_css_class("fj-day-habit")
                if hit:
                    button.set_tooltip_text(" · ".join(f"{name} ×{counts[key]}" for key, name in HABITS if key in hit))
                if day == today:
                    button.add_css_class("fj-day-today")
                if day == self.selected:
                    button.add_css_class("fj-day-selected")
                if day > today:
                    button.add_css_class("dim-label")
                button.connect("clicked", lambda _b, d=day: self._select(d))
                self.grid.attach(button, col, row, 1, 1)
