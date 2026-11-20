from __future__ import annotations

from datetime import datetime, timedelta

from ...flex import BUFFER_RANGE, routine_plan
from ...timeutil import human_duration
from ..context import Context
from ..dialogs.routine_dialog import RoutineItemDialog
from ..gi_setup import Adw, Gtk
from ..widgets import label
from .base import Page


class MorningPage(Page):
    """The morning routine: your steps, how long each takes, and a buffer. Work starts after it."""

    listens_to = frozenset({"flex", "data", "location", "day", "rhythm"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._quiet = True
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hero.append(label("MORNING ROUTINE", "fj-overline"))
        self.hero = label("", "fj-hero")
        self.hero_sub = label("", "fj-hero-sub", wrap=True)
        hero.append(self.hero)
        hero.append(self.hero_sub)
        self.column.append(hero)

        self.steps = Adw.PreferencesGroup(
            title="Steps", description="In the order you do them. Roughly how long each takes is enough.")
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Add a step")
        add.add_css_class("flat")
        add.connect("clicked", lambda _b: self.edit(None))
        self.steps.set_header_suffix(add)
        self.column.append(self.steps)

        buffer_group = Adw.PreferencesGroup()
        self.buffer = Adw.SpinRow.new_with_range(*BUFFER_RANGE, 5)
        self.buffer.set_title("Buffer (minutes)")
        self.buffer.set_subtitle("Slack after the last step, for the mornings that run long. Work starts after it.")
        self.buffer.set_value(ctx.settings.flexibility.buffer)
        self.buffer.connect("notify::value", self._on_buffer)
        buffer_group.add(self.buffer)
        self.column.append(buffer_group)

        self.today = Adw.PreferencesGroup(title="Today", description="Where each step lands on the clock.")
        self.column.append(self.today)
        self._rows: list[Gtk.Widget] = []
        self._today_rows: list[Gtk.Widget] = []
        self._quiet = False
        self.refresh()

    def edit(self, item) -> None:
        RoutineItemDialog(self.get_root(), self.ctx, item).present()

    def _on_buffer(self, row, _pspec) -> None:
        if self._quiet:
            return
        fs = self.ctx.settings.flexibility
        from dataclasses import replace

        self.ctx.settings.flexibility = replace(fs, buffer=int(row.get_value()))
        self.ctx.changed("flex")

    def _move(self, item, direction: int) -> None:
        if self.ctx.db.move_routine_item(item, direction):
            self.ctx.changed("flex")

    def _toggle(self, switch, _pspec, item) -> None:
        if self._quiet:
            return
        item.enabled = switch.get_active()
        self.ctx.db.save_routine_item(item)
        self.ctx.changed("flex")

    def refresh(self) -> None:
        self._quiet = True
        items = self.ctx.db.routine_items()
        for row in self._rows:
            self.steps.remove(row)
        self._rows.clear()
        if not items:
            row = Adw.ActionRow(title="No steps yet", subtitle="Add the things you do each morning before work.",
                                activatable=False)
            row.add_css_class("dim-label")
            self.steps.add(row)
            self._rows.append(row)
        for item in items:
            row = Adw.ActionRow(title=item.title, subtitle=f"about {item.minutes} min", activatable=True)
            row.add_prefix(label(f"{item.minutes}", "fj-time", "heading"))
            toggle = Gtk.Switch(active=item.enabled, valign=Gtk.Align.CENTER, tooltip_text="Include it")
            toggle.connect("notify::active", self._toggle, item)
            up = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Move up")
            down = Gtk.Button(icon_name="go-down-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Move down")
            for b, d in ((up, -1), (down, 1)):
                b.add_css_class("flat")
                b.connect("clicked", lambda _b, i=item, direction=d: self._move(i, direction))
                row.add_suffix(b)
            row.add_suffix(toggle)
            row.connect("activated", lambda _r, i=item: self.edit(i))
            if not item.enabled:
                row.add_css_class("fj-past")
            self.steps.add(row)
            self._rows.append(row)
        self._render_today(items)
        self._quiet = False

    def _render_today(self, items) -> None:
        for row in self._today_rows:
            self.today.remove(row)
        self._today_rows.clear()
        fs = self.ctx.settings.flexibility
        self.buffer.set_value(fs.buffer)
        today = datetime.now().date()
        prayers = self.ctx.library.day(self.ctx.location.slug, today)
        start = datetime.combine(today, prayers.fajr) if prayers else None
        plan = routine_plan(start, items, fs.buffer) if start else None
        self.today.set_visible(plan is not None)
        if plan is None:
            self.hero.set_text("—")
            self.hero_sub.set_text("Add your first step. Work will begin after the routine instead of at Fajr.")
            return
        self.hero.set_text(f"{plan.end:%H:%M}")
        used = sum((s.span.duration for s in plan.steps if not s.buffer), timedelta(0))
        self.hero_sub.set_text(
            f"Work starts after {human_duration(used)} of routine and {fs.buffer} min of buffer · day begins {start:%H:%M}")
        for step in plan.steps:
            row = Adw.ActionRow(title=step.title, subtitle=f"{step.minutes} min", activatable=False)
            row.add_prefix(label(f"{step.span.start:%H:%M}", "fj-time", "heading"))
            if step.buffer:
                row.add_css_class("dim-label")
            self.today.add(row)
            self._today_rows.append(row)
