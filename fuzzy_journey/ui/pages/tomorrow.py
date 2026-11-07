from __future__ import annotations

from datetime import date, timedelta

from ...pomodoro import SegmentKind
from ...timeutil import now as clock_now
from ..context import Context
from ..focus import TaskList, minutes_text
from ..gi_setup import Adw, Gtk
from ..widgets import DateButton, label
from .base import Page


def _relation(day: date, today: date) -> str:
    delta = (day - today).days
    return {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(
        delta, f"In {delta} days" if delta > 0 else f"{-delta} days ago"
    )


class TomorrowPage(Page):
    """Plan a day: its focus time, its tasks and its pomodoro schedule. Opens on tomorrow; any day can be chosen."""

    listens_to = frozenset({"day", "rhythm", "data", "location", "tasks", "pomodoro"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._anchor = clock_now().date()
        self.selected = self._anchor + timedelta(days=1)
        self._quiet = False

        # -- which day
        nav = Gtk.Box(spacing=6)
        prev = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Previous day")
        nxt = Gtk.Button(icon_name="go-next-symbolic", tooltip_text="Next day")
        for b in (prev, nxt):
            b.add_css_class("flat")
        prev.connect("clicked", lambda _b: self._go(self.selected - timedelta(days=1)))
        nxt.connect("clicked", lambda _b: self._go(self.selected + timedelta(days=1)))
        self.picker = DateButton(self.selected)
        self.picker.set_hexpand(True)
        self.picker.connect("changed", lambda b: self._go(b.date))
        nav.append(prev)
        nav.append(self.picker)
        nav.append(nxt)
        self.column.append(nav)

        # -- hero
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.overline = label("", "fj-overline")
        self.hero = label("", "fj-hero")
        self.hero_sub = label("", "fj-hero-sub", wrap=True)
        for w in (self.overline, self.hero, self.hero_sub):
            hero.append(w)
        self.column.append(hero)

        self.tasks = TaskList(ctx)
        self.column.append(self.tasks)

        # -- schedule
        self.schedule_group = Adw.PreferencesGroup()
        self.schedule = Adw.ExpanderRow(title="Schedule")
        self._schedule_rows: list[Gtk.Widget] = []
        self.schedule_group.add(self.schedule)
        self.column.append(self.schedule_group)
        self.refresh()

    def _go(self, day: date) -> None:
        if self._quiet or day == self.selected:
            return
        self.selected = day
        self.refresh()

    def refresh(self) -> None:
        today = clock_now().date()
        if today != self._anchor:  # a new day began: open on its tomorrow again
            self._anchor, self.selected = today, today + timedelta(days=1)
        self._quiet = True
        self.picker.date = self.selected
        self._quiet = False

        view = self.ctx.day_view(self.selected)
        schedule = view.schedule
        focus = schedule.focus_minutes if schedule else 0
        self.overline.set_text(f"{_relation(self.selected, today).upper()} · {self.selected:%A %-d %B}")
        if focus:
            self.hero.set_text(minutes_text(focus))
            blocks = sum(1 for s in schedule.segments if s.kind is SegmentKind.FOCUS)
            sub = f"of focus out of {minutes_text(int(view.work_total.total_seconds() // 60))} of work"
            if blocks:
                sub += f" · {blocks} focus block{'s' if blocks != 1 else ''}"
            self.hero_sub.set_text(sub)
        else:
            self.hero.set_text("—")
            self.hero_sub.set_text(
                "A rest day: no work, so no tasks." if view.kind.value == "rest" or (view.plan and not view.work)
                else "No work is planned for this day. Download the prayer times to plan it."
            )
        self.tasks.show_day(self.selected, focus)
        self._render_schedule(view)

    def _render_schedule(self, view) -> None:
        for row in self._schedule_rows:
            self.schedule.remove(row)
        self._schedule_rows = []
        segments = view.schedule.segments if view.schedule else ()
        self.schedule_group.set_visible(bool(segments))
        if not segments:
            return
        planning = view.schedule.planning
        self.schedule.set_subtitle(
            f"{segments[0].start:%H:%M}–{segments[-1].end:%H:%M}" + (" · ends with planning" if planning else "")
        )
        for seg in segments:
            row = Adw.ActionRow(title=seg.title, subtitle=f"{seg.minutes} min", activatable=False)
            row.add_prefix(label(seg.start.strftime("%H:%M"), "fj-time", "heading", xalign=0.0))
            if seg.is_break or seg.kind is SegmentKind.PLANNING:
                row.add_css_class("fj-quiet")
            self.schedule.add_row(row)
            self._schedule_rows.append(row)
