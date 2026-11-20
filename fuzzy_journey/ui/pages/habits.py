from __future__ import annotations

import calendar
from datetime import date

from ...habits import MAX_COUNT, MONTH, WEEK, Habit, days_left, describe, since_start, window_stat
from ...timeutil import now as clock_now
from ..context import Context
from ..dialogs.habit_dialog import HabitDialog
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page


class HabitsPage(Page):
    """A private calendar for habits you choose: ones to quit and ones to build.

    Each habit is marked per day (did it happen, and how many times) and counted from its own start date.
    Moving that date changes what the figures include and never erases a day. You add, rename, reorder and
    delete habits yourself.
    """

    listens_to = frozenset({"habits", "day"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        today = clock_now().date()
        self.month = today.replace(day=1)
        self.selected = today
        self._quiet = False
        self._habits: list[Habit] = []
        self._figures: dict[int, dict] = {}
        self._inputs: dict[int, tuple[Gtk.CheckButton, Gtk.SpinButton]] = {}

        self.column.append(label(
            "A private record, only for you. Track what you want to quit and what you want to build. Figures "
            "appear after enough days have passed: seven for the week, thirty for the month. Today is counted "
            "tomorrow, when it is finished.",
            "dim-label", wrap=True,
        ))
        self.stats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.column.append(self.stats)

        self.add_button = Gtk.Button(child=Adw.ButtonContent(label="Add a habit", icon_name="list-add-symbolic"),
                                     halign=Gtk.Align.CENTER)
        self.add_button.add_css_class("pill")
        self.add_button.connect("clicked", lambda _b: self.edit(None))
        self.column.append(self.add_button)

        # -- the month
        self.calendar_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.calendar_card.add_css_class("fj-card")
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
        self.calendar_card.append(nav)
        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=4, column_spacing=4)
        self.calendar_card.append(self.grid)
        self.calendar_card.append(label(
            "Orange: a habit you are quitting happened. Green: a habit you are building was done. Split: both. "
            "Hover a day for the details; tap it to edit.", "caption", "dim-label", xalign=0.5, wrap=True))
        self.column.append(self.calendar_card)

        # -- the selected day
        self.day_title = label("", "heading", xalign=0.0)
        self.column.append(self.day_title)
        self.editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.column.append(self.editor)
        self.refresh()

    # -- actions -----------------------------------------------------------------

    def edit(self, habit: Habit | None) -> None:
        HabitDialog(self.get_root(), self.ctx, habit).present()

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
        self._refresh_figures()

    def _save(self, habit: Habit) -> None:
        if self._quiet:
            return
        check, spin = self._inputs[habit.id]
        self.ctx.db.set_habit_mark(habit.id, self.selected, int(spin.get_value()) if check.get_active() else 0)
        self._refresh_figures()  # only the figures and calendar: the inputs stay as they are

    # -- rendering ---------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the habit list (a habit was added, changed, moved or deleted)."""
        self._habits = self.ctx.db.list_habits()
        clear(self.stats)
        clear(self.editor)
        self._figures, self._inputs = {}, {}
        empty = not self._habits
        self.calendar_card.set_visible(not empty)
        self.day_title.set_visible(not empty)
        if empty:
            self.stats.append(label("No habits yet. Add one: something you want to quit, or something you want to "
                                    "build.", "dim-label", wrap=True, xalign=0.5))

        editor = Adw.PreferencesGroup()
        for habit in self._habits:
            group = Adw.PreferencesGroup(title=habit.name)
            edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text=f"Edit “{habit.name}”")
            edit.add_css_class("flat")
            edit.connect("clicked", lambda _b, h=habit: self.edit(h))
            group.set_header_suffix(edit)
            rows = {}
            for tag, title in (("week", "Last 7 days"), ("month", "Last 30 days"), ("all", "Since the start")):
                row = Adw.ActionRow(title=title, subtitle_lines=0, activatable=False)
                group.add(row)
                rows[tag] = row
            self._figures[habit.id] = rows
            self.stats.append(group)

            row = Adw.ActionRow(title=habit.name, subtitle="Done this day" if not habit.quitting
                                else "Happened this day", activatable=False, use_markup=False)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            spin = Gtk.SpinButton.new_with_range(1, MAX_COUNT, 1)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_tooltip_text("How many times")
            check.connect("toggled", lambda _b, h=habit: self._save(h))
            spin.connect("value-changed", lambda _s, h=habit: self._save(h) if self._inputs[h.id][0].get_active()
                         else None)
            row.add_prefix(check)
            row.add_suffix(label("times", "dim-label"))
            row.add_suffix(spin)
            editor.add(row)
            self._inputs[habit.id] = (check, spin)
        if self._habits:
            self.editor.append(editor)
        self._refresh_figures()

    def _refresh_figures(self) -> None:
        self._quiet = True
        today = clock_now().date()
        for habit in self._habits:
            counts = self.ctx.db.habit_counts(habit.id, habit.start, today)
            kind = habit.kind
            rows = self._figures[habit.id]
            rows["week"].set_subtitle(describe(window_stat(counts, habit.start, today, WEEK),
                                               days_left(habit.start, today, WEEK), kind))
            rows["month"].set_subtitle(describe(window_stat(counts, habit.start, today, MONTH),
                                                days_left(habit.start, today, MONTH), kind))
            rows["all"].set_subtitle(describe(since_start(counts, habit.start, today), 1, kind))
        self.day_title.set_text(self.selected.strftime("%A, %-d %B %Y"))
        marks = self.ctx.db.habit_marks(self.selected, self.selected).get(self.selected, {})
        editable = self.selected <= today
        for habit in self._habits:
            check, spin = self._inputs[habit.id]
            count = marks.get(habit.id, 0)
            check.set_active(count > 0)
            check.set_sensitive(editable)
            spin.set_value(max(1, count))
            spin.set_sensitive(editable and count > 0)
        self._render_month()
        self._quiet = False

    def _render_month(self) -> None:
        clear(self.grid)
        self.month_title.set_text(self.month.strftime("%B %Y"))
        for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            self.grid.attach(label(name, "fj-weekday", xalign=0.5), col, 0, 1, 1)
        last = calendar.monthrange(self.month.year, self.month.month)[1]
        marks = self.ctx.db.habit_marks(self.month, self.month.replace(day=last))
        names = {h.id: h for h in self._habits}
        today = clock_now().date()
        for row, week in enumerate(calendar.Calendar().monthdatescalendar(self.month.year, self.month.month), start=1):
            for col, day in enumerate(week):
                if day.month != self.month.month:
                    continue
                button = Gtk.Button(label=str(day.day))
                button.add_css_class("fj-day")
                hits = [(names[hid], n) for hid, n in marks.get(day, {}).items() if hid in names]
                bad = any(h.quitting for h, _n in hits)
                good = any(not h.quitting for h, _n in hits)
                if bad and good:
                    button.add_css_class("fj-day-mixed")
                elif bad:
                    button.add_css_class("fj-day-bad")
                elif good:
                    button.add_css_class("fj-day-good")
                if hits:
                    button.set_tooltip_text(" · ".join(f"{h.name} ×{n}" for h, n in hits))
                if day == today:
                    button.add_css_class("fj-day-today")
                if day == self.selected:
                    button.add_css_class("fj-day-selected")
                if day > today:
                    button.add_css_class("dim-label")
                button.connect("clicked", lambda _b, d=day: self._select(d))
                self.grid.attach(button, col, row, 1, 1)
