# Fuzzy Journey

**A local-first daily planner and alarm app for Linux.**

Fuzzy Journey builds a wake / work / rest rhythm around Islamic prayer times. The original Python scheduling engine remains available, while the desktop app adds a polished GTK 4 + libadwaita interface and a persistent Linux alarm service.

The important design decision: **alarms do not rely on the GUI being open or the internet being available.** Reminders are stored in a local SQLite database and delivered by a user-level systemd service.

## What it does

- A native-feeling GTK 4 / libadwaita desktop interface.
- A daily overview with the next reminder, prayer times, and the 50% / 75% work and sleep plans.
- Multiple reminders at different times, with a custom title and sound toggle.
- Recurring reminders on selected weekdays, or a one-time reminder on a chosen date.
- Critical desktop notifications and an audible alarm tone.
- Reminders continue after the application window is closed.
- Local SQLite storage; no account, cloud service, push provider, or network request is involved in alarm delivery.
- A bundled Shahrekord 2026 schedule, so the first launch can show prayer times while offline.
- Optional prayer-data refresh from AlAdhan when an internet connection is available.
- A reminders history, alarm service status, and a small settings page.

## Linux installation

The supported desktop target is Ubuntu / GNOME with systemd, GTK 4 and libadwaita.

Install the desktop bindings and notification helper once:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libnotify-bin
```

For audio playback, use a working PipeWire or PulseAudio session. The service checks for `paplay`, `pw-play`, or `aplay` and uses the first available player.

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
3. Enable or disable its sound.
4. Save it. The reminder is persisted in SQLite.
5. The systemd user service checks the local database every five seconds and issues a desktop notification plus the alarm sound when an alarm is due.

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

The included Shahrekord 2026 schedule is read directly from the bundled CSV, so it works on first launch without a fetch. It covers the 2026 calendar year.

Prayer-data refresh is optional and requires a working connection. The app reuses the original `prayer_aio.py` updater and its AlAdhan calculation settings. Existing files are backed up by the original updater before replacement. If a later year is not bundled, add or refresh that year's CSV when connected; custom alarms do not depend on prayer-time data.

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

The tests cover weekday recurrence, one-time dates, the five-minute catch-up rule, and one-time delivery persistence.

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
