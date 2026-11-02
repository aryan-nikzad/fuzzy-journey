from __future__ import annotations

from datetime import datetime, time, timedelta

from ...rhythm import DayKind, plan_day
from ...timeutil import human_duration, mask_label
from ..context import Context
from ..dialogs.activity_dialog import ActivityDialog
from ..gi_setup import Adw, Gtk
from ..widgets import TimeEntry, label
from .base import Page


class RoutinePage(Page):
    listens_to = frozenset({"rhythm", "data", "location", "day"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._quiet = True

        # -- how work is planned
        work = Adw.PreferencesGroup(
            title="Work", description="A share of your day, planned from prayer times and adjusted around your activities."
        )
        evening = Adw.ActionRow(
            title="Evening work starts",
            subtitle="Used only when work overflows past 14:00. Earliest 14:00.",
        )
        self.evening = TimeEntry(ctx.settings.evening_start, min_hour=14)
        self.evening.connect("changed", self._save_evening)
        evening.add_suffix(self.evening)
        work.add(evening)

        flex = Adw.ActionRow(title="Extra focus time", subtitle="Added to the work target every day. Usually 0:00.")
        self.flex = TimeEntry(time(0, 0), max_hour=6)
        total = ctx.settings.flex
        self.flex.time = time(int(total.total_seconds() // 3600) % 24, int(total.total_seconds() // 60) % 60)
        self.flex.connect("changed", self._save_flex)
        flex.add_suffix(self.flex)
        work.add(flex)
        self.column.append(work)

        # -- today's two plans, side by side
        self.plans = Adw.PreferencesGroup(title="Today’s plans", description="What each kind of day would ask of you.")
        self.column.append(self.plans)

        # -- activities
        self.activities = Adw.PreferencesGroup(
            title="Activities", description="Calls, the gym, meals, a custom wake-up or sleep time."
        )
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Add an activity")
        add.add_css_class("flat")
        add.connect("clicked", lambda _b: self.edit(None))
        self.activities.set_header_suffix(add)
        self.column.append(self.activities)

        self._rows: list[Gtk.Widget] = []
        self._plan_rows: list[Gtk.Widget] = []
        self._quiet = False
        self.refresh()

    # -- settings ----------------------------------------------------------

    def _save_evening(self, _entry) -> None:
        if not self._quiet:
            self.ctx.settings.evening_start = self.evening.time
            self.ctx.changed("rhythm")

    def _save_flex(self, _entry) -> None:
        if not self._quiet:
            t = self.flex.time
            self.ctx.settings.flex = timedelta(hours=t.hour, minutes=t.minute)
            self.ctx.changed("rhythm")

    def edit(self, activity) -> None:
        ActivityDialog(self.get_root(), self.ctx, activity).present()

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        self._quiet = True
        self._render_plans()
        self._render_activities()
        self._quiet = False

    def _render_plans(self) -> None:
        for row in self._plan_rows:
            self.plans.remove(row)
        self._plan_rows.clear()
        today = datetime.now().date()
        prayer_day = self.ctx.library.day(self.ctx.location.slug, today)
        self.plans.set_visible(prayer_day is not None)
        if not prayer_day:
            return
        tomorrow = self.ctx.library.day(self.ctx.location.slug, today + timedelta(days=1))
        for kind in (DayKind.STEADY, DayKind.PUSH):
            plan = plan_day(
                today, kind, fajr=prayer_day.fajr, isha=prayer_day.isha,
                next_fajr=tomorrow.fajr if tomorrow else None,
                evening_start=self.ctx.settings.evening_start, flex=self.ctx.settings.flex,
            )
            blocks = ", ".join(f"{b.start:%H:%M}–{b.end:%H:%M}" for b in plan.blocks)
            lines = [f"{blocks} · bed {plan.bedtime:%H:%M}"]
            if plan.sleep_lost.total_seconds() > 0:
                lines.append(f"{human_duration(plan.sleep_lost)} of sleep given up")
            row = Adw.ActionRow(title=f"{kind.label} · {kind.percent}", subtitle="\n".join(lines), activatable=False)
            row.add_suffix(label(human_duration(plan.target), "heading", "fj-numeric"))
            if kind is DayKind.PUSH:
                row.set_subtitle_lines(3)
            self.plans.add(row)
            self._plan_rows.append(row)

    def _render_activities(self) -> None:
        for row in self._rows:
            self.activities.remove(row)
        self._rows.clear()
        items = self.ctx.db.list_activities()
        if not items:
            row = Adw.ActionRow(title="No activities yet", subtitle="Add one to see how it shapes your day.", activatable=False)
            row.add_css_class("dim-label")
            self.activities.add(row)
            self._rows.append(row)
            return
        for a in items:
            flags = [t for t, on in (("alarm at start", a.alarm_at_start), ("alarm at end", a.alarm_at_end)) if on]
            detail = " · ".join([a.category_label, mask_label(a.days_mask), *flags])
            row = Adw.ActionRow(title=a.title, subtitle=detail, activatable=True)
            row.add_prefix(label(f"{a.start}–{a.end}", "fj-time", "heading"))
            toggle = Gtk.Switch(active=a.enabled, valign=Gtk.Align.CENTER)
            toggle.connect("notify::active", self._toggle, a.id)
            row.add_suffix(toggle)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda _r, item=a: self.edit(item))
            if not a.enabled:
                row.add_css_class("fj-past")
            self.activities.add(row)
            self._rows.append(row)

    def _toggle(self, switch: Gtk.Switch, _pspec, activity_id: int) -> None:
        if self._quiet:
            return
        self.ctx.db.set_activity_enabled(activity_id, switch.get_active())
        self.ctx.changed("rhythm")
