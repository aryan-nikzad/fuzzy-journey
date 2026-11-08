from __future__ import annotations

from datetime import date

from ... import planner
from ...models import TaskStatus
from ...rhythm import OVERTIME_RANGE, OVERTIME_STEP
from ...timeutil import human_duration
from ...timeutil import now as clock_now
from ..context import Context
from ..focus import minutes_text
from ..gi_setup import Adw, Gdk, Gtk
from ..widgets import label


class OvertimeDialog(Adw.Window):
    """Night work, after the last prayer. Not recommended, so the better way out comes first.

    Step one says why, and offers to move tasks to tomorrow. Only a second, deliberate step
    chooses the hours, with the sleep it costs shown beside them.
    """

    def __init__(self, parent: Gtk.Window, ctx: Context, day: date, current: int = 0) -> None:
        super().__init__(transient_for=parent, modal=True, title="Night work", default_width=460, default_height=520)
        self.ctx, self.day, self.current = ctx, day, current
        self.open_tasks = [t for t in ctx.db.tasks_on(day) if t.status is TaskStatus.UNSET and not t.is_prayer]

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        self.save_button = Gtk.Button(label="Save" if current else "Add night work", visible=bool(current))
        self.save_button.connect("clicked", self._on_save)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.save_button)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for side in ("top", "bottom"):
            getattr(body, f"set_margin_{side}")(18)
        for side in ("start", "end"):
            getattr(body, f"set_margin_{side}")(18)
        body.append(label("Work into the night?", "title-2"))
        body.append(label(
            "Not recommended. Sleep is where the day’s work settles, and tired work is slower and "
            "carries more mistakes, so night work often costs more than it saves. Moving a few tasks "
            "to tomorrow is usually better for the work, for your discipline and for your health.",
            wrap=True,
        ))
        if self.open_tasks:
            n, total = len(self.open_tasks), sum(t.minutes for t in self.open_tasks)
            body.append(label(
                f"{n} task{'s are' if n != 1 else ' is'} still open ({minutes_text(total)}).",
                "dim-label", wrap=True,
            ))

        self.move = Gtk.Button(
            label="Move tasks to tomorrow" if self.open_tasks else "Plan tomorrow instead", halign=Gtk.Align.START
        )
        self.move.add_css_class("suggested-action")
        self.move.add_css_class("pill")
        self.move.connect("clicked", self._on_move)
        body.append(self.move)

        self.anyway = Gtk.Button(label="Work into the night anyway", halign=Gtk.Align.START, visible=not current)
        self.anyway.add_css_class("flat")
        self.anyway.connect("clicked", lambda _b: self._reveal())
        body.append(self.anyway)

        group = Adw.PreferencesGroup()
        self.length = Adw.SpinRow.new_with_range(OVERTIME_RANGE[0], OVERTIME_RANGE[1], OVERTIME_STEP)
        self.length.set_title("Night work (minutes)")
        self.length.set_snap_to_ticks(True)
        self.length.set_value(current or OVERTIME_RANGE[0])
        self.length.connect("notify::value", self._preview)
        group.add(self.length)
        self.cost = label("", "caption", "dim-label", wrap=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(group)
        box.append(self.cost)
        self.revealer = Gtk.Revealer(child=box, reveal_child=bool(current),
                                     transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        body.append(self.revealer)
        self._preview()

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=480, child=body))
        view = Adw.ToolbarView(content=scroller)
        view.add_top_bar(header)
        self.set_content(view)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, key, *_: self.close() or True if key == Gdk.KEY_Escape else False)
        self.add_controller(keys)

    def _minutes(self) -> int:
        return int(round(self.length.get_value() / OVERTIME_STEP)) * OVERTIME_STEP

    def _preview(self, *_args) -> None:
        minutes = self._minutes()
        view = planner.build_view(self.ctx.db, self.ctx.library, clock_now(), overtime=minutes)
        self.length.set_subtitle(minutes_text(minutes))
        if not view.plan or not view.plan.overtime or view.bedtime is None:
            self.cost.set_text("")
            return
        night = view.plan.overtime
        text = f"{night.start:%H:%M} to {night.end:%H:%M} · bed {view.bedtime:%H:%M}"
        if view.sleep is not None:
            text += f" · {human_duration(view.sleep)} of sleep"
        if view.sleep_lost.total_seconds() > 0:
            text += f" · {human_duration(view.sleep_lost)} given up"
        self.cost.set_text(text)

    def _reveal(self) -> None:
        self.anyway.set_visible(False)
        self.revealer.set_reveal_child(True)
        self.save_button.set_visible(True)

    def _on_move(self, _button) -> None:
        parent = self.get_transient_for()
        self.close()
        if self.open_tasks:
            from .review_dialog import ReviewDialog

            ReviewDialog(parent, self.ctx, self.day).present()
        else:
            self.ctx.show_page("tomorrow")

    def _on_save(self, _button) -> None:
        self.ctx.db.set_day_overtime(self.day, self._minutes())
        self.ctx.changed("day")
        self.close()
