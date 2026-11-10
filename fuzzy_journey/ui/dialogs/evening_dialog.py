from __future__ import annotations

from collections.abc import Callable
from datetime import date

from ... import planner
from ...rhythm import EVENING_RANGE, EVENING_STEP
from ...timeutil import human_duration
from ...timeutil import now as clock_now
from ..context import Context
from ..focus import minutes_text
from ..gi_setup import Adw, Gdk, Gtk
from ..widgets import label


class EveningDialog(Adw.Window):
    """Optional evening work, for any working day. Not recommended, and it says what it costs.

    Useful when the day was lost to sleep, a late start or long pauses. The block begins at the
    evening-start time; only what runs past Isha pushes bedtime, and the sleep given up is shown.
    """

    def __init__(
        self, parent: Gtk.Window, ctx: Context, day: date, current: int = 0, *,
        suggested: int | None = None, on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(transient_for=parent, modal=True, title="Evening work", default_width=460, default_height=520)
        self.ctx, self.day, self.current, self.on_saved = ctx, day, current, on_saved
        saved = ctx.today_view() if day == clock_now().date() else ctx.day_view(day)
        self._has_evening = bool(saved.plan and saved.plan.evening)  # one already exists: extending it is fine

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        self.save_button = Gtk.Button(label="Save" if current else "Add evening work")
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", self._on_save)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.save_button)
        if current:
            remove = Gtk.Button(label="Remove")
            remove.add_css_class("destructive-action")
            remove.connect("clicked", self._on_remove)
            header.pack_end(remove)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18)
        body.append(label("Work this evening?", "title-2"))
        body.append(label(
            "Not recommended, but sometimes the day went elsewhere: you slept long, started late or "
            "paused for a long while. An evening block gives the missing focus time back. It starts at "
            "your evening time, and the sleep it costs is shown below. Anything that still does not "
            "fit can wait for tomorrow.",
            wrap=True,
        ))
        group = Adw.PreferencesGroup()
        low, high = EVENING_RANGE
        self.length = Adw.SpinRow.new_with_range(low, high, EVENING_STEP)
        self.length.set_title("Evening work (minutes)")
        self.length.set_snap_to_ticks(True)
        start = current or suggested or low
        self.length.set_value(min(high, max(low, start)))
        self.length.connect("notify::value", self._preview)
        group.add(self.length)
        body.append(group)
        self.cost = label("", "caption", "dim-label", wrap=True)
        body.append(self.cost)
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
        return int(round(self.length.get_value() / EVENING_STEP)) * EVENING_STEP

    def _fits(self, preview) -> bool:
        """An evening that began before now cannot be added: its hours would count as already lived."""
        block = preview.plan.evening if preview.plan else None
        if block is None:
            return False
        return self._has_evening or self.day != clock_now().date() or block.start > clock_now()

    def _preview(self, *_args) -> None:
        minutes = self._minutes()
        self.length.set_subtitle(minutes_text(minutes))
        view = planner.build_view(self.ctx.db, self.ctx.library, clock_now(), evening=minutes) \
            if self.day == clock_now().date() else self.ctx.day_view(self.day)
        block = view.plan.evening if view.plan else None
        ok = block is not None and self._fits(view)
        self.save_button.set_sensitive(ok)
        if block is None:
            self.cost.set_text("This day has no evening to add to.")
            return
        text = f"{block.start:%H:%M} to {block.end:%H:%M}"
        if view.bedtime is not None:
            text += f" · bed {view.bedtime:%H:%M}"
        if view.sleep is not None:
            text += f" · {human_duration(view.sleep)} of sleep"
        if view.sleep_lost.total_seconds() > 0:
            text += f" · {human_duration(view.sleep_lost)} given up"
        if not ok:
            text += f"\nThe evening started at {block.start:%H:%M}, which has passed. Move it earlier in Preferences, or leave the rest for tomorrow."
        self.cost.set_text(text)

    def _on_save(self, _button) -> None:
        self.ctx.db.set_day_evening(self.day, self._minutes())
        self.ctx.changed("day")
        self.close()
        if self.on_saved:
            self.on_saved()

    def _on_remove(self, _button) -> None:
        self.ctx.db.set_day_evening(self.day, 0)
        self.ctx.changed("day")
        self.close()
