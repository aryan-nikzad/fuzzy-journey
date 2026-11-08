from __future__ import annotations

from datetime import date, time, timedelta

from ...rhythm import DayKind, check_recovered_start, plan_day
from ...timeutil import human_duration
from ...timeutil import now as clock_now
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import TimeEntry, label
from .form import FormDialog, group


class RecoveredDialog(FormDialog):
    """“I overslept”: begin today at the time you really woke, and work half of what is left of it."""

    def __init__(self, parent: Gtk.Window, ctx: Context, day: date, current: time | None = None) -> None:
        self.ctx, self.day = ctx, day
        self.prayer = ctx.library.day(ctx.location.slug, day)
        self.current = current
        super().__init__(parent, "I overslept", save_label="Recover the day", height=420)

    def _first_guess(self) -> time:
        if self.current:
            return self.current
        soon = clock_now() + timedelta(minutes=4)  # the next five-minute mark
        soon -= timedelta(minutes=soon.minute % 5, seconds=soon.second)
        return soon.time().replace(second=0, microsecond=0)

    def build(self) -> None:
        box = group()
        row = Adw.ActionRow(title="My day started at", subtitle="When you actually woke up.")
        self.start = TimeEntry(self._first_guess())
        self.start.connect("changed", self._preview)
        row.add_suffix(self.start)
        box.add(row)
        self.body.append(box)
        self.note = label("", "caption", "dim-label", wrap=True)
        self.body.append(self.note)
        self.body.append(label(
            "A rescue, not a plan. Work is half of the time you are awake, afternoon included, "
            "so your tasks still have room. The bank is not affected.", "caption", "dim-label", wrap=True,
        ))
        self._preview()

    def _plan(self):
        return plan_day(
            self.day, DayKind.RECOVERED, fajr=self.prayer.fajr, isha=self.prayer.isha,
            evening_start=self.ctx.settings.evening_start, flex=self.ctx.settings.flex, start=self.start.time,
        )

    def _preview(self, *_args) -> None:
        if not self.prayer:
            self.note.set_text("Download this year’s prayer times first.")
            return
        problem = check_recovered_start(self.prayer.fajr, self.prayer.isha, self.start.time)
        if problem:
            self.note.set_text(problem)
            return
        plan = self._plan()
        self.note.set_text(
            f"{human_duration(plan.target)} of work, {plan.morning.start:%H:%M} to {plan.morning.end:%H:%M}. "
            f"Bed {plan.bedtime:%H:%M}."
        )

    def save(self) -> bool:
        if not self.prayer:
            self.error("Download this year’s prayer times first.")
            return False
        problem = check_recovered_start(self.prayer.fajr, self.prayer.isha, self.start.time)
        if problem:
            self.error(problem)
            return False
        existing = self.ctx.db.day_entries(self.day, self.day).get(self.day)
        self.ctx.db.set_day_kind(self.day, DayKind.RECOVERED, existing.note if existing else "", self.start.time)
        self.ctx.changed("day")
        return True
