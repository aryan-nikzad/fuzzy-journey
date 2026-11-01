# Fuzzy Journey

**A local-first daily planner and alarm app for Linux.**

Fuzzy Journey builds a wake / work / rest rhythm around Islamic prayer times. The original Python scheduling engine remains available, while the desktop app adds a polished GTK 4 + libadwaita interface and a persistent Linux alarm service.

The important design decision: **alarms do not rely on the GUI being open or the internet being available.** Reminders are stored in a local SQLite database and delivered by a user-level systemd service.

## What it does

- A native-feeling GTK 4 / libadwaita desktop interface.
- A focused home dashboard with an in-place 50% / 75% / Day Off selector, productive work time remaining, adjusted work finish times, wake-up and bedtime, sleep duration, today's alarms with sound settings, prayer times and day-off balance. Configuration lives on the secondary pages.
- Multiple reminders at different times, with selectable Classic, Gentle, Urgent or Digital tones, or a personal MP3 / audio file.
- Custom audio files are copied into the app's local data folder so moving the original file will not break an alarm.
- Recurring reminders on selected weekdays, or a one-time reminder on a chosen date.
- Critical desktop notifications and an audible alarm tone.
- Reminders continue after the application window is closed.
- Local SQLite storage; no account, cloud service, push provider, or network request is involved in alarm delivery.
- A bundled Shahrekord 2026 schedule, so the first launch can show prayer times while offline.
- Independent prayer alarms with a selectable tone or personal audio file for each prayer.
- Manual full-year prayer-data downloads (for example, 2027) for later offline use.
- A reminders history, alarm service status, and a settings page.
- A matching application ID and desktop entry so the app icon groups correctly in the GNOME dock/taskbar.
- A one- or two-minute test alarm so you can lock the screen and verify delivery.

## Linux installation

The supported desktop target is Ubuntu / GNOME with systemd, GTK 4 and libadwaita.

Install the desktop bindings and notification helper once:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libnotify-bin
```

For built-in tones, use a working PipeWire or PulseAudio session; Fuzzy Journey checks for `paplay`, `pw-play`, or `aplay`. For personal MP3 / AAC / M4A / FLAC audio, install an MP3-capable player such as `mpv` (`sudo apt install mpv`), `ffmpeg` (`ffplay`), `mpg123`, or VLC. The selected file is imported into `~/.local/share/fuzzy-journey/custom-sounds/`.

From the repository directory:

```bash
chmod +x install.sh
./install.sh
```

The installer copies the application to `~/.local/share/fuzzy-journey/app`, creates an application-menu entry, and enables `fuzzy-journey.service` as a user service. It does not need internet access after the required desktop packages are present.

Launch **Fuzzy Journey** from the applications menu, or run:

```bash
~/.local/bin/fuzzy-journey
```

To remove the application while keeping your saved alarms and data:

```bash
./uninstall.sh
```

## How alarms work

1. Create a reminder and choose its time.
2. Select the weekdays on which it should repeat, or enter a one-time date in `YYYY-MM-DD` format.
3. Choose whether it should play a sound and select Classic, Gentle, Urgent or Digital.
4. Save it. The reminder and selected tone are persisted in SQLite.
5. The systemd user service checks the local database every five seconds and issues a desktop notification plus the selected alarm sound when the reminder is due.

Prayer alarms also have independent enable switches, built-in tone selectors and custom audio file pickers. The Alarms and Daily Schedule editors have the same custom audio picker; the Settings test alarm can use a personal file too. Routine blocks can alarm at their start, their end, or both. Wake-up, sleep, work and other activities use the same system. In Settings, schedule a one- or two-minute test alarm, then lock the screen (do not suspend the computer) to check that desktop audio is delivered.

You can close the GUI after creating reminders. The service continues in the background and is configured to start at user login.

The scheduler allows a **five-minute catch-up window**. For example, if the service starts again shortly after an alarm time, it can still deliver that alarm once. A recurring reminder is recorded as fired for that local date, so it cannot ring repeatedly during the same minute or service restart. One-time reminders are automatically disabled after delivery.

Useful service commands:

```bash
systemctl --user status fuzzy-journey.service
systemctl --user restart fuzzy-journey.service
journalctl --user -u fuzzy-journey.service -f
```

## Offline and power-state behaviour

Alarm delivery is completely local. It does not contact AlAdhan, GitHub, a push-notification provider, or any remote server.

There are unavoidable operating-system limits:

- The computer must be powered on. A normal desktop app cannot make sound while the computer is shut down.
- The user session must be logged in for desktop notifications and audio to be available.
- A suspended computer cannot play an alarm at the scheduled instant unless the hardware / OS wakes it. On resume, the service can catch up if the alarm is no more than five minutes late.
- If a reminder is more than five minutes late when the service returns, it is treated as missed rather than playing an outdated alarm hours later.

For dependable use, keep the user session logged in and disable automatic suspend during periods when alarms must be heard. The background service is independent of the app window, not of the computer's power state.

## Data and privacy

Everything lives on the device:

- Database: `~/.local/share/fuzzy-journey/fuzzy-journey.sqlite3`
- Generated alarm tone: `~/.local/share/fuzzy-journey/alarm.wav`
- Downloaded prayer schedules and backups: `~/.local/share/fuzzy-journey/`

No telemetry or cloud sync is implemented. The alarm daemon only reads the local database and calls the desktop notification / audio tools.

## Prayer-time data

The included Shahrekord 2026 schedule is read directly from the bundled CSV, so it works on first launch without a fetch. The prayer page has previous / next year navigation. The current year opens on upcoming dates and has a full-year toggle; other downloaded years show the complete year. When a selected year is missing, the page offers a direct download action for that year. Prayer alarms are resolved from the local date row, so they follow changing prayer times rather than using a fixed clock time.

Prayer-data downloads are optional and require a working connection. In Settings → Advanced · prayer data manager, enter a year such as `2027` and download its complete calendar. The app reuses `prayer_aio.py` and its Shahrekord / AlAdhan calculation settings. Existing raw and schedule CSVs are backed up before a forced refresh. Downloaded files stay in the app's local data folder and are used automatically when that year becomes current.

Default location: Shahrekord, Iran (`32.3261, 50.8572`), AlAdhan method 7.

## Original command-line planner

The original CLI remains available:

```bash
python3 prayer_aio.py --today
python3 prayer_aio.py --tomorrow
python3 prayer_aio.py --50 --tomorrow
python3 prayer_aio.py --75
python3 prayer_aio.py --date 15-03-2026
python3 prayer_aio.py --flex-time 00:30
python3 prayer_aio.py --reset-flex
```

The optional refresh action and CLI downloader require the `requests` Python package. On Ubuntu, install it with `sudo apt install python3-requests`. Reading and displaying existing CSV schedules and delivering alarms do not need it or make a network request.

## Tests

Run the alarm scheduling tests with the standard library:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

The tests cover weekday recurrence, one-time dates, the five-minute catch-up rule, one-time delivery persistence, routine alarm deduplication, and time-bank accounting.

## Day types and time bank

- **50% day:** neutral; it does not change the balance.
- **75% day:** earns **+0.5 day**.
- **Day off:** spends **1 day**.
- An unclassified date defaults to **50%** and can be changed later, including after the day has passed.
- Set a tracking start date to establish a zero-balance baseline; entries before that date are ignored.
- The balance is allowed to become negative. For example, taking a day off first creates -1; two 75% days bring it back to zero.
- Day types are stored by date in SQLite. Only dates from the tracking start date through today are counted. Unclassified eligible dates default to 50%; dates before the baseline and future dates have no status and are excluded. You can change an eligible past date later.

## Dynamic routines

Create recurring blocks for work, sleep, wake-up, calls, gym, reading or any other activity. Each block has a title, category, start/end time, weekday selection, enabled state, selected tone and independent start/end alarm switches. The home dashboard shows the current or next work block, its productive time remaining, pauses, and adjusted finish time. When an enabled non-work activity overlaps a work block, the work clock pauses and the finish time moves later by the activity's duration. For example, an 08:00–16:00 work block with a 10:00–14:00 activity finishes at 20:00, preserving eight hours of actual work. The dashboard also shows day start, bedtime, planned sleep, activity blocks and all configured alarm times with their sound settings. A selected Day Off suppresses work-block alarms. Equal start and end times are treated as an empty block and are not displayed.

## Project layout

| Path | Purpose |
| --- | --- |
| `fuzzy_journey/gui.py` | GTK desktop application |
| `fuzzy_journey/alarm_daemon.py` | Background alarm service |
| `fuzzy_journey/alarm_engine.py` | Due-time and recurrence logic |
| `fuzzy_journey/database.py` | SQLite persistence |
| `fuzzy_journey/notifications.py` | Desktop notification and local sound |
| `prayer_aio.py` | Original all-in-one prayer/work/sleep planner |
| `install.sh` / `uninstall.sh` | Linux user installation |
| `tests/` | Offline unit tests |

## License

MIT. See [LICENSE](LICENSE).
