from __future__ import annotations

from datetime import datetime, timedelta

from ... import alarms as rules
from ...models import PRAYER_NAMES, Alarm, PrayerAlarm, Sound
from ...timeutil import mask_label
from .. import service_control
from ..context import Context
from ..dialogs.alarm_dialog import AlarmDialog
from ..gi_setup import Adw, Gtk
from ..widgets import SoundEditor, label
from .base import Page


class AlarmsPage(Page):
    listens_to = frozenset({"alarms", "data", "location"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._quiet = False

        # -- service
        service = Adw.PreferencesGroup(title="Delivery")
        self.service_row = Adw.ActionRow(title="Alarm service", subtitle="Checking…")
        self.service_button = Gtk.Button(label="Restart", valign=Gtk.Align.CENTER)
        self.service_button.connect("clicked", self._restart)
        self.service_row.add_suffix(self.service_button)
        service.add(self.service_row)
        test = Adw.ActionRow(title="Test an alarm", subtitle="Rings in one minute. Lock the screen to check delivery.")
        test_button = Gtk.Button(label="Test", valign=Gtk.Align.CENTER)
        test_button.connect("clicked", self._test)
        test.add_suffix(test_button)
        service.add(test)

        # -- reminders
        self.reminders = Adw.PreferencesGroup(title="Reminders")
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Add a reminder")
        add.add_css_class("flat")
        add.connect("clicked", lambda _b: self.edit(None))
        self.reminders.set_header_suffix(add)
        self.column.append(self.reminders)
        self._reminder_rows: list[Gtk.Widget] = []

        # -- prayers
        prayers = Adw.PreferencesGroup(
            title="Prayer alarms", description="Follow the timetable, so they move with the seasons."
        )
        self.prayer_rows: dict[str, Adw.ExpanderRow] = {}
        self.prayer_controls: dict[str, tuple[Adw.SpinRow, SoundEditor]] = {}
        settings = ctx.db.prayer_alarms()
        for name in PRAYER_NAMES:
            current = settings.get(name, PrayerAlarm(name))
            expander = Adw.ExpanderRow(title=name, show_enable_switch=True)
            expander.set_enable_expansion(current.enabled)
            offset = Adw.SpinRow.new_with_range(-60, 60, 1)
            offset.set_title("Minutes from the prayer time")
            offset.set_subtitle("Negative rings earlier")
            offset.set_value(current.offset_minutes)
            editor = SoundEditor(current.sound, on_change=lambda _s, n=name: self._save_prayer(None, None, n))
            expander.add_row(offset)
            for row in editor.rows:
                expander.add_row(row)
            expander.connect("notify::enable-expansion", self._save_prayer, name)
            offset.connect("notify::value", self._save_prayer, name)
            prayers.add(expander)
            self.prayer_rows[name] = expander
            self.prayer_controls[name] = (offset, editor)
        self.column.append(prayers)

        # -- history
        self.history = Adw.PreferencesGroup(title="Recently rang")
        self.column.append(self.history)
        self._history_rows: list[Gtk.Widget] = []
        self.column.append(service)

        self.refresh()

    # -- actions -----------------------------------------------------------

    def edit(self, alarm: Alarm | None) -> None:
        AlarmDialog(self.get_root(), self.ctx, alarm).present()

    def _save_prayer(self, _obj, _pspec, name: str) -> None:
        if self._quiet:
            return
        offset, editor = self.prayer_controls[name]
        self.ctx.db.save_prayer_alarm(
            PrayerAlarm(name, self.prayer_rows[name].get_enable_expansion(), int(offset.get_value()), editor.sound)
        )
        self.ctx.changed("alarms")

    def _toggle(self, switch: Gtk.Switch, _pspec, alarm_id: int) -> None:
        if not self._quiet:
            self.ctx.db.set_alarm_enabled(alarm_id, switch.get_active())
            self.ctx.changed("alarms")

    def _test(self, _button) -> None:
        due = datetime.now() + timedelta(minutes=1)
        self.ctx.db.save_alarm(
            Alarm("Test alarm", due.strftime("%H:%M:%S"), 0, due.date().isoformat(), Sound(True, "classic"))
        )
        self.ctx.toast(f"Test alarm set for {due:%H:%M}")
        self.ctx.changed("alarms")

    def _restart(self, _button) -> None:
        service_control.start(lambda ok: (self.ctx.toast("Alarm service restarted" if ok else "Could not restart the service"),
                                          self._refresh_service()))

    def _refresh_service(self) -> None:
        def done(active) -> None:
            if active is None:
                self.service_row.set_subtitle("systemd isn’t available on this system")
                self.service_button.set_visible(False)
            elif active:
                self.service_row.set_subtitle("Running. Alarms ring even when this window is closed.")
                self.service_button.set_label("Restart")
                self.service_button.set_visible(True)
            else:
                self.service_row.set_subtitle("Not running. Alarms won’t ring.")
                self.service_button.set_label("Start")
                self.service_button.set_visible(True)

        service_control.is_active(done)

    # -- rendering ---------------------------------------------------------

    def refresh(self) -> None:
        self._quiet = True
        self._refresh_service()
        self._render_reminders()
        self._render_prayer_subtitles()
        self._render_history()
        self._quiet = False

    def _render_reminders(self) -> None:
        for row in self._reminder_rows:
            self.reminders.remove(row)
        self._reminder_rows.clear()
        items = self.ctx.db.list_alarms()
        now = datetime.now()
        if not items:
            row = Adw.ActionRow(title="No reminders", subtitle="Add one for anything the timetable doesn’t cover.", activatable=False)
            row.add_css_class("dim-label")
            self.reminders.add(row)
            self._reminder_rows.append(row)
            return
        for a in items:
            when = f"Once · {a.one_shot_date}" if a.one_shot_date else mask_label(a.days_mask)
            nxt = rules.next_occurrence(a, now)
            row = Adw.ActionRow(title=a.title, subtitle=f"{when} · {a.sound.describe()}", activatable=True)
            row.add_prefix(label(a.time[:5], "fj-time", "heading"))
            switch = Gtk.Switch(active=a.enabled, valign=Gtk.Align.CENTER)
            switch.connect("notify::active", self._toggle, a.id)
            row.add_suffix(switch)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda _r, item=a: self.edit(item))
            if not a.enabled or nxt is None:
                row.add_css_class("fj-past")
            self.reminders.add(row)
            self._reminder_rows.append(row)

    def _render_prayer_subtitles(self) -> None:
        day = self.ctx.library.day(self.ctx.location.slug, datetime.now().date())
        for name, expander in self.prayer_rows.items():
            at = day.get(name) if day else None
            expander.set_subtitle(f"{at:%H:%M} today" if at else "No timetable for today")

    def _render_history(self) -> None:
        for row in self._history_rows:
            self.history.remove(row)
        self._history_rows.clear()
        events = self.ctx.db.recent_events(6)
        self.history.set_visible(bool(events))
        for event in events:
            try:
                stamp = datetime.fromisoformat(event.fired_at).strftime("%a %-d %b, %H:%M")
            except ValueError:
                stamp = event.fired_at
            row = Adw.ActionRow(title=event.title, subtitle=stamp, activatable=False)
            row.add_css_class("fj-quiet")
            self.history.add(row)
            self._history_rows.append(row)
