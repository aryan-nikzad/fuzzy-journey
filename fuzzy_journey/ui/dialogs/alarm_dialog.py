from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ...models import Alarm
from ...timeutil import ALL_DAYS, parse_clock
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import DateButton, DayChooser, SoundEditor, TimeEntry, confirm
from .form import FormDialog, group


class AlarmDialog(FormDialog):
    """Create or edit a reminder."""

    def __init__(self, parent: Gtk.Window, ctx: Context, alarm: Alarm | None = None) -> None:
        self.ctx = ctx
        self.alarm = alarm
        super().__init__(parent, "Edit reminder" if alarm else "New reminder", height=700)

    def build(self) -> None:
        a = self.alarm
        main = group()
        self.title_row = Adw.EntryRow(title="Name")
        self.title_row.set_text(a.title if a else "")
        main.add(self.title_row)

        time_row = Adw.ActionRow(title="Time")
        self.time_entry = TimeEntry(a.clock if a else time(7, 0))
        time_row.add_suffix(self.time_entry)
        main.add(time_row)
        self.body.append(main)

        repeat = group("Repeat")
        self.mode_row = Adw.ComboRow(title="When")
        self.mode_row.set_model(Gtk.StringList.new(["On selected days", "Once, on a date"]))
        self.mode_row.set_selected(1 if a and a.one_shot_date else 0)
        self.mode_row.connect("notify::selected", self._sync_mode)
        repeat.add(self.mode_row)

        self.days_row = Adw.ActionRow(title="Days")
        self.days = DayChooser(a.days_mask if a and a.days_mask else ALL_DAYS)
        self.days_row.add_suffix(self.days)
        repeat.add(self.days_row)

        self.date_row = Adw.ActionRow(title="Date")
        start = date.fromisoformat(a.one_shot_date) if a and a.one_shot_date else date.today()
        self.date_button = DateButton(start)
        self.date_row.add_suffix(self.date_button)
        repeat.add(self.date_row)
        self.body.append(repeat)

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
            delete = Gtk.Button(label="Delete reminder", halign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.add_css_class("pill")
            delete.connect("clicked", self._delete)
            danger.add(delete)
            self.body.append(danger)
        self._sync_mode()

    def _sync_mode(self, *_args) -> None:
        once = self.mode_row.get_selected() == 1
        self.days_row.set_visible(not once)
        self.date_row.set_visible(once)

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_alarm(self.alarm.id)
            self.ctx.changed("alarms")
            self.close()

        confirm(self, f"Delete “{self.alarm.title}”?", "This reminder will be removed from this computer.", "Delete", go)

    def save(self) -> bool:
        once = self.mode_row.get_selected() == 1
        mask = 0 if once else self.days.mask
        if not once and mask == 0:
            self.error("Choose at least one day, or switch to a single date.")
            return False
        alarm = self.alarm or Alarm(title="", time="07:00")
        alarm.title = self.title_row.get_text().strip() or "Reminder"
        alarm.time = self.time_entry.text
        alarm.days_mask = mask
        alarm.one_shot_date = self.date_button.date.isoformat() if once else None
        alarm.sound = self.sound.sound
        alarm.enabled = self.enabled_row.get_active() if self.alarm else True
        if once and datetime.combine(self.date_button.date, parse_clock(alarm.time)) < datetime.now() - timedelta(minutes=5):
            self.error("That moment has already passed.")
            return False
        self.ctx.db.save_alarm(alarm)
        self.ctx.changed("alarms")
        return True
