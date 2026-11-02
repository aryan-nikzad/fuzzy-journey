from __future__ import annotations

from ...rhythm import DayKind, WorkStatus
from ...timeutil import countdown, human_duration
from ...timeutil import now as clock_now
from ...today import RowState, Slot, TodayView
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import DayBar, KindSelector, clear, label
from .base import Page

_STATUS = {
    WorkStatus.ACTIVE: "WORK LEFT TODAY",
    WorkStatus.PAUSED: "PAUSED",
    WorkStatus.UPCOMING: "NEXT UP",
    WorkStatus.DONE: "TODAY",
}


class TodayPage(Page):
    listens_to = frozenset({"tick", "day", "rhythm", "alarms", "data", "location"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._signature: tuple = ()

        # Shown instead of the day when no timetable is available.
        self.missing = Adw.StatusPage(
            icon_name="weather-clear-night-symbolic",
            title="No prayer times yet",
            description="The day starts at Fajr, so Fuzzy Journey needs this year's timetable once.",
            vexpand=True,
        )
        self.missing_button = Gtk.Button(label="Download prayer times", halign=Gtk.Align.CENTER)
        self.missing_button.add_css_class("suggested-action")
        self.missing_button.add_css_class("pill")
        self.missing_button.connect("clicked", self._download)
        self.missing.set_child(self.missing_button)

        self.day_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # -- header line
        top = Gtk.Box(spacing=12)
        self.date_label = label("", "heading", "dim-label")
        self.date_label.set_hexpand(True)
        top.append(self.date_label)
        self.bank_button = Gtk.Button()
        self.bank_button.add_css_class("flat")
        self.bank_button.connect("clicked", lambda _b: ctx.show_page("bank"))
        top.append(self.bank_button)
        self.day_box.append(top)

        # -- hero
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.overline = label("", "fj-overline")
        self.hero = label("", "fj-hero")
        self.hero_sub = label("", "fj-hero-sub", wrap=True)
        for w in (self.overline, self.hero, self.hero_sub):
            hero.append(w)
        self.day_box.append(hero)

        # -- shape of the day
        shape = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.bar = DayBar()
        shape.append(self.bar)
        ends = Gtk.Box()
        self.wake_label = label("", "caption", "dim-label", "fj-numeric")
        self.wake_label.set_hexpand(True)
        self.bed_label = label("", "caption", "dim-label", "fj-numeric")
        ends.append(self.wake_label)
        ends.append(self.bed_label)
        shape.append(ends)
        self.day_box.append(shape)

        # -- day kind
        kind_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.selector = KindSelector()
        self.selector.connect("kind-selected", self._on_kind)
        kind_box.append(self.selector)
        self.summary = label("", "caption", "dim-label", wrap=True, xalign=0.5)
        kind_box.append(self.summary)
        self.day_box.append(kind_box)

        # -- timeline
        self.timeline = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.timeline.add_css_class("boxed-list")
        self.day_box.append(self.timeline)
        self.next_alarm = label("", "caption", "dim-label", xalign=0.5)
        self.day_box.append(self.next_alarm)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.add_named(self.day_box, "day")
        self.stack.add_named(self.missing, "missing")
        self.column.append(self.stack)
        self.refresh()

    # -- actions -----------------------------------------------------------

    def _on_kind(self, _selector, code: str) -> None:
        day = clock_now().date()
        existing = self.ctx.db.day_entries(day, day).get(day)
        self.ctx.db.set_day_kind(day, DayKind.from_code(code), existing.note if existing else "")
        self.ctx.changed("day")

    def _download(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        button.set_label("Downloading…")

        def done(ok: bool, message: str) -> None:
            button.set_sensitive(True)
            button.set_label("Download prayer times")
            self.ctx.toast(message if ok else f"Download failed: {message}")

        self.ctx.download_year(clock_now().year, done)

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        view = self.ctx.today_view()
        if not view.has_prayer_data and not view.timeline:
            location = self.ctx.location.name
            self.missing.set_description(
                f"The day starts at Fajr, so Fuzzy Journey needs the {view.day.year} timetable "
                f"for {location} once. After that it works offline."
            )
            self.stack.set_visible_child_name("missing")
            return
        self.stack.set_visible_child_name("day")
        self._render_header(view)
        self._render_hero(view)
        self._render_shape(view)
        self._render_timeline(view)

    def _render_header(self, view: TodayView) -> None:
        self.date_label.set_text(view.now.strftime("%A, %-d %B"))
        bank = self.ctx.bank(view.day)
        balance = f"{bank.balance:+g}" if bank.balance else "0"
        self.bank_button.set_label(f"Bank {balance} d")
        self.bank_button.set_tooltip_text("Rest banked from Push days. Open the bank.")
        self.selector.set_kind(view.kind)

    def _render_hero(self, view: TodayView) -> None:
        focus = view.focus
        if view.kind is DayKind.REST:
            self.overline.set_text("TODAY")
            self.hero.set_text("Rest day")
            self.hero_sub.set_text("No work today. One day is spent from the bank.")
        elif focus is None:
            self.overline.set_text("TODAY")
            self.hero.set_text("—")
            self.hero_sub.set_text("No work blocks are planned for today.")
        else:
            p = focus.progress
            self.overline.set_text(_STATUS[p.status])
            if p.status is WorkStatus.DONE:
                self.hero.set_text("Work done")
                self.hero_sub.set_text(
                    f"{human_duration(view.work_total)} of focus. The rest of the day is yours."
                )
            elif p.status is WorkStatus.UPCOMING:
                self.hero.set_text(f"in {countdown(p.start - view.now)}")
                self.hero_sub.set_text(
                    f"{focus.title} starts at {p.start:%H:%M} · {human_duration(p.planned)} of focus"
                )
            elif p.status is WorkStatus.PAUSED and p.pause:
                self.hero.set_text(human_duration(view.work_remaining))
                self.hero_sub.set_text(
                    f"Paused for {p.pause.title} until {p.pause.span.end:%H:%M} · finishes {p.end:%H:%M}"
                )
            else:
                self.hero.set_text(human_duration(view.work_remaining))
                later = [w for w in view.work if w.progress.start > p.start]
                tail = f" · then {later[0].title.lower()} at {later[0].progress.start:%H:%M}" if later else ""
                self.hero_sub.set_text(f"{focus.title} · finishes {p.end:%H:%M}{tail}")

    def _render_shape(self, view: TodayView) -> None:
        if view.wake and view.bedtime:
            self.bar.set_visible(True)
            self.bar.set_data(view.wake, view.bedtime, view.segments, view.prayer_marks, view.now)
            self.wake_label.set_text(f"Wake  {view.wake:%H:%M}")
            self.bed_label.set_text(f"{view.bedtime:%H:%M}  Sleep")
        else:
            self.bar.set_visible(False)
            self.wake_label.set_text("")
            self.bed_label.set_text("")

        if not view.plan:
            self.summary.set_text("")
            return
        if view.kind is DayKind.REST:
            self.summary.set_text(f"No work · bed {view.bedtime:%H:%M} · {human_duration(view.sleep)} of sleep")
            return
        parts = [f"{human_duration(view.plan.target)} of work", f"bed {view.bedtime:%H:%M}",
                 f"{human_duration(view.sleep)} of sleep"]
        if view.sleep_lost.total_seconds() > 0:
            parts.append(f"{human_duration(view.sleep_lost)} given up")
        self.summary.set_text(" · ".join(parts))

    def _render_timeline(self, view: TodayView) -> None:
        if view.next_alarm:
            self.next_alarm.set_text(
                f"Next alarm: {view.next_alarm.title} at {view.next_alarm.due:%H:%M} "
                f"(in {countdown(view.next_alarm.due - view.now)})"
            )
        else:
            self.next_alarm.set_text("No more alarms today")

        signature = tuple(r.signature for r in view.timeline)
        if signature == self._signature:
            return
        self._signature = signature
        clear(self.timeline)
        for row in view.timeline:
            self.timeline.append(self._row(row))

    @staticmethod
    def _row(item) -> Adw.ActionRow:
        row = Adw.ActionRow(title=item.title, subtitle=item.detail, activatable=False, selectable=False)
        row.set_title_lines(1)
        row.add_prefix(label(item.start.strftime("%H:%M"), "fj-time", "heading", xalign=0.0))
        if item.has_alarm:
            bell = Gtk.Image.new_from_icon_name("alarm-symbolic")
            bell.add_css_class("dim-label")
            bell.set_tooltip_text("An alarm is set")
            row.add_suffix(bell)
        if item.state is RowState.PAST:
            row.add_css_class("fj-past")
        elif item.state is RowState.NOW:
            row.add_css_class("fj-now")
        if item.slot in (Slot.PRAYER, Slot.WAKE, Slot.SLEEP, Slot.REMINDER):
            row.add_css_class("fj-quiet")
        return row
