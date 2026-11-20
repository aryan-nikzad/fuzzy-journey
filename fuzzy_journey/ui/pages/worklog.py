from __future__ import annotations

from datetime import date, timedelta

from ...pomodoro import SegmentKind
from ...rhythm import productive_between
from ...timeutil import human_duration
from ...timeutil import now as clock_now
from ..context import Context
from ..gi_setup import Adw, GLib, Gtk
from ..widgets import clear, label
from .base import Page


class WorkLogPage(Page):
    """A calendar of the days you really started work, with when you began, ended, and each block."""

    listens_to = frozenset({"flex", "pomodoro", "data", "day"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._quiet = True
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hero.append(label("WORK LOG", "fj-overline"))
        self.hero = label("", "fj-hero")
        self.hero_sub = label("", "fj-hero-sub", wrap=True)
        hero.append(self.hero)
        hero.append(self.hero_sub)
        self.column.append(hero)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("fj-card")
        self.calendar = Gtk.Calendar()
        self.calendar.connect("day-selected", self._on_day)
        self.calendar.connect("notify::month", lambda *_: self._mark())
        self.calendar.connect("notify::year", lambda *_: self._mark())
        card.append(self.calendar)
        self.column.append(card)

        self.detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.column.append(self.detail)
        self._quiet = False
        self.refresh()

    def _selected(self) -> date:
        d = self.calendar.get_date()
        return date(d.get_year(), d.get_month(), d.get_day_of_month())

    def _month_range(self) -> tuple[date, date]:
        d = self.calendar.get_date()
        first = date(d.get_year(), d.get_month(), 1)
        return first - timedelta(days=7), first + timedelta(days=40)

    def _mark(self) -> None:
        self.calendar.clear_marks()
        start, end = self._month_range()
        for day, record in self.ctx.db.flex_days(start, end).items():
            if record.started_at and day.month == self.calendar.get_date().get_month():
                self.calendar.mark_day(day.day)

    def _on_day(self, *_args) -> None:
        if not self._quiet:
            self._render_day()

    def refresh(self) -> None:
        self._quiet = True
        today = clock_now().date()
        self._mark()
        record = self.ctx.db.flex_day(today)
        if record.started_at:
            self.hero.set_text(f"{record.started_at:%H:%M}")
            tail = f" · ended {record.ended_at:%H:%M}" if record.ended_at else " · still working"
            self.hero_sub.set_text(f"You started work today{tail}")
        else:
            self.hero.set_text("—")
            self.hero_sub.set_text("Work has not been started today. Marked days are days you started.")
        self._quiet = False
        self._render_day()

    def _render_day(self) -> None:
        clear(self.detail)
        day = self._selected()
        record = self.ctx.db.flex_day(day)
        group = Adw.PreferencesGroup(title=f"{day:%A, %-d %B}")
        self.detail.append(group)
        if not record.started_at:
            group.add(Adw.ActionRow(title="Not started", subtitle="No start was recorded for this day.",
                                    activatable=False))
            return
        end = record.ended_at
        focus = sum((productive_between(r.start, r.stop or end or clock_now(), ())
                     for r in record.runs if r.kind is SegmentKind.FOCUS), timedelta(0))
        span = f"{record.started_at:%H:%M}–{end:%H:%M}" if end else f"{record.started_at:%H:%M}–"
        summary = Adw.ActionRow(title=f"Started {record.started_at:%H:%M}", activatable=False,
                                subtitle=span + (f" · {human_duration(focus)} of focus in {len(record.runs)} blocks"
                                                 if record.runs else ""))
        group.add(summary)
        for run in record.runs:
            stop = f"{run.stop:%H:%M}" if run.stop else "running"
            minutes = int(((run.stop or clock_now()) - run.start).total_seconds() // 60)
            row = Adw.ActionRow(title=run.kind.label, subtitle=f"{run.start:%H:%M}–{stop} · {minutes} min",
                                activatable=False)
            if run.kind is not SegmentKind.FOCUS:
                row.add_css_class("dim-label")
            group.add(row)
