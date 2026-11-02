# Changelog

## 2.0.0

A ground-up refactor and redesign. Your data, alarms, and the `prayer_aio.py` command line carry over unchanged.

### Philosophy
- Stated plainly as four ideas (*The day is given. Work a share. Bank the rest. Protect the night.*) and two practices, in one place (`philosophy.py`), shown on first launch, in the Philosophy dialog, README and PHILOSOPHY.md.
- Day kinds renamed for clarity: **Steady 50%**, **Push 75%**, **Rest** (were "50% Standard", "75% Intensive", "Day off"). The numbers and the maths are unchanged.

### Interface
- New minimalist design built on native libadwaita: follows the system light/dark theme and accent colour; five screens in a header-bar switcher instead of a hand-made sidebar.
- **Today** leads with how much work is left, a *day bar* showing the shape of the day from wake to sleep, and one timeline of everything coming.
- Time and date pickers replace typing `HH:MM` and `YYYY-MM-DD`; edits happen in focused dialogs; changes to switches and day kinds save instantly.
- First-run welcome, a banner only when the alarm service is down, toasts instead of status text, keyboard shortcuts.

### New
- **Location setting** (name, coordinates, calculation method), so the app works anywhere, not only Shahrekord. Timetables are stored per place.
- Prayer alarms can ring a set number of minutes before or after the prayer.
- Evening start and extra focus time are set in the app; the plan updates immediately.
- Timetable downloads happen in the app, in the background, with a backup of what they replace.

### Fixed
- The interface no longer runs `systemctl` on the main thread every 20 seconds, and no longer re-reads the whole timetable each time.
- Work planned past midnight (long flex or evening blocks) is handled; previously bedtime and sleep were wrong.
- A single plan computation now serves the app, the alarm service and the CLI. Previously the same logic existed in several places.
- SQLite connections are closed, migrations run once and are versioned, and the delivery log is pruned.
- `requests` is no longer needed (the standard library is used), matching what the README always claimed.

### Under the hood
- The 2,300-line `gui.py` is split into pages, dialogs and widgets; the planning logic is pure and unit-tested (`rhythm.py`, `today.py`).
- 60+ tests, including a check that the generator reproduces the bundled timetable CSV exactly, a legacy-database migration test, and a headless GUI smoke test.
- Alarm service moved to `python3 -m fuzzy_journey.service`; re-run `./install.sh` to update it.
