# Changelog

## Unreleased

### Focus
- **Pomodoro.** Each day's work is cut into focus blocks and breaks, with an alarm at every change. Defaults: 50 minute focus, 10 minute short break, 30 minute long break after three focus blocks. Block length, both break lengths and how often the long break comes are adjustable; short breaks, long breaks and pomodoro itself can each be switched off (pomodoro is on by default).
- **Pause and resume** the running block (a glass of water): everything after it moves later by the length of the pause, and nothing rings while paused.
- **Planning.** The last 30 minutes of the day's work are kept for settling today's tasks and planning tomorrow. On by default; can be switched off.
- **Tasks.** A title, a length (5 to 360 minutes in steps of 5) and a status: not set, done, cancelled, or moved to tomorrow, which puts a copy on the next day. Tasks belong to their day; only that status moves one on. Order them by hand or by importance (High, Normal, Low) in Preferences → Focus.
- A day's tasks can never add up to more than its focus time, and the meter turns amber past the recommended 90%.
- **Tomorrow** screen with a date picker to plan, or look back at, any day.
- Tasks from earlier days that still have no status are put in front of you first, as a banner and a dialog, before the new day begins.
- **Stop a ringing alarm** (azan, a custom sound, anything) from a Stop button in the app, from the notification's *Stop alarm* action, with `Ctrl+.`, or with `python3 -m fuzzy_journey.service --stop`.

### Changed
- Screens are now Today, Tomorrow, Routine, Bank, Alarms, Prayers (`Ctrl+1`…`Ctrl+6`). The tab switcher moves to a bottom bar when the window is too narrow for six tabs.
- Database schema 2 adds the `tasks` and `pomodoro_pauses` tables. Existing data is untouched.

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
