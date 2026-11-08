# AGENTS.md

Rules for anyone (human or AI) changing this repository. Read [PHILOSOPHY.md](PHILOSOPHY.md) first:
a change that does not serve one of its four ideas probably does not belong.

## Do not break

- **The philosophy is the spec.** The arithmetic lives only in `fuzzy_journey/rhythm.py` (the day), `pomodoro.py` (how work is cut into blocks and breaks) and `tasks.py` (task load and order). The app, the alarm service and the CLI must all use it; never re-implement a rule elsewhere. If you change a rule, change `philosophy.py`, `PHILOSOPHY.md`, `README.md` and the tests in the same commit (`tests/test_docs.py` fails when they drift). `PHILOSOPHY.md` also carries two deliberate exceptions to the four ideas, *Recovered day* and *Night work*; they are not in `philosophy.py`, so keep them consistent by hand.
- **The CLI contract.** `prayer_aio.py` keeps its flags and its output text. Compare old and new output before changing `fuzzy_journey/cli.py`.
- **The CSV contract.** `*_raw.csv` and `*_schedule.csv` keep their column names and order (`prayer_times.RAW_FIELDNAMES`, `SCHEDULE_FIELDNAMES`), UTF-8 with BOM, `DD-MM-YYYY` dates. `tests/test_prayer_times.py` rebuilds the bundled schedule and requires an exact match.
- **Existing databases keep working.** Never edit a migration in `database.py`; append a new one and bump nothing else. Keep tables and columns compatible with 1.x. `day_entries.day_type` is `CHECK`-constrained to `50/75/off` and SQLite cannot relax that, so new day behaviour rides on extra columns: *Recovered* is a Steady entry plus `start_time`, *night work* is `overtime_minutes`.
- **Alarms ring exactly once.** Claim in a transaction (`alarms.py`) *before* delivering. Keep the five-minute catch-up window, and keep one-time alarms disabling themselves when claimed.
- **Tasks belong to their day.** Only the *carried* status creates a copy, on the next day and never in the past (`Database.set_task_status`). A day's tasks may never exceed its focus time (`tasks.check_task`); carried copies are the one exception, because a task is never refused or lost. The five prayers are tasks of kind `prayer` with length 0 (`Database.ensure_prayer_tasks`): they never count as focus time, cannot be edited or deleted, may be carried once (`tasks.can_carry`) and only the carried copy may be cancelled (`tasks.can_cancel`). Never add scores or streaks for them.
- **Stopping alarms is safe.** `sound.stop_all()` signals only pids it recorded in `ringing.json` and re-checks each in `/proc` first, because pids get reused. Keep that check.
- **Offline and private.** No telemetry, no accounts. The only network call is downloading a timetable (`prayer_times.fetch_year`).
- **No GTK in the core.** `rhythm`, `pomodoro`, `tasks`, `planner`, `today`, `alarms`, `prayer_times`, `database`, `service`, `sound`, `cli` must import without `gi`. Only `fuzzy_journey/ui/` may use GTK.
- **Never write to the user's real data folder in tests.** Use `tests/helpers.DbTestCase` or a temp dir.
- Keep `README.md` accurate: if behaviour, install steps, or flags change, update it in the same change.

## Style

- Python 3.10+, standard library only (PyGObject comes from the system). Type hints on public functions; `from __future__ import annotations`.
- UI: native libadwaita widgets and theme colours. Custom CSS (`resources/style.css`) is for type and spacing only, never hard-coded colours. Use only APIs available in libadwaita 1.4.
- Minimalism is a feature. Prefer removing a control to adding one; show an element only when it is relevant.
- Wording: plain, calm, no exclamation marks, no scores or guilt.

## Checks

```bash
make test       # core unit tests (see the note below)
make test-ui    # GUI smoke tests under xvfb
make lint       # ruff
```

`make test` currently reports **10 errors, all in `tests/test_alarm_engine.py`**. They test the 1.x code (`alarm_engine.py`, `alarm_daemon.py`, `gui.py`), which nothing in 2.x imports and which calls a `database.initialize` that no longer exists. They are known and unrelated to the live app; a clean run is `Ran N tests … FAILED (errors=10)` with nothing else. Remove that legacy code and its test together, or leave both alone.

