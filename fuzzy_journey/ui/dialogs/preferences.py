from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ... import backup
from ...goals import ANCHOR_LABELS, ANCHOR_MODES
from ...meta import APP_NAME
from ...models import CALCULATION_METHODS, PROGRESS_UNITS, Location
from ...paths import APP_DATA_DIR, ensure_data_dir
from ...pomodoro import EVERY_RANGE, FOCUS_RANGE, LONG_RANGE, SHORT_RANGE
from ...selftest import HOURS_RANGE
from ...selftest import MODES as SELFTEST_MODES
from ...tasks import ORDER_MODES
from ..context import Context
from ..gi_setup import Adw, Gio, GLib, Gtk
from ..widgets import SoundEditor, confirm

THEMES = ("system", "light", "dark")


def apply_theme(name: str) -> None:
    scheme = {"light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}.get(
        name, Adw.ColorScheme.DEFAULT
    )
    Adw.StyleManager.get_default().set_color_scheme(scheme)


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, ctx: Context) -> None:
        super().__init__(transient_for=parent, modal=True, title="Preferences", default_width=560, default_height=680)
        self.ctx = ctx
        self.set_search_enabled(False)
        # Five pages, one question each: how it looks and where you are (General), how work runs (Focus),
        # what Mind and Track show (Mind & Track), the optional pack (Flexibility), your files (Data).
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        self._mind_page = Adw.PreferencesPage(title="Mind & Track", icon_name="avatar-default-symbolic")
        self._system_page = Adw.PreferencesPage(title="Data", icon_name="drive-harddisk-symbolic")
        self.add(page)
        self._focus_page()
        self.add(self._mind_page)
        self._flex_page()
        self.add(self._system_page)

        # -- appearance
        look = Adw.PreferencesGroup(title="Appearance")
        self.theme_row = Adw.ComboRow(title="Colour scheme")
        self.theme_row.set_model(Gtk.StringList.new(["Follow the system", "Light", "Dark"]))
        self.theme_row.set_selected(THEMES.index(ctx.settings.theme))
        self.theme_row.connect("notify::selected", self._on_theme)
        look.add(self.theme_row)
        page.add(look)

        # -- location
        loc = ctx.location
        place = Adw.PreferencesGroup(
            title="Location",
            description="Your day starts at Fajr and ends at Isha, so these decide its shape.",
        )
        self.name_row = Adw.EntryRow(title="Place name")
        self.name_row.set_text(loc.name)
        self.lat_row = Adw.SpinRow.new_with_range(-90, 90, 0.0001)
        self.lat_row.set_title("Latitude")
        self.lat_row.set_digits(4)
        self.lat_row.set_value(loc.latitude)
        self.lon_row = Adw.SpinRow.new_with_range(-180, 180, 0.0001)
        self.lon_row.set_title("Longitude")
        self.lon_row.set_digits(4)
        self.lon_row.set_value(loc.longitude)
        self.method_ids = list(CALCULATION_METHODS)
        if loc.method not in self.method_ids:
            self.method_ids.append(loc.method)
        self.method_row = Adw.ComboRow(title="Calculation method")
        self.method_row.set_model(Gtk.StringList.new(
            [CALCULATION_METHODS.get(m, f"Method {m}") for m in self.method_ids]
        ))
        self.method_row.set_selected(self.method_ids.index(loc.method))
        for row in (self.name_row, self.lat_row, self.lon_row, self.method_row):
            place.add(row)
        apply = Adw.ActionRow(title="Apply location", subtitle="Timetables are stored per place, so nothing is lost.")
        button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.connect("clicked", self._apply_location)
        apply.add_suffix(button)
        place.add(apply)
        page.add(place)

        # -- prayer data
        data = Adw.PreferencesGroup(
            title="Prayer data", description="Downloaded once, used offline. This is the only thing that ever needs the internet."
        )
        year = datetime.now().year
        self.download_buttons = []
        for y in (year, year + 1):
            row = Adw.ActionRow(title=f"{y} timetable")
            self.download_buttons.append((row, y))
            button = Gtk.Button(valign=Gtk.Align.CENTER)
            button.connect("clicked", self._download, y)
            row.add_suffix(button)
            data.add(row)
            row._button = button
        page.add(data)
        self._refresh_data()

        # -- storage
        store = Adw.PreferencesGroup(title="Your data")
        folder = Adw.ActionRow(title="Data folder", subtitle=str(APP_DATA_DIR), subtitle_selectable=True)
        open_button = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
        open_button.connect("clicked", self._open_folder)
        folder.add_suffix(open_button)
        store.add(folder)
        store.add(Adw.ActionRow(
            title="Private by design",
            subtitle=f"{APP_NAME} has no account, no cloud and no telemetry. Alarms never use the network.",
            activatable=False,
        ))
        self._system_page.add(store)

    # -- flexibility pack ---------------------------------------------------

    def _flex_page(self) -> None:
        """One switch turns the whole pack on; with it off the app is exactly as before."""
        from ...flex import NOTHING_LABELS, NOTHING_PLACES, NOTHING_RANGE, NOTHING_RULES
        from ..widgets import TimeEntry

        page = Adw.PreferencesPage(title="Flexibility", icon_name="view-reveal-symbolic")
        self.add(page)
        f = self.ctx.settings.flexibility
        self._flex_quiet = True

        top = Adw.PreferencesGroup(
            title="Flexibility pack",
            description="Optional changes for days that do not run by the clock: a morning routine, starting and "
                        "ending work yourself, blocks you can lengthen or cut short, and a time to do nothing. "
                        "Off, the app works exactly as it always has.")
        self.flex_row = Adw.SwitchRow(title="Use the flexibility pack", subtitle="Switch on the options below.")
        self.flex_row.set_active(f.enabled)
        self.flex_row.connect("notify::active", self._on_flex)
        top.add(self.flex_row)
        page.add(top)

        def switch(title, subtitle, value):
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            row.set_active(value)
            row.connect("notify::active", self._on_flex)
            return row

        self.flex_groups = []
        routine = Adw.PreferencesGroup(title="Morning")
        self.flex_routine = switch("Morning routine",
                                   "A page for your morning steps. Work starts after them, not at Fajr.", f.routine)
        routine.add(self.flex_routine)
        page.add(routine)

        work = Adw.PreferencesGroup(title="Starting and ending work")
        self.flex_start = switch("Start work with a button",
                                 "Pomodoros begin when you press Start work, every day, and the time is saved.",
                                 f.manual_start)
        self.flex_blocks = switch("Flexible blocks and End work",
                                  "Every focus block and break has its own Start and Stop, and you press End work.",
                                  f.blocks)
        work.add(self.flex_start)
        work.add(self.flex_blocks)
        page.add(work)

        nothing = Adw.PreferencesGroup(title="Do nothing", description=NOTHING_RULES)
        self.flex_nothing = switch("A time to do nothing", "Protected, with an alarm at both ends.", f.nothing)
        self.flex_minutes = Adw.SpinRow.new_with_range(*NOTHING_RANGE, 5)
        self.flex_minutes.set_title("Minutes")
        self.flex_minutes.set_value(f.nothing_minutes)
        self.flex_minutes.connect("notify::value", self._on_flex)
        self.flex_where = Adw.ComboRow(title="When")
        self.flex_where.set_model(Gtk.StringList.new([NOTHING_LABELS[k] for k in NOTHING_PLACES]))
        self.flex_where.set_selected(NOTHING_PLACES.index(f.nothing_where))
        self.flex_where.connect("notify::selected", self._on_flex)
        self.flex_at = TimeEntry(f.nothing_at)
        self.flex_at.connect("changed", self._on_flex)
        self.flex_at_row = Adw.ActionRow(title="Fixed time", subtitle="Also used on days with no work.")
        self.flex_at_row.add_suffix(self.flex_at)
        self.flex_alarm = switch("Ring at the start and the end", "", f.nothing_alarm)
        for row in (self.flex_nothing, self.flex_minutes, self.flex_where, self.flex_at_row, self.flex_alarm):
            nothing.add(row)
        page.add(nothing)
        self.flex_groups = [routine, work, nothing]
        self._flex_quiet = False
        self._sync_flex_rows()

    def _sync_flex_rows(self) -> None:
        on = self.flex_row.get_active()
        for group in self.flex_groups:
            group.set_sensitive(on)
        self.flex_at_row.set_sensitive(self.flex_nothing.get_active())
        self.flex_minutes.set_sensitive(self.flex_nothing.get_active())
        self.flex_where.set_sensitive(self.flex_nothing.get_active())
        self.flex_alarm.set_sensitive(self.flex_nothing.get_active())

    def _on_flex(self, *_args) -> None:
        if self._flex_quiet:
            return
        from dataclasses import replace

        from ...flex import NOTHING_PLACES

        settings = self.ctx.settings
        self._sync_flex_rows()
        settings.flexibility = replace(
            settings.flexibility,
            enabled=self.flex_row.get_active(), routine=self.flex_routine.get_active(),
            manual_start=self.flex_start.get_active(), blocks=self.flex_blocks.get_active(),
            nothing=self.flex_nothing.get_active(), nothing_minutes=int(self.flex_minutes.get_value()),
            nothing_where=NOTHING_PLACES[self.flex_where.get_selected()], nothing_at=self.flex_at.time,
            nothing_alarm=self.flex_alarm.get_active(),
        )
        self.ctx.changed("flex")

    # -- focus -------------------------------------------------------------

    def _focus_page(self) -> None:
        page = Adw.PreferencesPage(title="Focus", icon_name="alarm-symbolic")
        self.add(page)
        ctx = self.ctx
        p = ctx.settings.pomodoro

        def spin(title, rng, value, step=1):
            row = Adw.SpinRow.new_with_range(rng[0], rng[1], step)
            row.set_title(title)
            row.set_snap_to_ticks(True)
            row.set_value(value)
            row.connect("notify::value", self._on_focus_changed)
            return row

        def switch(title, subtitle, value):
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            row.set_active(value)
            row.connect("notify::active", self._on_focus_changed)
            return row

        pomo = Adw.PreferencesGroup(
            title="Pomodoro",
            description="Work is cut into focus blocks and breaks, with an alarm at each change.",
        )
        self.pomo_on = switch("Use pomodoro", "Turn it off to work in one stretch.", p.enabled)
        self.focus_row = spin("Focus block (minutes)", FOCUS_RANGE, p.focus, 5)
        self.short_on = switch("Short breaks", "A pause between focus blocks.", p.short_enabled)
        self.short_row = spin("Short break (minutes)", SHORT_RANGE, p.short)
        self.long_on = switch("Long breaks", "A longer pause after several focus blocks.", p.long_enabled)
        self.long_row = spin("Long break (minutes)", LONG_RANGE, p.long, 5)
        self.every_row = spin("Long break after (focus blocks)", EVERY_RANGE, p.long_every)
        self._pomo_rows = [
            (self.focus_row, lambda q: q.pomo_on.get_active()),
            (self.short_on, lambda q: q.pomo_on.get_active()),
            (self.short_row, lambda q: q.pomo_on.get_active() and q.short_on.get_active()),
            (self.long_on, lambda q: q.pomo_on.get_active()),
            (self.long_row, lambda q: q.pomo_on.get_active() and q.long_on.get_active()),
            (self.every_row, lambda q: q.pomo_on.get_active() and q.long_on.get_active()),
        ]
        for row in (self.pomo_on, *(r for r, _ in self._pomo_rows)):
            pomo.add(row)
        page.add(pomo)

        ring = Adw.PreferencesGroup(title="Pomodoro alarm", description="Rings when a block or a break begins.")
        self.pomo_sound = SoundEditor(ctx.settings.pomodoro_sound, self._on_pomo_sound)
        for row in self.pomo_sound.rows:
            ring.add(row)
        page.add(ring)

        plan = Adw.PreferencesGroup(title="Planning and tasks")
        self.planning_on = switch(
            "End the day with planning",
            "The last 30 minutes of work are kept for settling today’s tasks and planning tomorrow.",
            p.planning_enabled,
        )
        plan.add(self.planning_on)
        self.order_row = Adw.ComboRow(title="Order tasks", subtitle="How you decide what comes first.")
        self.order_row.set_model(Gtk.StringList.new(["In my own order", "By importance"]))
        self.order_row.set_selected(ORDER_MODES.index(ctx.settings.task_order))
        self.order_row.connect("notify::selected", self._on_order)
        plan.add(self.order_row)
        page.add(plan)

        # -- Mind & Track
        anchor = Adw.PreferencesGroup(
            title="Your goal and who you are",
            description="One great goal and one self-image statement a day, on Today. They are only your own "
                        "words: they never change the plan.",
        )
        self.anchor_row = Adw.ComboRow(
            title="On Today",
            subtitle="Your plan should live in your head, not on a screen, so by default Today asks you to say "
                     "them first.",
        )
        self.anchor_row.set_model(Gtk.StringList.new([ANCHOR_LABELS[m] for m in ANCHOR_MODES]))
        self.anchor_row.set_selected(ANCHOR_MODES.index(ctx.settings.anchor_mode))
        self.anchor_row.connect("notify::selected", self._on_anchor)
        anchor.add(self.anchor_row)
        self._mind_page.add(anchor)

        test = Adw.PreferencesGroup(
            title="Test myself",
            description="Add a regular task that asks you to say your rules, your plan and your day from memory. "
                        "It is only a record for you: never focus time, never carried over, never nagged about.",
        )
        self.selftest_row = Adw.ComboRow(title="Add a self-test task")
        self.selftest_row.set_model(Gtk.StringList.new(["Never", "At each prayer time", "Every few hours"]))
        self.selftest_row.set_selected(SELFTEST_MODES.index(ctx.settings.selftest_mode))
        self.selftest_row.connect("notify::selected", self._on_selftest)
        test.add(self.selftest_row)
        self.selftest_hours = Adw.SpinRow.new_with_range(*HOURS_RANGE, 1)
        self.selftest_hours.set_title("Hours between tests")
        self.selftest_hours.set_subtitle("From when you wake until bedtime.")
        self.selftest_hours.set_value(ctx.settings.selftest_hours)
        self.selftest_hours.connect("notify::value", self._on_selftest)
        test.add(self.selftest_hours)
        self.selftest_hours.set_visible(ctx.settings.selftest_mode == "interval")
        self._mind_page.add(test)

        track = Adw.PreferencesGroup(
            title="Track",
            description="Pages you can turn off. Turning one off hides it and keeps your data.",
        )
        self.habit_row = Adw.SwitchRow(
            title="Show the habit calendar",
            subtitle="A private calendar for habits you want to build or quit.",
        )
        self.habit_row.set_active(ctx.settings.habit_calendar)
        self.habit_row.connect("notify::active", self._on_habit_calendar)
        track.add(self.habit_row)
        self.prayers_row = Adw.SwitchRow(
            title="Show the five prayers as tasks",
            subtitle="Turn off if you do not pray. The prayer times still set when your day starts and ends.",
        )
        self.prayers_row.set_active(ctx.settings.show_prayers)
        self.prayers_row.connect("notify::active", self._on_show_prayers)
        track.add(self.prayers_row)
        self._mind_page.add(track)

        safe = Adw.PreferencesGroup(
            title="Backup and restore",
            description="Everything you have set up in one file: settings, reminders, routine, tasks, days, "
                        "habits, ideas, rules, the recovery plan and your own sounds. The prayer-time CSV files are not "
                        "included; they work on their own wherever you place them.",
        )
        back_up = Adw.ActionRow(title="Back up everything…", subtitle="Save it to a file you keep safe.",
                                activatable=True)
        back_up.add_suffix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
        back_up.connect("activated", self._choose_backup_file)
        restore = Adw.ActionRow(
            title="Restore from a backup…",
            subtitle="Replaces everything the app stores now. A copy of what you have is kept first.",
            activatable=True,
        )
        restore.add_suffix(Gtk.Image.new_from_icon_name("document-open-symbolic"))
        restore.connect("activated", self._choose_restore_file)
        safe.add(back_up)
        safe.add(restore)
        self._system_page.add(safe)

        tray = Adw.PreferencesGroup(title="System tray")
        self.tray_row = Adw.SwitchRow(
            title="Show an icon in the system tray",
            subtitle="Click it to show or hide the window. Closing the window then keeps the app in the tray. "
                     "GNOME needs the AppIndicator extension. With no tray found, the window closes normally.",
        )
        self.tray_row.set_active(ctx.settings.tray_icon)
        self.tray_row.connect("notify::active", self._on_tray)
        tray.add(self.tray_row)
        self._system_page.add(tray)

        closing = Adw.PreferencesGroup(
            title="Closing the day",
            description="What the app does when the day's work is over. These are judgement calls, so each can be changed.",
        )
        st = ctx.settings
        switches = (
            ("closing_prompt", "Ask about today's tasks when work ends",
             "Done, tomorrow or cancel for each open task. Never after bedtime."),
            ("closing_reminder", "Also remind me to plan tomorrow",
             "Open the check-in even when no task is open."),
            ("closing_confirm", "Ask before leaving tasks open",
             "One more click before open tasks wait for tomorrow's review."),
            ("protect_bedtime", "Never run work past bedtime",
             "Pauses cannot push work into the night: the focus is cut and planning keeps its place."),
            ("evening_offer", "Offer evening work",
             "Show Add evening work… on Today and in the check-in. Not recommended."),
        )
        self._flag_rows: dict[str, Adw.SwitchRow] = {}
        for key, title, subtitle in switches:
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            row.set_active(getattr(st, key))
            row.connect("notify::active", lambda r, _p, k=key: self._on_flag(k, r.get_active()))
            self._flag_rows[key] = row
            closing.add(row)
        snooze = Adw.SpinRow.new_with_range(10, 120, 5)
        snooze.set_title("Ask again after (minutes)")
        snooze.set_subtitle("When you choose Ask me later, or press Escape.")
        snooze.set_value(st.closing_snooze)
        snooze.connect("notify::value", lambda r, _p: setattr(st, "closing_snooze", int(r.get_value())))
        closing.add(snooze)
        page.add(closing)

        done = Adw.PreferencesGroup(
            title="Work done",
            description="The Bank page lists the focus you really worked each day: the time the clock ran, "
            "without pauses or breaks. Show it as any of these.",
        )
        chosen = ctx.settings.progress_units
        self._unit_rows: dict[str, Adw.SwitchRow] = {}
        subtitles = {
            "hours": "For example 2h 40m.",
            "percent": "Compared with the focus time a Steady day offers.",
            "blocks": "Focus blocks with decimals, such as 3.4.",
        }
        for key, title in PROGRESS_UNITS.items():
            row = Adw.SwitchRow(title=title, subtitle=subtitles[key])
            row.set_active(key in chosen)
            row.connect("notify::active", self._on_units)
            self._unit_rows[key] = row
            done.add(row)
        page.add(done)
        self._sync_focus_rows()

    def _on_anchor(self, *_args) -> None:
        self.ctx.settings.anchor_mode = ANCHOR_MODES[self.anchor_row.get_selected()]
        self.ctx.changed("anchor")

    def _sync_focus_rows(self) -> None:
        for row, visible in self._pomo_rows:
            row.set_visible(visible(self))

    def _on_focus_changed(self, *_args) -> None:
        settings = self.ctx.settings
        settings.pomodoro = replace(
            settings.pomodoro,
            enabled=self.pomo_on.get_active(), focus=int(self.focus_row.get_value()),
            short_enabled=self.short_on.get_active(), short=int(self.short_row.get_value()),
            long_enabled=self.long_on.get_active(), long=int(self.long_row.get_value()),
            long_every=int(self.every_row.get_value()), planning_enabled=self.planning_on.get_active(),
        )
        self._sync_focus_rows()
        self.ctx.changed("rhythm")

    def _on_pomo_sound(self, sound) -> None:
        self.ctx.settings.pomodoro_sound = sound

    def _on_flag(self, key: str, value: bool) -> None:
        setattr(self.ctx.settings, key, value)
        self.ctx.changed("day")

    def _on_units(self, *_args) -> None:
        chosen = [key for key, row in self._unit_rows.items() if row.get_active()]
        if not chosen:  # something must be shown: fall back to hours
            self._unit_rows["hours"].set_active(True)
            return
        self.ctx.settings.progress_units = chosen
        self.ctx.changed("progress")

    # -- backup and restore ----------------------------------------------------------

    def _zip_filters(self) -> Gio.ListStore:
        zips = Gtk.FileFilter(name="Fuzzy Journey backups (.zip)")
        zips.add_suffix("zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zips)
        return filters

    def _choose_backup_file(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Save a backup", initial_name=backup.default_filename())
        dialog.set_filters(self._zip_filters())

        def done(source, result) -> None:
            try:
                picked = source.save_finish(result)
            except GLib.Error:
                return  # cancelled
            self.make_backup(Path(picked.get_path()))

        dialog.save(self, None, done)

    def _choose_restore_file(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Choose a backup to restore")
        dialog.set_filters(self._zip_filters())

        def done(source, result) -> None:
            try:
                picked = source.open_finish(result)
            except GLib.Error:
                return
            self.ask_restore(Path(picked.get_path()))

        dialog.open(self, None, done)

    def _tell(self, heading: str, body: str) -> None:
        message = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
        message.add_response("ok", "OK")
        message.present()

    def make_backup(self, path: Path) -> bool:
        if path.suffix.lower() != ".zip":
            path = path.with_name(path.name + ".zip")
        try:
            info = backup.create_backup(self.ctx.db, path)
        except backup.BackupError as error:
            self._tell("The backup was not saved", str(error))
            return False
        extra = f" and {info.sounds} sound{'s' if info.sounds != 1 else ''}" if info.sounds else ""
        self.ctx.toast(f"Backed up everything{extra} to {path.name}")
        return True

    def ask_restore(self, path: Path) -> None:
        """Check the file, say what it is, and only then ask. Nothing changes until the person agrees."""
        try:
            info = backup.read_backup_info(path)
        except backup.BackupError as error:
            self._tell("This cannot be restored", str(error))
            return
        confirm(
            self, "Replace everything with this backup?",
            f"Made on {info.created_text} by version {info.app_version}. Everything the app stores now "
            "(settings, reminders, routine, tasks, days, habits, ideas and rules) is replaced by what is in the backup. "
            "A copy of the current data is kept first. The prayer-time CSV files are not touched.",
            "Restore", lambda: self.restore_backup(path),
        )

    def restore_backup(self, path: Path) -> bool:
        try:
            result = backup.restore_backup(self.ctx.db, path)
        except backup.BackupError as error:
            self._tell("The backup was not restored", str(error))
            return False
        apply_theme(self.ctx.settings.theme)
        parent = self.get_transient_for()
        app = parent.get_application() if parent else None
        if app and hasattr(app, "apply_tray"):
            app.apply_tray()
        self.ctx.changed("all")
        self.ctx.toast(f"Restored the backup from {result.info.created_text}")
        self.close()  # this window still shows the old values
        return True

    def _on_tray(self, row, _pspec) -> None:
        self.ctx.settings.tray_icon = row.get_active()
        parent = self.get_transient_for()
        app = parent.get_application() if parent else None
        if app and hasattr(app, "apply_tray"):
            app.apply_tray()
        if row.get_active():
            self.ctx.toast("The icon appears if your desktop has a system tray.")

    def _on_habit_calendar(self, row, _pspec) -> None:
        self.ctx.settings.habit_calendar = row.get_active()
        self.ctx.changed("habits")

    def _on_selftest(self, *_args) -> None:
        settings = self.ctx.settings
        settings.selftest_mode = SELFTEST_MODES[self.selftest_row.get_selected()]
        settings.selftest_hours = int(self.selftest_hours.get_value())
        self.selftest_hours.set_visible(settings.selftest_mode == "interval")
        self.ctx.changed("tasks")

    def _on_show_prayers(self, row, _pspec) -> None:
        self.ctx.settings.show_prayers = row.get_active()
        self.ctx.changed("tasks")

    def _on_order(self, row, _pspec) -> None:
        self.ctx.settings.task_order = ORDER_MODES[row.get_selected()]
        self.ctx.changed("tasks")

    # -- handlers ----------------------------------------------------------

    def _on_theme(self, row, _pspec) -> None:
        name = THEMES[row.get_selected()]
        self.ctx.settings.theme = name
        apply_theme(name)

    def _apply_location(self, _button) -> None:
        name = self.name_row.get_text().strip()
        if not name:
            self.add_toast(Adw.Toast.new("Give the place a name."))
            return
        self.ctx.settings.location = Location(
            name, round(self.lat_row.get_value(), 4), round(self.lon_row.get_value(), 4),
            self.method_ids[self.method_row.get_selected()],
        )
        self.add_toast(Adw.Toast.new(f"Location set to {name}"))
        self._refresh_data()
        self.ctx.changed("location")

    def _refresh_data(self) -> None:
        slug = self.ctx.location.slug
        for row, year in self.download_buttons:
            have = self.ctx.library.table(slug, year) is not None
            row.set_subtitle("On this computer" if have else "Not downloaded")
            row._button.set_label("Refresh" if have else "Download")
            row._button.remove_css_class("suggested-action")
            if not have:
                row._button.add_css_class("suggested-action")

    def _download(self, button: Gtk.Button, year: int) -> None:
        button.set_sensitive(False)
        button.set_label("Downloading…")

        def done(ok: bool, message: str) -> None:
            button.set_sensitive(True)
            self._refresh_data()
            self.add_toast(Adw.Toast.new(message if ok else f"Download failed: {message}"))

        self.ctx.download_year(year, done)

    def _open_folder(self, _button) -> None:
        ensure_data_dir()
        Gtk.FileLauncher.new(Gio.File.new_for_path(str(APP_DATA_DIR))).launch(self, None, None)
