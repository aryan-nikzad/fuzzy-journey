"""Small reusable widgets. Each does one thing and has no knowledge of pages."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import date, datetime, time

from ..models import SOUND_PRESETS, Sound
from ..rhythm import DayKind
from ..sound import import_custom_audio, play
from ..timeutil import WEEKDAY_NAMES
from .gi_setup import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk

try:  # Gsk is only needed for rounded clipping
    import gi

    gi.require_version("Gsk", "4.0")
    from gi.repository import Gsk
except (ImportError, ValueError):  # pragma: no cover
    Gsk = None


def clear(container: Gtk.Widget) -> None:
    """Remove every child of a Box / ListBox / PreferencesGroup-like container."""
    child = container.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        container.remove(child)
        child = following


def label(text: str = "", *classes: str, xalign: float = 0.0, wrap: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    for css in classes:
        widget.add_css_class(css)
    return widget


# --------------------------------------------------------------------------
# DayBar: the shape of the day
# --------------------------------------------------------------------------


class DayBar(Gtk.Widget):
    """A thin horizontal bar from wake to bedtime.

    Accent = focused work, dark grey = interruptions, light grey = free time.
    Small ticks mark the prayers; a vertical line marks now.
    """

    __gtype_name__ = "FjDayBar"
    BAR_HEIGHT = 12
    TOP = 8

    def __init__(self) -> None:
        super().__init__()
        self._start: datetime | None = None
        self._end: datetime | None = None
        self._segments: tuple = ()
        self._marks: tuple = ()
        self._now: datetime | None = None
        self.set_hexpand(True)
        self.add_css_class("fj-daybar")

    def set_data(self, start, end, segments, marks, now) -> None:
        self._start, self._end = start, end
        self._segments, self._marks, self._now = tuple(segments), tuple(marks), now
        self.queue_draw()

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.VERTICAL:
            height = self.TOP + self.BAR_HEIGHT + 6
            return height, height, -1, -1
        return 120, 400, -1, -1

    def _x(self, moment: datetime, width: float) -> float:
        total = (self._end - self._start).total_seconds()
        fraction = (moment - self._start).total_seconds() / total if total > 0 else 0
        return max(0.0, min(1.0, fraction)) * width

    def do_snapshot(self, snapshot):
        if not (self._start and self._end and self._end > self._start):
            return
        width, height = float(self.get_width()), float(self.get_height())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            found, accent = self.get_style_context().lookup_color("accent_bg_color")
        if not found:
            accent = Gdk.RGBA()
            accent.parse("#3584e4")
        fg = self.get_color()

        def tint(color, alpha):
            rgba = Gdk.RGBA()
            rgba.red, rgba.green, rgba.blue, rgba.alpha = color.red, color.green, color.blue, alpha
            return rgba

        def fill(x0, x1, color, y=self.TOP, h=self.BAR_HEIGHT, radius=3.0):
            if x1 - x0 < 0.5:
                return
            rect = Graphene.Rect().init(x0, y, x1 - x0, h)
            if Gsk is not None:
                rounded = Gsk.RoundedRect()
                rounded.init_from_rect(rect, radius)
                snapshot.push_rounded_clip(rounded)
                snapshot.append_color(color, rect)
                snapshot.pop()
            else:  # pragma: no cover
                snapshot.append_color(color, rect)

        styles = {"free": tint(fg, 0.10), "work": accent, "pause": tint(fg, 0.30)}
        for kind in ("free", "work", "pause"):  # painter's order: interruptions notch the work
            for segment in self._segments:
                if segment.kind == kind:
                    fill(self._x(segment.span.start, width), self._x(segment.span.end, width), styles[kind])

        for mark in self._marks:
            x = self._x(mark, width)
            fill(x - 0.75, x + 0.75, tint(fg, 0.35), y=1, h=5, radius=0.75)

        if self._now and self._start <= self._now <= self._end:
            x = self._x(self._now, width)
            fill(x - 1.25, x + 1.25, tint(fg, 0.9), y=3, h=height - 5, radius=1.25)


# --------------------------------------------------------------------------
# KindSelector: Steady / Push / Rest
# --------------------------------------------------------------------------


class KindSelector(Gtk.Box):
    """Three linked toggle buttons. Emits ``kind-selected`` only for user changes."""

    __gsignals__ = {"kind-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,))}
    #: Recovered is a rescue, not a choice, so it is never offered here.
    CHOICES = (DayKind.STEADY, DayKind.PUSH, DayKind.REST)

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.add_css_class("linked")
        self.add_css_class("fj-kinds")
        self.set_homogeneous(True)
        self._buttons: dict[DayKind, Gtk.ToggleButton] = {}
        self._quiet = False
        first = None
        for kind in self.CHOICES:
            button = Gtk.ToggleButton()
            button.set_child(self._two_lines(kind.label, kind.percent if kind is not DayKind.REST else "no work"))
            button.set_tooltip_text(kind.blurb)
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", self._on_toggled, kind)
            self.append(button)
            self._buttons[kind] = button

    @staticmethod
    def _two_lines(title: str, subtitle: str) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, halign=Gtk.Align.CENTER)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.append(label(title, "heading"))
        box.append(label(subtitle, "caption", "dim-label"))
        return box

    def _on_toggled(self, button: Gtk.ToggleButton, kind: DayKind) -> None:
        if button.get_active() and not self._quiet:
            self.emit("kind-selected", kind.value)

    def set_kind(self, kind: DayKind) -> None:
        self._quiet = True
        self._buttons[kind if kind in self._buttons else DayKind.STEADY].set_active(True)
        self._quiet = False


# --------------------------------------------------------------------------
# Time, weekdays, dates
# --------------------------------------------------------------------------


class TimeEntry(Gtk.Box):
    """Hours : minutes, two spin buttons. Emits ``changed``."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, value: time = time(9, 0), *, min_hour: int = 0, max_hour: int = 23) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER)
        self.hours = Gtk.SpinButton.new_with_range(min_hour, max_hour, 1)
        self.minutes = Gtk.SpinButton.new_with_range(0, 59, 1)
        for spin in (self.hours, self.minutes):
            spin.set_wrap(True)
            spin.set_numeric(True)
            spin.set_width_chars(2)
            spin.add_css_class("fj-time-spin")
            spin.connect("output", self._format)
            spin.connect("value-changed", lambda *_: self.emit("changed"))
        self.append(self.hours)
        self.append(label(":", "heading"))
        self.append(self.minutes)
        self.time = value

    @staticmethod
    def _format(spin: Gtk.SpinButton) -> bool:
        spin.set_text(f"{int(spin.get_value()):02d}")
        return True

    @property
    def time(self) -> time:
        return time(int(self.hours.get_value()), int(self.minutes.get_value()))

    @time.setter
    def time(self, value: time) -> None:
        self.hours.set_value(value.hour)
        self.minutes.set_value(value.minute)

    @property
    def text(self) -> str:
        return self.time.strftime("%H:%M")


class DayChooser(Gtk.Box):
    """Seven linked toggle buttons for repeat weekdays (Monday is bit 0)."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, mask: int = 127) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, valign=Gtk.Align.CENTER)
        self.add_css_class("linked")
        self._buttons = []
        for name in WEEKDAY_NAMES:
            button = Gtk.ToggleButton(label=name[:2])
            button.set_tooltip_text(name)
            button.add_css_class("fj-day-toggle")
            button.connect("toggled", lambda *_: self.emit("changed"))
            self.append(button)
            self._buttons.append(button)
        self.mask = mask

    @property
    def mask(self) -> int:
        return sum(1 << i for i, b in enumerate(self._buttons) if b.get_active())

    @mask.setter
    def mask(self, value: int) -> None:
        for i, button in enumerate(self._buttons):
            button.set_active(bool(value & (1 << i)))


class DateButton(Gtk.MenuButton):
    """A button that shows a date and opens a calendar popover. Emits ``changed``."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, value: date | None = None) -> None:
        super().__init__(valign=Gtk.Align.CENTER)
        self._calendar = Gtk.Calendar()
        self._popover = Gtk.Popover(child=self._calendar)
        self.set_popover(self._popover)
        self._quiet = False
        self._calendar.connect("day-selected", self._on_selected)
        self._value = value or date.today()
        self.date = self._value

    def _on_selected(self, calendar: Gtk.Calendar) -> None:
        if self._quiet:
            return
        picked = calendar.get_date()
        self._value = date(picked.get_year(), picked.get_month(), picked.get_day_of_month())
        self.set_label(self._value.strftime("%d %b %Y"))
        self._popover.popdown()
        self.emit("changed")

    @property
    def date(self) -> date:
        return self._value

    @date.setter
    def date(self, value: date) -> None:
        self._value = value
        self._quiet = True
        self._calendar.select_day(GLib.DateTime.new_local(value.year, value.month, value.day, 0, 0, 0))
        self._quiet = False
        self.set_label(value.strftime("%d %b %Y"))


# --------------------------------------------------------------------------
# Sound editor: three rows that can live in a group or an expander
# --------------------------------------------------------------------------


class SoundEditor:
    """Rows for choosing a tone: on/off, built-in tone, personal file, preview."""

    def __init__(self, sound: Sound | None = None, on_change: Callable[[Sound], None] | None = None) -> None:
        sound = sound or Sound()
        self._on_change = on_change
        self._custom_path = sound.custom_path
        self._quiet = True

        self.enabled_row = Adw.SwitchRow(title="Play a sound")
        self.enabled_row.set_active(sound.enabled)

        self.tone_row = Adw.ComboRow(title="Tone")
        self.tone_row.set_model(Gtk.StringList.new(list(SOUND_PRESETS.values())))
        keys = list(SOUND_PRESETS)
        self.tone_row.set_selected(keys.index(sound.key) if sound.key in keys else 0)
        preview = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER)
        preview.add_css_class("flat")
        preview.set_tooltip_text("Preview")
        preview.connect("clicked", lambda _b: play(Sound(True, self.sound.key, self._custom_path)))
        self.tone_row.add_suffix(preview)

        self.file_row = Adw.ActionRow(title="Personal sound")
        choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        choose.connect("clicked", self._choose)
        self._clear = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER)
        self._clear.add_css_class("flat")
        self._clear.set_tooltip_text("Use the built-in tone")
        self._clear.connect("clicked", lambda _b: self._set_custom(None))
        self.file_row.add_suffix(self._clear)
        self.file_row.add_suffix(choose)

        self.rows = [self.enabled_row, self.tone_row, self.file_row]
        self._refresh_file_row()
        self._quiet = False
        self.enabled_row.connect("notify::active", self._changed)
        self.tone_row.connect("notify::selected", self._changed)

    @property
    def sound(self) -> Sound:
        keys = list(SOUND_PRESETS)
        index = int(self.tone_row.get_selected())
        return Sound(
            self.enabled_row.get_active(), keys[index] if 0 <= index < len(keys) else "classic", self._custom_path
        )

    def _changed(self, *_args) -> None:
        self.tone_row.set_sensitive(self._custom_path is None)
        if self._on_change and not self._quiet:
            self._on_change(self.sound)

    def _refresh_file_row(self) -> None:
        from pathlib import Path

        self.file_row.set_subtitle(Path(self._custom_path).name if self._custom_path else "Using the built-in tone")
        self._clear.set_visible(self._custom_path is not None)
        self.tone_row.set_sensitive(self._custom_path is None)

    def _set_custom(self, path: str | None) -> None:
        self._custom_path = path
        self._refresh_file_row()
        if self._on_change and not self._quiet:
            self._on_change(self.sound)

    def _choose(self, button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Choose an alarm sound")
        audio = Gtk.FileFilter(name="Audio files")
        for suffix in ("mp3", "wav", "ogg", "flac", "m4a", "aac"):
            audio.add_suffix(suffix)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(audio)
        dialog.set_filters(filters)

        def done(source, result):
            try:
                picked = source.open_finish(result)
            except GLib.Error:
                return  # cancelled
            try:
                self._set_custom(import_custom_audio(picked.get_path()))
            except (ValueError, OSError) as exc:
                self.file_row.set_subtitle(str(exc))

        dialog.open(button.get_root(), None, done)


def confirm(parent: Gtk.Window, heading: str, body: str, action: str, on_accept: Callable[[], None]) -> None:
    """A destructive-action confirmation."""
    dialog = Adw.MessageDialog(transient_for=parent, heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("go", action)
    dialog.set_response_appearance("go", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, response: on_accept() if response == "go" else None)
    dialog.present()
