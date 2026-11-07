"""The two focus widgets shared by Today and Tomorrow: the task list and the pomodoro card."""

from __future__ import annotations

from datetime import date, timedelta

from .. import pomodoro, tasks
from ..models import Task, TaskStatus
from ..pomodoro import SegmentKind
from ..timeutil import countdown, human_duration
from ..timeutil import now as clock_now
from .context import Context
from .gi_setup import Adw, GLib, Gtk
from .widgets import clear, label


def minutes_text(minutes: int) -> str:
    return human_duration(timedelta(minutes=minutes))


def _menu_item(text: str, callback, *, destructive: bool = False) -> Gtk.Button:
    button = Gtk.Button(label=text, halign=Gtk.Align.FILL)
    button.add_css_class("flat")
    if destructive:
        button.add_css_class("destructive-action")
    button.get_child().set_halign(Gtk.Align.START)
    button.connect("clicked", callback)
    return button


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


class TaskList(Gtk.Box):
    """One day's tasks, how much of its focus time they use, and the controls to change them."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.ctx = ctx
        self.day = clock_now().date()
        self.focus = 0
        self._signature: tuple = ()

        head = Gtk.Box(spacing=12)
        head.append(label("Tasks", "heading", xalign=0.0))
        self.meter_label = label("", "caption", "dim-label", xalign=1.0)
        self.meter_label.set_hexpand(True)
        head.append(self.meter_label)
        self.append(head)

        self.bar = Gtk.ProgressBar()
        self.bar.add_css_class("fj-meter")
        self.append(self.bar)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.connect("row-activated", self._on_activated)
        self.append(self.list)

        self.add_row = Adw.ActionRow(title="Add a task", activatable=True)
        self.add_row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))

    # -- rendering ---------------------------------------------------------

    def show_day(self, day: date, focus_minutes: int) -> None:
        self.day, self.focus = day, focus_minutes
        mode = self.ctx.settings.task_order
        items = tasks.in_order(self.ctx.db.tasks_on(day), mode)
        signature = (day, focus_minutes, mode, tuple((t.id, t.title, t.minutes, t.level, t.status, t.position) for t in items))
        if signature == self._signature:
            return
        self._signature = signature

        load = tasks.load(items, focus_minutes)
        self.bar.set_visible(focus_minutes > 0)
        self.bar.set_fraction(load.fraction)
        for widget in (self.bar, self.meter_label):
            (widget.add_css_class if load.over_recommended else widget.remove_css_class)("fj-warn")
        if focus_minutes <= 0:
            self.meter_label.set_text("No focus time this day")
        else:
            text = f"{minutes_text(load.planned)} of {minutes_text(focus_minutes)}"
            if load.over_recommended:
                text += f" · over {minutes_text(pomodoro.recommended(focus_minutes))} recommended"
            self.meter_label.set_text(text)

        clear(self.list)
        open_tasks = [t for t in items if t.status is TaskStatus.UNSET]
        for task in items:
            self.list.append(self._row(task, open_tasks, mode))

        room = load.left >= tasks.MIN_MINUTES
        self.add_row.set_sensitive(room)
        self.add_row.set_subtitle(
            "" if room else "No focus time is planned for this day." if focus_minutes <= 0
            else "This day’s focus time is full."
        )
        self.list.append(self.add_row)

    def _row(self, task: Task, open_tasks: list[Task], mode: str) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(task.title), activatable=False)
        parts = [minutes_text(task.minutes)]
        if mode == tasks.ORDER_LEVEL and task.status is TaskStatus.UNSET:
            parts.append(task.level_label)
        if task.status in (TaskStatus.CARRIED, TaskStatus.CANCELLED):
            parts.append(task.status.label)
        row.set_subtitle(" · ".join(parts))
        settled = task.status is not TaskStatus.UNSET
        if settled:
            row.add_css_class("fj-settled")

        started = self.day <= clock_now().date()
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=task.status is TaskStatus.DONE, sensitive=started)
        check.set_tooltip_text("Done" if started else "A future day: nothing to settle yet")
        check.connect("toggled", lambda b, t=task: self._set(t, TaskStatus.DONE if b.get_active() else TaskStatus.UNSET))
        row.add_prefix(check)

        menu = Gtk.MenuButton(icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Task options")
        menu.add_css_class("flat")
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        popover.set_child(box)
        menu.set_popover(popover)

        def item(text, callback, **kw):
            box.append(_menu_item(text, lambda _b: (popover.popdown(), callback()), **kw))

        item("Edit…", lambda: self._edit(task))
        if mode == tasks.ORDER_SEQUENCE and task in open_tasks:
            i = open_tasks.index(task)
            if i > 0:
                item("Move up", lambda: self._move(task, -1, open_tasks))
            if i < len(open_tasks) - 1:
                item("Move down", lambda: self._move(task, 1, open_tasks))
        if started:
            if task.status is not TaskStatus.CARRIED:
                target = max(task.day + timedelta(days=1), clock_now().date())
                item("Move to tomorrow" if target > clock_now().date() else "Move to today",
                     lambda: self._set(task, TaskStatus.CARRIED))
            if task.status is not TaskStatus.CANCELLED:
                item("Cancel task", lambda: self._set(task, TaskStatus.CANCELLED))
            if settled:
                item("Reset status", lambda: self._set(task, TaskStatus.UNSET))
        item("Delete", lambda: self._delete(task), destructive=True)
        row.add_suffix(menu)
        return row

    # -- actions -----------------------------------------------------------

    def _set(self, task: Task, status: TaskStatus) -> None:
        if task.status is status:
            return
        self.ctx.db.set_task_status(task.id, status, today=clock_now().date())
        self.ctx.changed("tasks")

    def _move(self, task: Task, direction: int, open_tasks: list[Task]) -> None:
        self.ctx.db.move_task(task, direction, open_tasks)
        self.ctx.changed("tasks")

    def _delete(self, task: Task) -> None:
        self.ctx.db.delete_task(task.id)
        self.ctx.changed("tasks")

    def _edit(self, task: Task | None) -> None:
        from .dialogs.task_dialog import TaskDialog

        TaskDialog(self.get_root(), self.ctx, self.day, self.focus, task).present()

    def _on_activated(self, _list, row) -> None:
        if row is self.add_row:
            self._edit(None)


# --------------------------------------------------------------------------
# Pomodoro card
# --------------------------------------------------------------------------


class FocusCard(Gtk.Box):
    """What to do right now: the current block, its countdown, and Pause / Resume."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.ctx = ctx
        self.add_css_class("fj-card")
        self._schedule: pomodoro.Schedule | None = None
        self._pauses: list = []
        self._day = clock_now().date()

        self.overline = label("", "fj-overline")
        self.timer = label("", "fj-timer")
        self.detail = label("", "fj-hero-sub", wrap=True)
        for w in (self.overline, self.timer, self.detail):
            self.append(w)

        self.buttons = Gtk.Box(spacing=8, margin_top=8)
        self.pause = Gtk.Button(halign=Gtk.Align.START)
        self.pause.add_css_class("pill")
        self.pause.connect("clicked", self._on_pause)
        self.settle = Gtk.Button(label="Settle today’s tasks")
        self.settle.add_css_class("suggested-action")
        self.settle.add_css_class("pill")
        self.settle.connect("clicked", self._on_settle)
        self.plan = Gtk.Button(label="Plan tomorrow")
        self.plan.add_css_class("pill")
        self.plan.connect("clicked", lambda _b: ctx.show_page("tomorrow"))
        for b in (self.pause, self.settle, self.plan):
            self.buttons.append(b)
        self.append(self.buttons)

        GLib.timeout_add_seconds(1, self._tick)

    def update(self, schedule: pomodoro.Schedule | None, day: date) -> None:
        self._schedule, self._day = schedule, day
        self._pauses = self.ctx.db.pomodoro_pauses(day)
        self._render()

    def _tick(self) -> bool:
        if self.get_mapped() and self.get_visible():
            self._render()
        return GLib.SOURCE_CONTINUE

    def _render(self) -> None:
        now = clock_now()
        schedule = self._schedule
        if not schedule or not schedule.segments:
            self.set_visible(False)
            return
        segments = pomodoro.live_segments(schedule, self._pauses, now)
        paused = any(end is None for _start, end in self._pauses)
        cur = pomodoro.current(segments, now)
        upcoming = next((s for s in segments if s.start > now), None)
        if cur is None and not paused and upcoming is None:
            self.set_visible(False)  # the day's work is behind us
            return
        self.set_visible(True)
        for b in (self.pause, self.settle, self.plan):
            b.set_visible(False)

        if cur is None and not paused:
            self.overline.set_text("NEXT")
            self.timer.set_text(f"in {countdown(upcoming.start - now)}")
            self.detail.set_text(f"{upcoming.title} at {upcoming.start:%H:%M} · {upcoming.minutes} min")
            return

        if cur is not None and cur.kind is SegmentKind.PLANNING:
            self.overline.set_text("PLANNING")
            self.timer.set_text(self._clock(cur.end - now))
            self.detail.set_text("Settle today’s tasks, then plan tomorrow.")
            self.settle.set_visible(True)
            self.plan.set_visible(True)
            return

        self.pause.set_visible(True)
        self.pause.set_label("Resume" if paused else "Pause")
        (self.pause.add_css_class if paused else self.pause.remove_css_class)("suggested-action")
        self.pause.set_tooltip_text("Carry on where you stopped" if paused else "Stop the clock, then resume later")
        if cur is None:
            self.overline.set_text("PAUSED")
            self.timer.set_text("—")
            self.detail.set_text("Resume when you are ready.")
            return
        focus_blocks = [s for s in schedule.segments if s.kind is SegmentKind.FOCUS]
        following = next((s for s in segments if s.start >= cur.end), None)
        then = f" · then {following.title.lower()}" if following else ""
        if cur.kind is SegmentKind.FOCUS:
            n = next(i for i, s in enumerate(schedule.segments) if s.start == cur.start and s.kind is cur.kind)
            number = 1 + sum(1 for s in schedule.segments[:n] if s.kind is SegmentKind.FOCUS)
            self.overline.set_text("PAUSED" if paused else f"FOCUS {number} OF {len(focus_blocks)}")
        else:
            self.overline.set_text("PAUSED" if paused else cur.title.upper())
        self.timer.set_text(self._clock(cur.end - now))
        self.detail.set_text(f"{cur.title} · until {cur.end:%H:%M}{then}")

    @staticmethod
    def _clock(left: timedelta) -> str:
        total = max(0, int(left.total_seconds()))
        return f"{total // 60:02d}:{total % 60:02d}"

    def _on_pause(self, _button) -> None:
        now = clock_now()
        if any(end is None for _s, end in self._pauses):
            self.ctx.db.resume_pomodoro(self._day, now)
        else:
            self.ctx.db.pause_pomodoro(self._day, now)
        self.ctx.changed("pomodoro")

    def _on_settle(self, _button) -> None:
        from .dialogs.review_dialog import ReviewDialog

        ReviewDialog(self.get_root(), self.ctx, self._day).present()
