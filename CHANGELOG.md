# Changelog

## Unreleased

### Fixed
- **One pause model.** The Pause button used to move only the pomodoro blocks while the work clock ignored it, so Today could say *39 min left, finishes 16:39* while the focus block had 47 minutes left and ended in the middle of the gym. A manual pause is now a pause like any other: the work clock and the pomodoro schedule are laid out from the same pauses and always agree. A pause that overlaps an activity merges with it and is named for the activity.
- **Nothing runs past bedtime.** However long the pauses, work and planning stop at bedtime. The focus that no longer fits is cut (planning keeps its place at the end) and Today says how much was cut.
- The Tasks meter says *over by 2h 15m* when tasks exceed the day's focus time, not only that they pass the recommended 90%.
- The Focus card shows *Paused* with a frozen timer whenever the day is paused (the gym as well as the Pause button), and what it is waiting for.

### Closing the day
- When the day's work is over (planning begins) and tasks are still open, the app asks once what happened to each: Done, Tomorrow or Cancel. *Ask me in 30 min* or Escape asks again later; *Close the day* with open tasks needs a second click and leaves them for tomorrow's review. Never after bedtime.
- The same window shows tomorrow's load and says you can add new tasks for tomorrow, not only moved ones. The next-day review says so too.

### Evening work
- **Add evening work…** (30 minutes to four hours) is available on any working day, not recommended, with bedtime and sleep given up shown first. Also offered from the closing window. Planning moves to the end of the evening. Schema 6 adds `day_entries.evening_minutes`.

### Settings for judgement calls
- Preferences → Focus → *Closing the day*: the automatic check-in, a reminder to plan tomorrow when nothing is open, the confirmation before leaving tasks open, never running work past bedtime, offering evening work, and the *Ask me later* delay. Defaults follow the philosophy (all on except the reminder; 30 minutes).

### Work done
- The Bank page lists the focus the clock really ran each day (no pauses, breaks or planning) as hours, percent of a Steady day's focus, focus blocks with decimals, or any mix, chosen in Preferences → Focus. Recorded every minute by the app or the alarm service; schema 6 adds the `day_progress` table.

### Recovered day
- **I overslept…** on a Steady day starts the day at the time you really woke. Work is 50% of the time you are awake (start to Isha) and may run into the afternoon, so the plan is rescued instead of lost. It counts as Steady for the bank, never shortens the night, and pomodoro, planning and task room follow the new window. *Change* and *Undo* are on Today; recovered days are outlined in the Bank calendar.
- Stored as a Steady entry with a start time (schema 3 adds one column), so older versions simply see a Steady day.

### Prayers as tasks
- The five prayers appear on every day as zero-length tasks in one folded **Prayers** row. They never use focus time and cannot be edited or deleted. A prayer can be moved to tomorrow once; the copy can only be done or cancelled. Schema 5 adds a `kind` column to `tasks`.

### Night work
- **Work into the night…** adds one to four hours of work after Isha on any working day. It is not recommended, so it first suggests moving tasks to tomorrow and only then offers the hours, showing the bedtime and sleep given up. Neutral for the bank. Pomodoro, alarms, planning and task room extend with it. Schema 4 adds one column.

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
- Database schema 6 adds the `tasks`, `pomodoro_pauses` and `day_progress` tables, a day start time, night work, evening work and a task kind. Existing data is untouched.

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
