from __future__ import annotations

import csv
import hashlib
import re
import shutil
import subprocess
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from fuzzy_journey import database
from fuzzy_journey.alarm_engine import effective_routine_end, next_occurrence
from fuzzy_journey.notifications import SOUND_PRESETS, play_alarm_sound
from fuzzy_journey.paths import APP_DATA_DIR, APP_ROOT, ensure_data_dir, schedule_path

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
PRAYER_FIELDS = (
    ("Fajr", "Fajr"),
    ("Sunrise", "Sunrise"),
    ("Dhuhr", "Dhuhr"),
    ("Asr", "Asr"),
    ("Maghrib", "Maghrib"),
    ("Isha", "Isha"),
)
SOUND_KEYS = tuple(SOUND_PRESETS)
SOUND_LABELS = tuple(SOUND_PRESETS.values())


def sound_key_from_dropdown(dropdown: Gtk.DropDown) -> str:
    index = int(dropdown.get_selected())
    return SOUND_KEYS[index] if 0 <= index < len(SOUND_KEYS) else "classic"


def label(text: str, css: str | None = None, *, xalign: float = 0.0, wrap: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.set_xalign(xalign)
    widget.set_wrap(wrap)
    if css:
        widget.add_css_class(css)
    return widget


def make_card(*, hero: bool = False) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.add_css_class("card")
    if hero:
        box.add_css_class("hero-card")
    box.set_margin_top(5)
    box.set_margin_bottom(5)
    return box


def clear_list(widget: Gtk.ListBox) -> None:
    child = widget.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        widget.remove(child)
        child = following


def load_schedule(day: date | None = None) -> tuple[dict | None, list[dict], Path | None]:
    target = day or date.today()
    path = schedule_path(target.year)
    if path is None:
        return None, [], None
    rows: list[dict] = []
    today = None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                row_date = datetime.strptime(row["Date"], "%d-%m-%Y").date()
            except (KeyError, ValueError):
                continue
            rows.append(row)
            if row_date == target:
                today = row
    return today, rows, path


def format_repeat(alarm: dict) -> str:
    if alarm.get("one_shot_date"):
        return f"Once · {alarm['one_shot_date']}"
    mask = int(alarm.get("days_mask") or 0)
    chosen = [day for index, day in enumerate(WEEKDAYS) if mask & (1 << index)]
    if len(chosen) == 7:
        return "Every day"
    if chosen == ["Mon", "Tue", "Wed", "Thu", "Fri"]:
        return "Weekdays"
    if chosen == ["Sat", "Sun"]:
        return "Weekends"
    return " · ".join(chosen) if chosen else "No repeat days"


def countdown_text(delta: timedelta) -> str:
    seconds = max(0, int(delta.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def duration_text(value: str) -> str:
    try:
        hours, minutes = (int(part) for part in value.split(":"))
        return f"{hours}h {minutes:02d}m" if minutes else f"{hours}h"
    except (ValueError, AttributeError):
        return value or "—"


def copy_custom_audio(source_path: str) -> str:
    source = Path(source_path).expanduser()
    allowed = {".mp3", ".wav", ".wave", ".ogg", ".flac", ".m4a", ".aac"}
    if source.suffix.lower() not in allowed or not source.is_file():
        raise ValueError("Choose a valid MP3, WAV, OGG, FLAC, M4A or AAC audio file.")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-")[:48] or "alarm"
    destination_dir = APP_DATA_DIR / "custom-sounds"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{digest.hexdigest()[:12]}-{safe_name}{source.suffix.lower()}"
    if not destination.exists():
        shutil.copy2(source, destination)
    return str(destination)


def choose_audio_file(parent: Gtk.Window, callback) -> None:
    dialog = Gtk.FileChooserNative.new(
        "Choose an alarm sound", parent, Gtk.FileChooserAction.OPEN,
        "Choose audio", "Cancel",
    )
    audio_filter = Gtk.FileFilter()
    audio_filter.set_name("Audio files")
    for pattern in ("*.mp3", "*.MP3", "*.wav", "*.WAV", "*.ogg", "*.OGG",
                    "*.flac", "*.FLAC", "*.m4a", "*.M4A", "*.aac", "*.AAC"):
        audio_filter.add_pattern(pattern)
    dialog.add_filter(audio_filter)
    all_filter = Gtk.FileFilter()
    all_filter.set_name("All files")
    all_filter.add_pattern("*")
    dialog.add_filter(all_filter)

    def response(native_dialog, response_id):
        if response_id == Gtk.ResponseType.ACCEPT:
            selected = native_dialog.get_file()
            try:
                source = selected.get_path() if selected else None
                if not source:
                    raise ValueError("The selected file has no local path.")
                callback(copy_custom_audio(source), None)
            except (OSError, ValueError) as exc:
                callback(None, str(exc))
        native_dialog.destroy()

    dialog.connect("response", response)
    dialog.show()


class AlarmForm(Gtk.Window):
    def __init__(self, parent: "MainWindow", alarm: dict | None = None):
        super().__init__(transient_for=parent, modal=True)
        self.parent = parent
        self.alarm = alarm
        self.set_title("Edit reminder" if alarm else "New reminder")
        self.set_default_size(460, 590)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_margin_top(22)
        root.set_margin_bottom(22)
        root.set_margin_start(24)
        root.set_margin_end(24)
        self.set_child(root)

        root.append(label("Set a time that matters", "form-title"))
        root.append(label("It will ring locally, even while this window is closed.", "muted", wrap=True))

        root.append(label("Reminder name", "field-title"))
        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text("e.g. Start morning work")
        self.title_entry.set_text(alarm["title"] if alarm else "")
        root.append(self.title_entry)

        root.append(label("Time", "field-title"))
        self.time_entry = Gtk.Entry()
        self.time_entry.set_placeholder_text("HH:MM · 24-hour clock")
        self.time_entry.set_max_length(5)
        self.time_entry.set_text(alarm["alarm_time"] if alarm else "07:00")
        root.append(self.time_entry)

        root.append(label("Repeat on", "field-title"))
        days_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        self.day_checks: list[Gtk.CheckButton] = []
        old_mask = int(alarm["days_mask"]) if alarm else 127
        for index, day in enumerate(WEEKDAYS):
            check = Gtk.CheckButton(label=day)
            check.set_active(bool(old_mask & (1 << index)))
            days_row.append(check)
            self.day_checks.append(check)
        root.append(days_row)

        root.append(label("Or schedule it once", "field-title"))
        self.date_entry = Gtk.Entry()
        self.date_entry.set_placeholder_text("YYYY-MM-DD · leave blank to repeat")
        self.date_entry.set_text(alarm.get("one_shot_date") or "" if alarm else "")
        root.append(self.date_entry)
        root.append(label("A date takes priority over the repeat days.", "field-hint", wrap=True))

        self.sound_check = Gtk.CheckButton(label="Play an alarm sound")
        self.sound_check.set_active(bool(alarm["sound_enabled"]) if alarm else True)
        root.append(self.sound_check)

        root.append(label("Alarm sound", "field-title"))
        self.sound_dropdown = Gtk.DropDown.new_from_strings(list(SOUND_LABELS))
        selected_sound = alarm.get("sound_key", "classic") if alarm else "classic"
        self.sound_dropdown.set_selected(SOUND_KEYS.index(selected_sound) if selected_sound in SOUND_KEYS else 0)
        root.append(self.sound_dropdown)

        self.custom_sound_path = alarm.get("custom_sound_path") if alarm else None
        custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        choose_custom = Gtk.Button(label="Choose MP3 / audio file")
        choose_custom.add_css_class("flat")
        choose_custom.connect("clicked", lambda _b: choose_audio_file(self, self._custom_sound_selected))
        custom_row.append(choose_custom)
        clear_custom = Gtk.Button(label="Use built-in tone")
        clear_custom.add_css_class("flat")
        clear_custom.connect("clicked", self._clear_custom_sound)
        custom_row.append(clear_custom)
        root.append(custom_row)
        self.custom_sound_status = label(
            Path(self.custom_sound_path).name if self.custom_sound_path else "Using the selected built-in tone.",
            "field-hint", wrap=True,
        )
        root.append(self.custom_sound_status)

        self.enabled_check = Gtk.CheckButton(label="Keep this reminder enabled")
        self.enabled_check.set_active(bool(alarm["enabled"]) if alarm else True)
        root.append(self.enabled_check)

        self.status = label("", "error-text", wrap=True)
        root.append(self.status)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.set_halign(Gtk.Align.END)
        test_button = Gtk.Button(label="Test sound")
        test_button.add_css_class("flat")
        test_button.connect("clicked", self._test_sound)
        actions.append(test_button)

        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("flat")
        cancel.connect("clicked", lambda _button: self.close())
        actions.append(cancel)

        save = Gtk.Button(label="Save reminder")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        actions.append(save)
        root.append(actions)

    def _custom_sound_selected(self, path: str | None, error: str | None) -> None:
        if error:
            self.custom_sound_status.set_text(error)
            return
        self.custom_sound_path = path
        self.custom_sound_status.set_text(f"Custom sound: {Path(path).name}" if path else "Using the selected built-in tone.")

    def _clear_custom_sound(self, _button: Gtk.Button) -> None:
        self.custom_sound_path = None
        self.custom_sound_status.set_text("Using the selected built-in tone.")

    def _test_sound(self, _button: Gtk.Button) -> None:
        selected_sound = sound_key_from_dropdown(self.sound_dropdown)
        threading.Thread(target=play_alarm_sound, args=(selected_sound, self.custom_sound_path), daemon=True).start()

    def _save(self, _button: Gtk.Button) -> None:
        title = self.title_entry.get_text().strip() or "Reminder"
        clock = self.time_entry.get_text().strip()
        try:
            datetime.strptime(clock, "%H:%M")
        except ValueError:
            self.status.set_text("Enter a valid time in 24-hour HH:MM format.")
            return

        one_shot = self.date_entry.get_text().strip()
        if one_shot:
            try:
                date.fromisoformat(one_shot)
            except ValueError:
                self.status.set_text("Use YYYY-MM-DD for a one-time reminder date.")
                return
            days_mask = 0
        else:
            days_mask = sum(1 << index for index, check in enumerate(self.day_checks) if check.get_active())
            if days_mask == 0:
                self.status.set_text("Choose at least one repeat day, or enter a one-time date.")
                return

        try:
            database.save_alarm(
                title=title,
                alarm_time=clock,
                days_mask=days_mask,
                one_shot_date=one_shot or None,
                sound_enabled=self.sound_check.get_active(),
                sound_key=sound_key_from_dropdown(self.sound_dropdown),
                custom_sound_path=self.custom_sound_path,
                enabled=self.enabled_check.get_active(),
                alarm_id=self.alarm["id"] if self.alarm else None,
            )
        except Exception as exc:
            self.status.set_text(f"Could not save the reminder: {exc}")
            return

        self.parent.refresh_all()
        self.close()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app)
        headerbar = Adw.HeaderBar()
        headerbar.set_show_start_title_buttons(False)
        headerbar.set_show_end_title_buttons(True)
        self.set_title("Fuzzy Journey")
        self.set_default_size(1160, 780)
        self.set_size_request(760, 560)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        self._install_css()
        database.initialize()
        ensure_data_dir()

        shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(headerbar)
        toolbar_view.set_content(shell)
        self.set_content(toolbar_view)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(228, -1)
        sidebar.set_margin_top(20)
        sidebar.set_margin_bottom(18)
        sidebar.set_margin_start(15)
        sidebar.set_margin_end(12)
        shell.append(sidebar)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        icon = Gtk.Image.new_from_icon_name("appointment-soon-symbolic")
        icon.set_pixel_size(28)
        icon.add_css_class("brand-icon")
        brand.append(icon)
        brand_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        brand_text.append(label("Fuzzy Journey", "brand-title"))
        brand_text.append(label("A calmer daily rhythm", "brand-subtitle"))
        brand.append(brand_text)
        sidebar.append(brand)

        sidebar.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.nav_buttons: dict[str, Gtk.Button] = {}
        nav_items = (
            ("overview", "Overview", "view-grid-symbolic"),
            ("alarms", "Alarms", "alarm-symbolic"),
            ("calendar", "Calendar & time bank", "x-office-calendar-symbolic"),
            ("schedule", "Daily schedule", "view-list-symbolic"),
            ("prayers", "Prayer times", "appointment-soon-symbolic"),
            ("settings", "Settings", "preferences-system-symbolic"),
        )
        for key, title, icon_name in nav_items:
            button = Gtk.Button()
            button.add_css_class("nav-button")
            button.set_has_frame(False)
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            image = Gtk.Image.new_from_icon_name(icon_name)
            image.set_pixel_size(18)
            inner.append(image)
            inner.append(label(title))
            button.set_child(inner)
            button.connect("clicked", self._navigate, key)
            sidebar.append(button)
            self.nav_buttons[key] = button

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar.append(spacer)
        offline = make_card()
        offline.set_margin_start(0)
        offline.set_margin_end(0)
        offline.append(label("LOCAL BY DESIGN", "eyebrow"))
        offline.append(label("Your reminders and saved schedules stay on this computer. No account or connection required.", "muted", wrap=True))
        sidebar.append(offline)
        sidebar.append(label("FUZZY JOURNEY  ·  1.0", "version-label"))

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main.set_hexpand(True)
        shell.append(main)

        self.page_title = label("Overview", "page-title")
        self.page_subtitle = label(datetime.now().strftime("%A, %d %B %Y"), "muted")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_top(25)
        header.set_margin_bottom(17)
        header.set_margin_start(24)
        header.set_margin_end(27)
        title_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        title_stack.append(self.page_title)
        title_stack.append(self.page_subtitle)
        header.append(title_stack)
        header_spacer = Gtk.Box()
        header_spacer.set_hexpand(True)
        header.append(header_spacer)
        self.clock_label = label(datetime.now().strftime("%H:%M"), "clock-label")
        header.append(self.clock_label)
        main.append(header)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(160)
        self.stack.set_vexpand(True)
        main.append(self.stack)

        self.stack.add_named(self._build_overview(), "overview")
        self.stack.add_named(self._build_alarms(), "alarms")
        self.stack.add_named(self._build_calendar(), "calendar")
        self.stack.add_named(self._build_schedule(), "schedule")
        self.stack.add_named(self._build_prayers(), "prayers")
        self.stack.add_named(self._build_settings(), "settings")
        self._navigate(None, "overview")
        self.refresh_all()
        GLib.timeout_add_seconds(20, self._tick_clock)

    def _install_css(self) -> None:
        css = b"""
        window { background: #0b1120; color: #e5edf8; }
        .sidebar { background: #101a2b; border: 1px solid #1d2a3e; border-radius: 20px; }
        .brand-title { font-size: 17px; font-weight: 750; color: #f1f5f9; }
        .brand-subtitle, .muted, .brand-subtitle { color: #91a2b8; font-size: 12px; }
        .brand-icon { color: #8bd5f5; }
        .nav-button { min-height: 44px; padding: 0 13px; border-radius: 11px; color: #a9b8ca; }
        .nav-button:hover { background: #1b2a40; color: #f1f5f9; }
        .nav-button.selected { background: #243b56; color: #d9f1ff; font-weight: 650; }
        .page-title { font-size: 27px; font-weight: 760; color: #f8fafc; }
        .clock-label { font-size: 22px; font-weight: 700; color: #a9ddf4; font-feature-settings: "tnum"; }
        .main-content { padding: 4px 25px 28px 25px; }
        .card { background: #131f31; border: 1px solid #25364d; border-radius: 17px; padding: 18px; }
        .hero-card { background: linear-gradient(135deg, #172c43, #1b2940); border-color: #36516c; }
        .eyebrow { color: #8fc8e8; font-size: 11px; font-weight: 750; letter-spacing: 1.2px; }
        .hero-time { color: #f8fafc; font-size: 35px; font-weight: 800; font-feature-settings: "tnum"; }
        .hero-title { color: #f8fafc; font-size: 18px; font-weight: 700; }
        .section-title { font-size: 17px; font-weight: 720; color: #f1f5f9; }
        .section-description { color: #91a2b8; font-size: 12px; }
        .metric { font-size: 24px; font-weight: 750; color: #eff6ff; font-feature-settings: "tnum"; }
        .metric-label { color: #91a2b8; font-size: 11px; }
        .prayer-time { font-size: 19px; font-weight: 700; color: #eaf2fb; font-feature-settings: "tnum"; }
        .prayer-name { font-size: 11px; color: #91a2b8; }
        .form-title { font-size: 22px; font-weight: 750; color: #f8fafc; }
        .field-title { font-size: 12px; font-weight: 700; color: #c4d1e0; }
        .field-hint { color: #8396ad; font-size: 11px; }
        .error-text { color: #ff9b9b; font-size: 12px; }
        .time-label { font-size: 25px; font-weight: 800; color: #eff6ff; font-feature-settings: "tnum"; }
        .alarm-title { font-size: 14px; font-weight: 700; color: #eaf2fb; }
        .alarm-meta { font-size: 11px; color: #8fa2b9; }
        .list-row { background: #131f31; border: 1px solid #25364d; border-radius: 13px; padding: 13px 15px; }
        .version-label { color: #657991; font-size: 10px; letter-spacing: 0.8px; }
        .online-pill { background: #173b37; color: #83e0bd; border-radius: 20px; padding: 6px 10px; font-size: 10px; font-weight: 750; }
        .warning-pill { background: #46351d; color: #f5ca84; border-radius: 20px; padding: 6px 10px; font-size: 10px; font-weight: 750; }
        .small-button { padding: 5px 10px; }
        .dim-line { color: #8495a9; font-size: 12px; }
        .accent { color: #9edcf8; }
        entry { min-height: 38px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _navigate(self, _button: Gtk.Button | None, page: str) -> None:
        self.stack.set_visible_child_name(page)
        titles = {
            "overview": ("Overview", "Your day, at a glance"),
            "alarms": ("Alarms", "Independent reminders for anything that matters"),
            "calendar": ("Calendar & time bank", "Plan the whole year and track earned or borrowed days off"),
            "schedule": ("Daily schedule", "Build and change your recurring daily rhythm"),
            "prayers": ("Prayer times", "A local schedule, ready without internet"),
            "settings": ("Settings", "Local data and background alarm service"),
        }
        title, subtitle = titles[page]
        self.page_title.set_text(title)
        self.page_subtitle.set_text(subtitle)
        for key, button in self.nav_buttons.items():
            if key == page:
                button.add_css_class("selected")
            else:
                button.remove_css_class("selected")

    def _scroll_page(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(child)
        return scroller

    def _build_overview(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.add_css_class("main-content")

        self.next_alarm_card = make_card(hero=True)
        self.next_alarm_card.append(label("NEXT REMINDER", "eyebrow"))
        self.next_alarm_time = label("No reminders yet", "hero-time")
        self.next_alarm_card.append(self.next_alarm_time)
        self.next_alarm_title = label("Add a reminder to give your day a rhythm.", "muted", wrap=True)
        self.next_alarm_card.append(self.next_alarm_title)
        hero_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        add = Gtk.Button(label="Create reminder")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda _button: self._open_alarm_form())
        hero_actions.append(add)
        manage = Gtk.Button(label="Manage reminders")
        manage.add_css_class("flat")
        manage.connect("clicked", lambda _button: self._navigate(None, "alarms"))
        hero_actions.append(manage)
        self.next_alarm_card.append(hero_actions)
        page.append(self.next_alarm_card)

        prayer_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        prayer_header.append(label("Today's prayer times", "section-title"))
        prayer_header_spacer = Gtk.Box()
        prayer_header_spacer.set_hexpand(True)
        prayer_header.append(prayer_header_spacer)
        self.data_badge = label("OFFLINE DATA", "online-pill")
        prayer_header.append(self.data_badge)
        page.append(prayer_header)

        self.prayer_card = make_card()
        self.prayer_grid = Gtk.Grid()
        self.prayer_grid.set_column_spacing(18)
        self.prayer_grid.set_row_spacing(18)
        self.prayer_card.append(self.prayer_grid)
        page.append(self.prayer_card)

        plan_heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        plan_heading.append(label("Your work / rest plan", "section-title"))
        plan_heading.append(label("Calculated from Fajr and Isha, using your saved local schedule.", "section-description"))
        self.today_plan_badge = label("TODAY'S PLAN · 50%", "online-pill")
        plan_heading.append(self.today_plan_badge)
        page.append(plan_heading)

        plan_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.plan_50_card = make_card()
        self.plan_75_card = make_card()
        self.plan_50_card.set_hexpand(True)
        self.plan_75_card.set_hexpand(True)
        self.plan_50_card.append(label("50% PLAN", "eyebrow"))
        self.plan_75_card.append(label("75% PLAN", "eyebrow"))
        self.plan_50_value = label("—", "metric")
        self.plan_75_value = label("—", "metric")
        self.plan_50_card.append(self.plan_50_value)
        self.plan_75_card.append(self.plan_75_value)
        self.plan_50_detail = label("Waiting for schedule data", "muted", wrap=True)
        self.plan_75_detail = label("Waiting for schedule data", "muted", wrap=True)
        self.plan_50_card.append(self.plan_50_detail)
        self.plan_75_card.append(self.plan_75_detail)
        plan_row.append(self.plan_50_card)
        plan_row.append(self.plan_75_card)
        page.append(plan_row)

        self.overview_note = label("", "muted", wrap=True)
        page.append(self.overview_note)
        return self._scroll_page(page)

    def _build_alarms(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        page.add_css_class("main-content")

        intro = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        intro_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        intro_text.append(label("Your reminders", "section-title"))
        intro_text.append(label("Recurring routines and one-time alarms. Each reminder is saved locally.", "section-description"))
        intro_text.set_hexpand(True)
        intro.append(intro_text)
        add = Gtk.Button(label="＋  Add reminder")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda _button: self._open_alarm_form())
        intro.append(add)
        page.append(intro)

        self.alarm_status_card = make_card()
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_row.append(label("Background alarm service", "field-title"))
        status_spacer = Gtk.Box()
        status_spacer.set_hexpand(True)
        status_row.append(status_spacer)
        self.alarm_service_badge = label("Checking…", "warning-pill")
        status_row.append(self.alarm_service_badge)
        self.alarm_status_card.append(status_row)
        self.alarm_status_card.append(label("The service keeps checking your reminders after you close this window. It starts automatically at login.", "muted", wrap=True))
        page.append(self.alarm_status_card)

        self.alarms_list = Gtk.ListBox()
        self.alarms_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.alarms_list.set_activate_on_single_click(False)
        self.alarms_list.add_css_class("boxed-list")
        page.append(self.alarms_list)

        self.history_card = make_card()
        self.history_card.append(label("RECENT RINGS", "eyebrow"))
        self.history_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.history_card.append(self.history_list)
        page.append(self.history_card)
        return self._scroll_page(page)

    def _build_prayers(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("main-content")

        card = make_card()
        card.append(label("Prayer times on this device", "section-title"))
        card.append(label("Prayer data is stored locally after download. The selected year's CSV is used without an internet connection.", "muted", wrap=True))
        card.append(label("Enable each prayer independently and choose its sound.", "field-hint", wrap=True))
        self.prayer_alarm_checks = {}
        self.prayer_sound_dropdowns = {}
        prayer_settings = database.list_prayer_alarms()
        for key in ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            check = Gtk.CheckButton(label=key)
            check.set_hexpand(True)
            settings = prayer_settings.get(key, {})
            check.set_active(bool(settings.get("enabled", 0)))
            dropdown = Gtk.DropDown.new_from_strings(list(SOUND_LABELS))
            selected_sound = settings.get("sound_key", "classic")
            dropdown.set_selected(SOUND_KEYS.index(selected_sound) if selected_sound in SOUND_KEYS else 0)
            check.connect("toggled", lambda widget, prayer=key: self._update_prayer_alarm(
                prayer, enabled=widget.get_active()))
            dropdown.connect("notify::selected", lambda widget, _pspec, prayer=key: self._update_prayer_alarm(
                prayer, sound_key=sound_key_from_dropdown(widget)))
            row.append(check)
            row.append(label("Sound", "field-hint"))
            row.append(dropdown)
            custom_path = settings.get("custom_sound_path")
            custom_status = label(Path(custom_path).name if custom_path else "Built-in", "field-hint")
            choose_custom = Gtk.Button.new_from_icon_name("document-open-symbolic")
            choose_custom.add_css_class("flat")
            choose_custom.set_tooltip_text("Choose a custom MP3 / audio file")
            def custom_selected(path, error, prayer=key, status=custom_status):
                if error:
                    status.set_text(error)
                    return
                self._update_prayer_alarm(prayer, custom_sound_path=path, update_custom_sound=True)
                status.set_text(Path(path).name if path else "Built-in")
            choose_custom.connect("clicked", lambda _b, prayer=key, callback=custom_selected: choose_audio_file(self, callback))
            row.append(choose_custom)
            clear_custom = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
            clear_custom.add_css_class("flat")
            clear_custom.set_tooltip_text("Use built-in sound")
            clear_custom.connect("clicked", lambda _b, prayer=key, callback=custom_selected: callback(None, None))
            row.append(clear_custom)
            card.append(row)
            card.append(custom_status)
            self.prayer_alarm_checks[key] = check
            self.prayer_sound_dropdowns[key] = dropdown
        page.append(card)

        self.prayer_table = Gtk.ListBox()
        self.prayer_table.set_selection_mode(Gtk.SelectionMode.NONE)
        page.append(self.prayer_table)
        self.prayer_page_note = label("", "muted", wrap=True)
        page.append(self.prayer_page_note)
        return self._scroll_page(page)

    def _update_prayer_alarm(self, prayer_key: str, *, enabled: bool | None = None,
                             sound_key: str | None = None,
                             custom_sound_path: str | None = None,
                             update_custom_sound: bool = False) -> None:
        current = database.list_prayer_alarms().get(prayer_key, {})
        database.set_prayer_alarm(
            prayer_key,
            bool(current.get("enabled", 0)) if enabled is None else enabled,
            int(current.get("offset_minutes", 0)),
            bool(current.get("sound_enabled", 1)),
            sound_key or str(current.get("sound_key") or "classic"),
            custom_sound_path if update_custom_sound else current.get("custom_sound_path"),
        )

    def _build_calendar(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("main-content")
        balance = make_card(hero=True)
        balance.append(label("YOUR TIME BANK", "eyebrow"))
        self.balance_value = label("0 days", "hero-time")
        balance.append(self.balance_value)
        self.balance_detail = label("Two 75% days earn one day off. A day off can put the balance below zero.", "muted", wrap=True)
        balance.append(self.balance_detail)
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.balance_earned = label("Earned: 0", "metric")
        self.balance_used = label("Used: 0", "metric")
        self.balance_debt = label("Debt: 0", "metric")
        stats.append(self.balance_earned)
        stats.append(self.balance_used)
        stats.append(self.balance_debt)
        balance.append(stats)
        page.append(balance)

        tracking = make_card()
        tracking.append(label("Start tracking from", "section-title"))
        tracking.append(label("Choose the date you want the time bank to begin. Anything before this date is ignored, so your starting balance is zero.", "muted", wrap=True))
        self.time_bank_start_entry = Gtk.Entry()
        self.time_bank_start_entry.set_placeholder_text("YYYY-MM-DD")
        self.time_bank_start_entry.set_text(database.get_time_bank_start_date())
        tracking.append(self.time_bank_start_entry)
        tracking_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_start = Gtk.Button(label="Set start date")
        apply_start.add_css_class("suggested-action")
        apply_start.connect("clicked", self._apply_time_bank_start_date)
        tracking_actions.append(apply_start)
        reset_start = Gtk.Button(label="Reset to today")
        reset_start.add_css_class("flat")
        reset_start.connect("clicked", lambda _b: (self.time_bank_start_entry.set_text(date.today().isoformat()), self._apply_time_bank_start_date(None)))
        tracking_actions.append(reset_start)
        tracking.append(tracking_actions)
        self.time_bank_start_status = label("", "field-hint", wrap=True)
        tracking.append(self.time_bank_start_status)
        page.append(tracking)

        month_card = make_card()
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        prev = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        prev.connect("clicked", lambda _b: self._shift_calendar_month(-1))
        controls.append(prev)
        self.calendar_month_title = label("", "section-title")
        self.calendar_month_title.set_hexpand(True)
        self.calendar_month_title.set_xalign(0.5)
        controls.append(self.calendar_month_title)
        nxt = Gtk.Button.new_from_icon_name("go-next-symbolic")
        nxt.connect("clicked", lambda _b: self._shift_calendar_month(1))
        controls.append(nxt)
        month_card.append(controls)
        self.calendar_grid = Gtk.Grid()
        self.calendar_grid.set_column_homogeneous(True)
        self.calendar_grid.set_row_spacing(5)
        self.calendar_grid.set_column_spacing(5)
        month_card.append(self.calendar_grid)
        page.append(month_card)

        edit = make_card()
        edit.append(label("Selected day", "section-title"))
        self.selected_day_label = label(date.today().strftime("%A, %d %B %Y"), "muted")
        edit.append(self.selected_day_label)
        self.day_type_dropdown = Gtk.DropDown.new_from_strings(["Normal · 50%", "Intensive · 75%", "Day off"])
        edit.append(self.day_type_dropdown)
        self.day_notes = Gtk.Entry()
        self.day_notes.set_placeholder_text("Optional note for this day")
        edit.append(self.day_notes)
        self.day_scope_note = label("", "field-hint", wrap=True)
        edit.append(self.day_scope_note)
        self.save_day_button = Gtk.Button(label="Save day type")
        self.save_day_button.add_css_class("suggested-action")
        self.save_day_button.connect("clicked", self._save_selected_day)
        edit.append(self.save_day_button)
        page.append(edit)
        self.calendar_selected_date = date.today()
        self.calendar_month = date.today().replace(day=1)
        self._select_calendar_day(date.today())
        return self._scroll_page(page)

    def _shift_calendar_month(self, amount: int) -> None:
        year, month = self.calendar_month.year, self.calendar_month.month + amount
        if month < 1:
            year, month = year - 1, 12
        elif month > 12:
            year, month = year + 1, 1
        self.calendar_month = date(year, month, 1)
        self._render_calendar()

    def _select_calendar_day(self, day: date) -> None:
        self.calendar_selected_date = day
        self.selected_day_label.set_text(day.strftime("%A, %d %B %Y"))
        start_date = date.fromisoformat(database.get_time_bank_start_date())
        today = date.today()
        counts_for_bank = start_date <= day <= today
        entries = database.get_day_entries(day.isoformat(), day.isoformat())
        saved = entries[0] if entries else None
        self.day_type_dropdown.set_selected(
            {"50": 0, "75": 1, "off": 2}.get(saved["day_type"], 0) if saved and counts_for_bank else 0
        )
        self.day_notes.set_text(saved["notes"] if saved and counts_for_bank else "")
        self.day_type_dropdown.set_sensitive(counts_for_bank)
        self.day_notes.set_sensitive(counts_for_bank)
        self.save_day_button.set_sensitive(counts_for_bank)
        if day < start_date:
            self.day_scope_note.set_text(f"Before tracking started on {start_date}. This date has no status and is not counted.")
        elif day > today:
            self.day_scope_note.set_text("Future date. Its status stays blank and it is not counted yet.")
        else:
            status = "50% by default" if not saved else {"50": "50%", "75": "75%", "off": "Day off"}[saved["day_type"]]
            self.day_scope_note.set_text(f"Included in the time bank · {status}. You can edit past days if something unexpected happened.")
        self._render_calendar()

    def _apply_time_bank_start_date(self, _button: Gtk.Button | None) -> None:
        value = self.time_bank_start_entry.get_text().strip()
        try:
            date.fromisoformat(value)
        except ValueError:
            self.time_bank_start_status.set_text("Enter a valid start date in YYYY-MM-DD format.")
            return
        database.set_time_bank_start_date(value)
        self.time_bank_start_status.set_text(f"Time bank now starts on {value}. Earlier entries are ignored.")
        self.refresh_calendar()

    def _save_selected_day(self, _button: Gtk.Button) -> None:
        start_date = date.fromisoformat(database.get_time_bank_start_date())
        today = date.today()
        if not start_date <= self.calendar_selected_date <= today:
            return
        kind = {0: "50", 1: "75", 2: "off"}.get(self.day_type_dropdown.get_selected(), "50")
        database.set_day_type(self.calendar_selected_date.isoformat(), kind, self.day_notes.get_text().strip())
        self._select_calendar_day(self.calendar_selected_date)
        self.refresh_calendar()
        self.refresh_overview()

    def _render_calendar(self) -> None:
        if not hasattr(self, "calendar_grid"):
            return
        clear_grid = self.calendar_grid.get_first_child()
        while clear_grid:
            following = clear_grid.get_next_sibling()
            self.calendar_grid.remove(clear_grid)
            clear_grid = following
        self.calendar_month_title.set_text(self.calendar_month.strftime("%B %Y"))
        for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            self.calendar_grid.attach(label(name, "prayer-name", xalign=0.5), col, 0, 1, 1)
        import calendar as _calendar
        month = _calendar.Calendar(firstweekday=0)
        entries = {item["day_date"]: item for item in database.get_day_entries(
            self.calendar_month.isoformat(), date(self.calendar_month.year, self.calendar_month.month,
            _calendar.monthrange(self.calendar_month.year, self.calendar_month.month)[1]).isoformat())}
        for row, week in enumerate(month.monthdatescalendar(self.calendar_month.year, self.calendar_month.month), start=1):
            for col, day in enumerate(week):
                if day.month != self.calendar_month.month:
                    text_value = " "
                else:
                    entry = entries.get(day.isoformat())
                    start_date = date.fromisoformat(database.get_time_bank_start_date())
                    today = date.today()
                    if start_date <= day <= today:
                        effective_type = entry["day_type"] if entry else "50"
                        suffix = {"50": " · 50", "75": " · 75", "off": " · OFF"}[effective_type]
                    else:
                        suffix = ""
                    text_value = f"{day.day}{suffix}"
                button = Gtk.Button(label=text_value)
                button.set_sensitive(day.month == self.calendar_month.month)
                button.set_size_request(68, 42)
                if day.month == self.calendar_month.month and not entries.get(day.isoformat()):
                    button.set_tooltip_text("Default day: 50% (you can change this later).")
                eligible_day = date.fromisoformat(database.get_time_bank_start_date()) <= day <= date.today()
                if day == self.calendar_selected_date:
                    button.add_css_class("suggested-action")
                elif eligible_day and entries.get(day.isoformat(), {}).get("day_type") == "75":
                    button.add_css_class("success")
                elif eligible_day and entries.get(day.isoformat(), {}).get("day_type") == "off":
                    button.add_css_class("warning")
                button.connect("clicked", lambda _b, selected=day: self._select_calendar_day(selected))
                self.calendar_grid.attach(button, col, row, 1, 1)

    def refresh_calendar(self) -> None:
        if not hasattr(self, "balance_value"):
            return
        stats = database.day_balance()
        balance = stats["balance"]
        self.balance_value.set_text(f"{balance:+g} days" if balance else "0 days")
        self.balance_detail.set_text(f"Each 75% day earns half a day; each day off spends one. Tracking starts {stats['start_date']}. Negative balance is allowed.")
        self.balance_earned.set_text(f"Earned: {stats['earned']:g}")
        self.balance_used.set_text(f"Used: {stats['consumed']:g}")
        self.balance_debt.set_text(f"Debt: {max(0, -balance):g}")
        if hasattr(self, "time_bank_start_entry"):
            self.time_bank_start_entry.set_text(stats["start_date"])
        self._render_calendar()

    def _build_schedule(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("main-content")
        intro = make_card()
        intro.append(label("Your recurring time blocks", "section-title"))
        intro.append(label("Add work, sleep, wake-up, girlfriend calls, gym, reading, meals or any other activity. Each block has its own days and alarm setting.", "muted", wrap=True))
        add = Gtk.Button(label="＋  Add time block")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._open_routine_form)
        intro.append(add)
        page.append(intro)
        self.routine_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.append(self.routine_list)
        return self._scroll_page(page)

    def _open_routine_form(self, _button=None, block: dict | None = None) -> None:
        dialog = Gtk.Window(transient_for=self, modal=True, title="Edit time block" if block else "Add time block")
        dialog.set_default_size(440, 610)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(20); box.set_margin_bottom(20); box.set_margin_start(22); box.set_margin_end(22)
        box.append(label("Activity name", "field-title"))
        title = Gtk.Entry(); title.set_placeholder_text("e.g. Focused work"); title.set_text(block["title"] if block else ""); box.append(title)
        box.append(label("Category", "field-title"))
        categories = ["personal", "work", "sleep", "wake", "call", "prayer", "health"]
        category = Gtk.DropDown.new_from_strings(["Personal", "Work", "Sleep", "Wake-up", "Call", "Prayer", "Health"])
        category.set_selected(categories.index(block["category"]) if block and block["category"] in categories else 0)
        box.append(category)
        box.append(label("Start time · HH:MM", "field-title"))
        start = Gtk.Entry(); start.set_text(block["start_time"] if block else "16:00"); box.append(start)
        box.append(label("End time · HH:MM", "field-title"))
        end = Gtk.Entry(); end.set_text(block["end_time"] if block else "18:00"); box.append(end)
        box.append(label("Repeat on", "field-title"))
        checks = []
        day_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        old_mask = int(block["days_mask"]) if block else 127
        for index, day in enumerate(WEEKDAYS):
            check = Gtk.CheckButton(label=day); check.set_active(bool(old_mask & (1 << index))); checks.append(check); day_row.append(check)
        box.append(day_row)
        alarm = Gtk.CheckButton(label="Alarm when this block starts")
        alarm.set_active(bool(block["alarm_enabled"]) if block else False); box.append(alarm)
        end_alarm = Gtk.CheckButton(label="Alarm when this block ends")
        end_alarm.set_active(bool(block.get("end_alarm_enabled", 0)) if block else False); box.append(end_alarm)
        sound = Gtk.CheckButton(label="Play sound")
        sound.set_active(bool(block["sound_enabled"]) if block else True); box.append(sound)
        box.append(label("Alarm sound", "field-title"))
        sound_dropdown = Gtk.DropDown.new_from_strings(list(SOUND_LABELS))
        old_sound = block.get("sound_key", "classic") if block else "classic"
        sound_dropdown.set_selected(SOUND_KEYS.index(old_sound) if old_sound in SOUND_KEYS else 0)
        box.append(sound_dropdown)
        custom_sound_path = block.get("custom_sound_path") if block else None
        custom_sound_status = label(
            Path(custom_sound_path).name if custom_sound_path else "Using the built-in alarm tone.",
            "field-hint", wrap=True,
        )
        def custom_selected(path, error):
            nonlocal custom_sound_path
            if error:
                custom_sound_status.set_text(error)
                return
            custom_sound_path = path
            custom_sound_status.set_text(f"Custom sound: {Path(path).name}" if path else "Using the built-in alarm tone.")
        custom_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        choose_custom = Gtk.Button(label="Choose audio file")
        choose_custom.add_css_class("flat")
        choose_custom.connect("clicked", lambda _b: choose_audio_file(dialog, custom_selected))
        custom_actions.append(choose_custom)
        clear_custom = Gtk.Button(label="Use built-in")
        clear_custom.add_css_class("flat")
        clear_custom.connect("clicked", lambda _b: custom_selected(None, None))
        custom_actions.append(clear_custom)
        box.append(custom_actions)
        box.append(custom_sound_status)
        enabled = Gtk.CheckButton(label="Block enabled")
        enabled.set_active(bool(block["enabled"]) if block else True); box.append(enabled)
        status = label("", "error-text", wrap=True); box.append(status)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8); actions.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel"); cancel.connect("clicked", lambda _b: dialog.close()); actions.append(cancel)
        save = Gtk.Button(label="Save block"); save.add_css_class("suggested-action")
        def save_block(_b):
            mask = sum(1 << i for i, item in enumerate(checks) if item.get_active())
            if mask == 0:
                status.set_text("Choose at least one day for this block.")
                return
            try:
                database.save_routine_block(
                    title=title.get_text(),
                    category=categories[category.get_selected()],
                    start_time=start.get_text().strip(),
                    end_time=end.get_text().strip(),
                    days_mask=mask,
                    alarm_enabled=alarm.get_active(),
                    end_alarm_enabled=end_alarm.get_active(),
                    sound_enabled=sound.get_active(),
                    sound_key=sound_key_from_dropdown(sound_dropdown),
                    custom_sound_path=custom_sound_path,
                    enabled=enabled.get_active(),
                    block_id=block["id"] if block else None,
                )
            except ValueError:
                status.set_text("Enter valid 24-hour start and end times.")
                return
            dialog.close()
            self.refresh_all()
        save.connect("clicked", save_block); actions.append(save); box.append(actions)
        dialog.set_child(box); dialog.present()

    def refresh_schedule(self) -> None:
        if not hasattr(self, "routine_list"):
            return
        child = self.routine_list.get_first_child()
        while child:
            nxt = child.get_next_sibling(); self.routine_list.remove(child); child = nxt
        blocks = database.list_routine_blocks()
        if not blocks:
            self.routine_list.append(label("No custom time blocks yet.", "muted"))
        today = date.today()
        for block in blocks:
            row = make_card()
            heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            heading.append(label(block["start_time"], "time-label"))
            title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); title_box.set_hexpand(True)
            title_box.append(label(block["title"], "alarm-title"))
            display_end = block["end_time"]
            end_note = ""
            is_scheduled_today = bool(int(block.get("days_mask") or 0) & (1 << today.weekday()))
            if is_scheduled_today and block["category"] == "work" and block["enabled"]:
                adjusted_end = effective_routine_end(block, blocks, today)
                display_end = adjusted_end.strftime("%H:%M")
                if display_end != block["end_time"]:
                    end_note = " · extended around other activities"
            title_box.append(label(f"{block['category'].title()} · until {display_end}{end_note} · {format_repeat(block)}", "alarm-meta"))
            heading.append(title_box)
            edit = Gtk.Button.new_from_icon_name("document-edit-symbolic")
            edit.add_css_class("flat")
            edit.set_tooltip_text("Edit time block")
            edit.connect("clicked", lambda _b, item=block: self._open_routine_form(block=item))
            heading.append(edit)
            delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            delete.add_css_class("flat")
            delete.set_tooltip_text("Delete time block")
            delete.connect("clicked", lambda _b, bid=block["id"]: (database.delete_routine_block(bid), self.refresh_all()))
            heading.append(delete)
            switch = Gtk.Switch(); switch.set_active(bool(block["enabled"])); switch.set_valign(Gtk.Align.CENTER)
            switch.connect("notify::active", lambda sw, _p, bid=block["id"]: (database.set_routine_enabled(bid, sw.get_active()), self.refresh_all()))
            heading.append(switch)
            row.append(heading)
            flags = []
            if block.get("alarm_enabled"):
                flags.append("start alarm")
            if block.get("end_alarm_enabled"):
                flags.append("end alarm")
            row.append(label((" · ".join(flags) if flags else "No alarms") + f" · Sound: {SOUND_PRESETS.get(block.get('sound_key', 'classic'), 'Classic')}", "field-hint"))
            self.routine_list.append(row)

    def _build_settings(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        page.add_css_class("main-content")

        test_card = make_card()
        test_card.append(label("Test an alarm", "section-title"))
        test_card.append(label("Schedule a real one-time alarm in one or two minutes. Lock the screen to test delivery; do not suspend the computer.", "muted", wrap=True))
        test_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.test_delay_dropdown = Gtk.DropDown.new_from_strings(["1 minute", "2 minutes"])
        test_row.append(self.test_delay_dropdown)
        self.test_sound_dropdown = Gtk.DropDown.new_from_strings(list(SOUND_LABELS))
        test_row.append(self.test_sound_dropdown)
        test_card.append(test_row)
        test_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        test_button = Gtk.Button(label="Schedule test alarm")
        test_button.add_css_class("suggested-action")
        test_button.connect("clicked", self._schedule_test_alarm)
        test_actions.append(test_button)
        self.test_alarm_status = label("", "field-hint", wrap=True)
        test_actions.append(self.test_alarm_status)
        test_card.append(test_actions)
        page.append(test_card)

        local_card = make_card()
        local_card.append(label("Local-first operation", "section-title"))
        local_card.append(label("Your alarm list, preferences and delivery history are stored on this computer. No sign-in, cloud sync, push server or network connection is involved in ringing an alarm.", "muted", wrap=True))
        local_card.append(label(f"Data folder: {APP_DATA_DIR}", "field-hint", wrap=True))
        page.append(local_card)

        service_card = make_card()
        service_card.append(label("Alarm service", "section-title"))
        service_card.append(label("A systemd user service checks the local alarm database every five seconds. It runs independently of the desktop window.", "muted", wrap=True))
        service_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.settings_service_status = label("Checking service…", "muted")
        self.settings_service_status.set_hexpand(True)
        service_actions.append(self.settings_service_status)
        restart = Gtk.Button(label="Restart service")
        restart.add_css_class("flat")
        restart.connect("clicked", self._restart_service)
        service_actions.append(restart)
        service_card.append(service_actions)
        page.append(service_card)

        data_card = make_card()
        data_card.append(label("Advanced · prayer data manager", "section-title"))
        data_card.append(label("Download a full year of Shahrekord prayer times for offline use. Choose a future year such as 2027; existing files are backed up before a forced refresh.", "muted", wrap=True))
        self.download_year_entry = Gtk.Entry()
        self.download_year_entry.set_placeholder_text("Year, e.g. 2027")
        self.download_year_entry.set_max_length(4)
        self.download_year_entry.set_text(str(date.today().year))
        data_card.append(label("Year to download", "field-title"))
        data_card.append(self.download_year_entry)
        self.refresh_status = label("", "field-hint", wrap=True)
        data_card.append(self.refresh_status)
        refresh = Gtk.Button(label="Download / refresh selected year")
        refresh.add_css_class("suggested-action")
        refresh.connect("clicked", lambda button: self._refresh_prayer_data(button, self.download_year_entry))
        data_card.append(refresh)
        page.append(data_card)

        appearance = make_card()
        appearance.append(label("Appearance", "section-title"))
        dark_switch = Gtk.Switch()
        dark_switch.set_active(True)
        dark_switch.set_halign(Gtk.Align.START)
        dark_switch.connect("notify::active", self._change_theme)
        appearance.append(dark_switch)
        appearance.append(label("Use dark appearance", "muted"))
        page.append(appearance)

        note = label("Important: alarms can ring while the app is closed, but the computer must be powered on and the user session must be active. If the computer is off at the scheduled time, no desktop app can produce a sound then.", "field-hint", wrap=True)
        page.append(note)
        return self._scroll_page(page)

    def _change_theme(self, switch: Gtk.Switch, _pspec) -> None:
        scheme = Adw.ColorScheme.FORCE_DARK if switch.get_active() else Adw.ColorScheme.DEFAULT
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def _service_active(self) -> bool:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "fuzzy-journey.service"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            return result.stdout.strip() == "active"
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _restart_service(self, _button: Gtk.Button) -> None:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "restart", "fuzzy-journey.service"],
                capture_output=True, text=True, timeout=8, check=False,
            )
            if result.returncode != 0:
                self.settings_service_status.set_text("Could not restart. Run install.sh again to register the service.")
        except (OSError, subprocess.TimeoutExpired):
            self.settings_service_status.set_text("systemd user service is unavailable.")
        self.refresh_all()

    def _refresh_prayer_data(self, button: Gtk.Button, year_entry: Gtk.Entry | None = None) -> None:
        script = APP_ROOT / "prayer_aio.py"
        if not script.is_file():
            self.refresh_status.set_text("The original prayer-data updater is not present in this installation.")
            return
        try:
            year = int(year_entry.get_text().strip()) if year_entry else date.today().year
            if year < 1900 or year > 2200:
                raise ValueError
        except ValueError:
            self.refresh_status.set_text("Enter a valid year between 1900 and 2200.")
            return
        button.set_sensitive(False)
        self.refresh_status.set_text(f"Downloading the complete {year} calendar. This requires internet access…")

        def worker():
            ensure_data_dir()
            command = [
                sys.executable, str(script), "--override", "--no-show",
                "--city", "shahrekord", "--year", str(year),
                "--lat", "32.3261", "--lon", "50.8572", "--method", "7",
            ]
            try:
                result = subprocess.run(
                    command, cwd=APP_DATA_DIR, capture_output=True, text=True, timeout=1800, check=False
                )
                ok = result.returncode == 0
                message = f"{year} prayer data downloaded and saved for offline use." if ok else (
                    result.stderr.strip()[-500:] or result.stdout.strip()[-500:] or "Download failed. Check the connection and try again."
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                ok = False
                message = f"Download failed: {exc}"
            GLib.idle_add(self._finish_refresh, button, ok, message)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh(self, button: Gtk.Button, ok: bool, message: str) -> bool:
        button.set_sensitive(True)
        self.refresh_all()
        self.refresh_status.set_text(message)
        return GLib.SOURCE_REMOVE

    def _schedule_test_alarm(self, _button: Gtk.Button) -> None:
        delay = int(self.test_delay_dropdown.get_selected()) + 1
        due = datetime.now() + timedelta(minutes=delay)
        sound = sound_key_from_dropdown(self.test_sound_dropdown)
        database.save_alarm(
            title=f"Alarm test · {delay} minute",
            alarm_time=due.strftime("%H:%M:%S"),
            days_mask=0,
            one_shot_date=due.date().isoformat(),
            sound_enabled=True,
            sound_key=sound,
            enabled=True,
        )
        self.test_alarm_status.set_text(f"Test scheduled for {due.strftime('%H:%M:%S')} · {SOUND_PRESETS[sound]}. You can lock the screen now.")
        self.refresh_all()

    def _open_alarm_form(self, alarm: dict | None = None) -> None:
        AlarmForm(self, alarm).present()

    def _confirm_delete(self, alarm_id: int, title: str) -> None:
        dialog = Gtk.Window(transient_for=self, modal=True, title="Delete reminder")
        dialog.set_default_size(330, 150)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.append(label(f"Delete “{title}”?", "section-title"))
        box.append(label("This reminder will be removed from this device.", "muted", wrap=True))
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: dialog.close())
        actions.append(cancel)
        delete = Gtk.Button(label="Delete")
        delete.add_css_class("destructive-action")
        def confirm(_button):
            database.delete_alarm(alarm_id)
            dialog.close()
            self.refresh_all()
        delete.connect("clicked", confirm)
        actions.append(delete)
        box.append(actions)
        dialog.set_child(box)
        dialog.present()

    def _toggle_alarm(self, alarm_id: int, enabled: bool) -> None:
        database.set_alarm_enabled(alarm_id, enabled)
        self.refresh_overview()

    def _alarm_row(self, alarm: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("list-row")
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        outer.set_margin_top(5)
        outer.set_margin_bottom(5)
        outer.set_margin_start(5)
        outer.set_margin_end(5)

        time_text = label(alarm["alarm_time"][:5], "time-label")
        time_text.set_width_chars(5)
        outer.append(time_text)

        text_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text_stack.set_hexpand(True)
        text_stack.append(label(alarm["title"], "alarm-title"))
        text_stack.append(label(f"{format_repeat(alarm)} · {SOUND_PRESETS.get(alarm.get('sound_key', 'classic'), 'Classic')}", "alarm-meta"))
        outer.append(text_stack)

        if alarm.get("sound_enabled"):
            sound_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
            sound_icon.set_tooltip_text("Sound enabled")
            outer.append(sound_icon)

        toggle = Gtk.Switch()
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_active(bool(alarm["enabled"]))
        toggle.connect("notify::active", lambda switch, _pspec, alarm_id=alarm["id"]: self._toggle_alarm(alarm_id, switch.get_active()))
        outer.append(toggle)

        edit = Gtk.Button.new_from_icon_name("document-edit-symbolic")
        edit.add_css_class("flat")
        edit.set_tooltip_text("Edit reminder")
        edit.connect("clicked", lambda _button, item=alarm: self._open_alarm_form(item))
        outer.append(edit)

        delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        delete.add_css_class("flat")
        delete.set_tooltip_text("Delete reminder")
        delete.connect("clicked", lambda _button, item=alarm: self._confirm_delete(item["id"], item["title"]))
        outer.append(delete)

        row.set_child(outer)
        return row

    def refresh_alarms(self) -> None:
        alarms = database.list_alarms()
        clear_list(self.alarms_list)
        if not alarms:
            empty = Gtk.ListBoxRow()
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            empty_box.set_margin_top(22)
            empty_box.set_margin_bottom(22)
            empty_box.append(label("No reminders yet", "section-title", xalign=0.5))
            empty_box.append(label("Create one for Fajr, focused work, the gym, calls, or anything you do not want to miss.", "muted", xalign=0.5, wrap=True))
            empty.set_child(empty_box)
            self.alarms_list.append(empty)
        else:
            for alarm in alarms:
                self.alarms_list.append(self._alarm_row(alarm))

        clear_box = self.history_list.get_first_child()
        while clear_box is not None:
            following = clear_box.get_next_sibling()
            self.history_list.remove(clear_box)
            clear_box = following
        events = database.recent_events(6)
        if not events:
            self.history_list.append(label("Nothing has rung yet.", "muted"))
        else:
            for event in events:
                time_value = event["fired_at"].replace("T", " ")
                self.history_list.append(label(f"{time_value}   ·   {event['title']}", "muted"))
        service_running = self._service_active()
        self.alarm_service_badge.set_text("RUNNING" if service_running else "NOT RUNNING")
        self.alarm_service_badge.remove_css_class("warning-pill" if service_running else "online-pill")
        self.alarm_service_badge.add_css_class("online-pill" if service_running else "warning-pill")

    def refresh_overview(self) -> None:
        alarms = database.list_alarms()
        now = datetime.now()
        candidates = [(next_occurrence(alarm, now), alarm) for alarm in alarms if alarm.get("enabled")]
        candidates = [(when, alarm) for when, alarm in candidates if when is not None]
        if candidates:
            when, alarm = min(candidates, key=lambda item: item[0])
            self.next_alarm_time.set_text(when.strftime("%H:%M"))
            day_label = "Today" if when.date() == now.date() else when.strftime("%A, %d %b")
            self.next_alarm_title.set_text(f"{alarm['title']}  ·  {day_label}  ·  in {countdown_text(when - now)}")
        else:
            self.next_alarm_time.set_text("All clear")
            self.next_alarm_title.set_text("No enabled reminders. Add one to keep your routine on track.")

        today, _rows, path = load_schedule()
        day_entry = database.get_day_entries(now.date().isoformat(), now.date().isoformat())
        selected_plan = day_entry[0]["day_type"] if day_entry else "50"
        if hasattr(self, "today_plan_badge"):
            self.today_plan_badge.set_text("TODAY'S PLAN · " + ("75%" if selected_plan == "75" else "DAY OFF" if selected_plan == "off" else "50%"))
        clear_list(self.prayer_grid)
        if today:
            for index, (name, field) in enumerate(PRAYER_FIELDS):
                tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                tile.append(label(name.upper(), "prayer-name"))
                tile.append(label(today.get(field, "—"), "prayer-time"))
                self.prayer_grid.attach(tile, index % 3, index // 3, 1, 1)

            self.plan_50_value.set_text(duration_text(today.get("WorkTarget_50", "—")))
            self.plan_75_value.set_text(duration_text(today.get("WorkTarget_75", "—")))
            self.plan_50_detail.set_text(
                f"Morning  {today.get('MorningBlockStart_50')}–{today.get('MorningBlockEnd_50')}\n"
                f"Evening  {today.get('EveningBlockStart_50')}–{today.get('EveningBlockEnd_50')}\n"
                f"Sleep    {duration_text(today.get('SleepDuration_50', '—'))}"
            )
            self.plan_75_detail.set_text(
                f"Morning  {today.get('MorningBlockStart_75')}–{today.get('MorningBlockEnd_75')}\n"
                f"Evening  {today.get('EveningBlockStart_75')}–{today.get('EveningBlockEnd_75')}\n"
                f"Sleep    {duration_text(today.get('SleepDuration_75', '—'))}"
            )
            start_field = "MorningBlockStart_75" if selected_plan == "75" else "MorningBlockStart_50"
            start_value = today.get(start_field, "—")
            self.overview_note.set_text(f"Work starts at {start_value} · selected day: {selected_plan if selected_plan == 'off' else selected_plan + '%'} · {path.name}")
        else:
            self.prayer_grid.attach(label("No prayer schedule found for today. The app itself still works offline; add this year's CSV or refresh it when connected.", "muted", wrap=True), 0, 0, 3, 1)
            self.plan_50_value.set_text("—")
            self.plan_75_value.set_text("—")
            self.plan_50_detail.set_text("No local data for today.")
            self.plan_75_detail.set_text("No local data for today.")
            self.overview_note.set_text("Prayer data can be refreshed from Settings when a connection is available.")
        self.data_badge.set_text("LOCAL DATA" if path else "DATA NEEDED")

    def refresh_prayer_page(self) -> None:
        clear_list(self.prayer_table)
        today = date.today()
        _today, rows, _path = load_schedule(today)
        if not rows:
            self.prayer_page_note.set_text("No local data is available for this year. Your custom reminders continue to work normally.")
            return

        start_index = None
        for index, row in enumerate(rows):
            try:
                row_date = datetime.strptime(row["Date"], "%d-%m-%Y").date()
            except (KeyError, ValueError):
                continue
            if row_date >= today:
                start_index = index
                break
        if start_index is None:
            self.prayer_page_note.set_text("No upcoming dates are present in this local file. Refresh the prayer data when connected.")
            return
        for row_data in rows[start_index:]:
            try:
                row_date = datetime.strptime(row_data["Date"], "%d-%m-%Y").date()
            except (KeyError, ValueError):
                continue
            line = Gtk.ListBoxRow()
            line_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            line_box.set_margin_top(9)
            line_box.set_margin_bottom(9)
            line_box.set_margin_start(12)
            line_box.set_margin_end(12)
            date_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            date_box.set_size_request(130, -1)
            date_box.append(label(row_date.strftime("%a, %d %b"), "alarm-title"))
            date_box.append(label("Today" if row_date == today else row_date.strftime("%Y"), "alarm-meta"))
            line_box.append(date_box)
            line_box.set_hexpand(True)
            for name, field in PRAYER_FIELDS:
                cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                cell.set_hexpand(True)
                cell.append(label(name, "prayer-name"))
                cell.append(label(row_data.get(field, "—"), "alarm-title"))
                line_box.append(cell)
            line.set_child(line_box)
            self.prayer_table.append(line)
        self.prayer_page_note.set_text(f"Showing every remaining date in {today.year} from the local schedule ({len(rows) - start_index} days). Use the full-year calendar for day-type planning.")

    def refresh_settings(self) -> None:
        active = self._service_active()
        self.settings_service_status.set_text("Service is running in the background." if active else "Service is not active. Run install.sh to enable it.")
        self.refresh_status.set_text(f"Current data file: {schedule_path(date.today().year) or 'Not found for this year'}")

    def refresh_all(self) -> None:
        self.refresh_alarms()
        self.refresh_overview()
        self.refresh_calendar()
        self.refresh_schedule()
        self.refresh_prayer_page()
        self.refresh_settings()

    def _tick_clock(self) -> bool:
        now = datetime.now()
        self.clock_label.set_text(now.strftime("%H:%M"))
        if now.strftime("%H:%M") == "00:00":
            self.refresh_all()
        else:
            self.refresh_overview()
        return GLib.SOURCE_CONTINUE


class FuzzyJourneyApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="org.anyatech.FuzzyJourney",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.window: MainWindow | None = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


def main() -> int:
    app = FuzzyJourneyApp()
    # This is a desktop application, not a file handler or command-line tool.
    # Do not let GApplication interpret launcher arguments as files to open.
    # Passing None tells GApplication not to interpret process arguments as files.
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
