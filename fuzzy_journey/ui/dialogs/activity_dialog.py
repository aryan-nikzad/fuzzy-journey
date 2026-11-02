from __future__ import annotations

from datetime import time

from ...models import ACTIVITY_CATEGORIES, Activity
from ...timeutil import ALL_DAYS
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import DayChooser, SoundEditor, TimeEntry, confirm
from .form import FormDialog, group

CATEGORY_HINTS = {
    "work": "Counts as extra focused work. Other activities pause its clock.",
    "wake": "Overrides the wake time taken from Fajr.",
    "sleep": "Overrides the bedtime taken from Isha.",
}


class ActivityDialog(FormDialog):
    """Create or edit a recurring activity."""

    def __init__(self, parent: Gtk.Window, ctx: Context, activity: Activity | None = None) -> None:
        self.ctx = ctx
        self.activity = activity
        super().__init__(parent, "Edit activity" if activity else "New activity", height=760)

    def build(self) -> None:
        a = self.activity
        main = group(description="A recurring block of your day. Activities that overlap work pause its clock.")
        self.title_row = Adw.EntryRow(title="Name")
        self.title_row.set_text(a.title if a else "")
        main.add(self.title_row)

        self.keys = list(ACTIVITY_CATEGORIES)
        self.category_row = Adw.ComboRow(title="Kind")
        self.category_row.set_model(Gtk.StringList.new(list(ACTIVITY_CATEGORIES.values())))
        self.category_row.set_selected(self.keys.index(a.category) if a and a.category in self.keys else 0)
        self.category_row.connect("notify::selected", self._hint)
        main.add(self.category_row)

        start_row = Adw.ActionRow(title="Starts")
        self.start = TimeEntry(a.start_clock if a else time(16, 0))
        start_row.add_suffix(self.start)
        main.add(start_row)
        end_row = Adw.ActionRow(title="Ends")
        self.end = TimeEntry(a.end_clock if a else time(17, 0))
        end_row.add_suffix(self.end)
        main.add(end_row)
        self.body.append(main)
        self.hint = group()
        self.body.append(self.hint)

        repeat = group("Repeat")
        days_row = Adw.ActionRow(title="Days")
        self.days = DayChooser(a.days_mask if a else ALL_DAYS)
        days_row.add_suffix(self.days)
        repeat.add(days_row)
        self.body.append(repeat)

        alarms = group("Alarms")
        self.start_alarm = Adw.SwitchRow(title="Alarm at the start")
        self.start_alarm.set_active(a.alarm_at_start if a else False)
        self.end_alarm = Adw.SwitchRow(title="Alarm at the end")
        self.end_alarm.set_active(a.alarm_at_end if a else False)
        alarms.add(self.start_alarm)
        alarms.add(self.end_alarm)
        self.body.append(alarms)

        sound = group("Sound")
        self.sound = SoundEditor(a.sound if a else None)
        for row in self.sound.rows:
            sound.add(row)
        self.body.append(sound)

        if a:
            state = group()
            self.enabled_row = Adw.SwitchRow(title="Enabled")
            self.enabled_row.set_active(a.enabled)
            state.add(self.enabled_row)
            self.body.append(state)
            danger = group()
            delete = Gtk.Button(label="Delete activity", halign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.add_css_class("pill")
            delete.connect("clicked", self._delete)
            danger.add(delete)
            self.body.append(danger)
        self._hint()

    def _hint(self, *_args) -> None:
        key = self.keys[self.category_row.get_selected()]
        self.hint.set_description(CATEGORY_HINTS.get(key, ""))
        self.hint.set_visible(key in CATEGORY_HINTS)

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_activity(self.activity.id)
            self.ctx.changed("rhythm")
            self.close()

        confirm(self, f"Delete “{self.activity.title}”?", "This activity will be removed from your routine.", "Delete", go)

    def save(self) -> bool:
        mask = self.days.mask
        if mask == 0:
            self.error("Choose at least one day.")
            return False
        if self.start.text == self.end.text:
            self.error("Start and end can’t be the same time.")
            return False
        activity = self.activity or Activity(title="", category="personal", start="16:00", end="17:00")
        activity.title = self.title_row.get_text().strip() or "Activity"
        activity.category = self.keys[self.category_row.get_selected()]
        activity.start, activity.end = self.start.text, self.end.text
        activity.days_mask = mask
        activity.alarm_at_start = self.start_alarm.get_active()
        activity.alarm_at_end = self.end_alarm.get_active()
        activity.sound = self.sound.sound
        activity.enabled = self.enabled_row.get_active() if self.activity else True
        self.ctx.db.save_activity(activity)
        self.ctx.changed("rhythm")
        return True
