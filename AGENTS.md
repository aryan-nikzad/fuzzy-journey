# AGENTS.md

Rules for anyone (human or AI) changing this repository. Read [PHILOSOPHY.md](PHILOSOPHY.md) first, then
*The psychology to keep* below: a change that does not serve one of the four ideas, or that works against that
psychology, probably does not belong.

## The psychology to keep

`PHILOSOPHY.md` states the four ideas. The author built this app around their own mind, and the same thinking runs
through every page, dialog and default, far beyond that file. When code and prose disagree, the *behaviour* is the
truth. Keep all of this when you change anything:

1. **The plan lives in the head; the app is scaffolding.** Recall hides everything until you say it. Today's goal and
   self-image card defaults to *say it first, then tap* (`anchor_mode`). Never replace remembering with reading.
2. **Cost is shown, never hidden.** Sleep given up, a negative bank, work cut to protect bedtime: the price of a
   choice is always on screen beside the choice.
3. **Friction for what hurts, none for what helps.** Night work asks you to move tasks to tomorrow first and only then
   lets you choose hours. Capturing an idea is one line and Enter. Do not add steps to good paths or remove them
   from costly ones.
4. **Rescue, never punishment.** Recovered and Disruption days are things you choose, they are neutral for the bank,
   and tasks that no longer fit are never pushed to tomorrow for you. Nothing is applied to you for missing a task.
5. **A mirror, not a score.** No streaks, points, targets or red numbers. A figure appears only when it is true and
   fair (habit weeks need seven finished days). Work done is shown, not graded.
6. **Firm, never trapping.** The closing check-in asks once, can be asked again later, and leaving tasks open takes a
   second deliberate click. It never asks after bedtime. The tray never strands you.
7. **Never invent, never overwrite.** Goals, self-image, rules and recovery steps are the person's words: nothing is
   seeded, rewritten or "fixed". A day is only closed if it was recorded while the app ran.
8. **Few decisions, little to remember.** Five places, one job per page, changes saved instantly, pickers instead of
   typing, rare actions behind one quiet entry, anything irrelevant hidden. Adding an option is a cost to the person's
   memory: prefer removing a control to adding one.
9. **Where a judgement call could go either way, make it a setting.** The closing check-in switches, the anchor
   mode, the Work-done units. Defaults follow the philosophy; the person decides.
10. **Calm words.** Plain, no exclamation marks, no guilt, no scores. Self-image is always present tense.
11. **Faith is the frame, not a test.** Prayer times shape the day; the app never teaches or judges practice, and
    everything about prayer can be switched off without deleting anything.

## Do not break

- **The philosophy is the spec.** The arithmetic lives only in `fuzzy_journey/rhythm.py` (the day), `pomodoro.py` (how work is cut into blocks and breaks) and `tasks.py` (task load and order). The app, the alarm service and the CLI must all use it; never re-implement a rule elsewhere. If you change a rule, change `philosophy.py`, `PHILOSOPHY.md`, `README.md` and the tests in the same commit (`tests/test_docs.py` fails when they drift). `PHILOSOPHY.md` also carries three deliberate exceptions to the four ideas, *Recovered day*, *Night work* and *Evening work*; they are not in `philosophy.py`, so keep them consistent by hand.
- **The CLI contract.** `prayer_aio.py` keeps its flags and its output text. Compare old and new output before changing `fuzzy_journey/cli.py`.
- **The CSV contract.** `*_raw.csv` and `*_schedule.csv` keep their column names and order (`prayer_times.RAW_FIELDNAMES`, `SCHEDULE_FIELDNAMES`), UTF-8 with BOM, `DD-MM-YYYY` dates. `tests/test_prayer_times.py` rebuilds the bundled schedule and requires an exact match.
- **Existing databases keep working.** Never edit a migration in `database.py`; append a new one and bump nothing else. Keep tables and columns compatible with 1.x. `day_entries.day_type` is `CHECK`-constrained to `50/75/off` and SQLite cannot relax that, so new day behaviour rides on extra columns: *Recovered* is a Steady entry plus `start_time`, *night work* is `overtime_minutes`, *evening work* is `evening_minutes`. What each day really had (focus worked, the closing state) lives in `day_progress`; a day is only closed if it was recorded while the app or the service ran, never invented afterwards.
- **Alarms ring exactly once.** Claim in a transaction (`alarms.py`) *before* delivering. Keep the five-minute catch-up window, and keep one-time alarms disabling themselves when claimed.
- **Tasks belong to their day.** Only the *carried* status creates a copy, on the next day and never in the past (`Database.set_task_status`). A day's tasks may never exceed its focus time (`tasks.check_task`); carried copies are the one exception, because a task is never refused or lost. The five prayers are tasks of kind `prayer` with length 0 (`Database.ensure_prayer_tasks`): they never count as focus time, cannot be edited or deleted, may be carried once (`tasks.can_carry`) and only the carried copy may be cancelled (`tasks.can_cancel`). Never add scores or streaks for them.
- **Stopping alarms is safe.** `sound.stop_all()` signals only pids it recorded in `ringing.json` and re-checks each in `/proc` first, because pids get reused. Keep that check.
- **Rules and Recovery are the person's words.** `principles.py` only seeds starting text, once, when schema 7 is created. Never re-seed, overwrite or "fix" what the person wrote, and never let these entries drive the schedule: A Disruption day is a day kind (`DayKind.DISRUPTION`, `OFFLINE`), but the *rules text* never drives it: nothing reads the Rules or Recovery entries.
- **Goals and Self-image are the person's words.** `goals.py` seeds nothing and nothing reads these entries to plan a day. There is one great goal (a unique index enforces it) and many horizons in the order to reach them. Never add scores, streaks or deadlines that pressure; a self-image statement must stay in the present tense (`goals.check_self`).
- **Five places.** `Today`, `Plan`, `Mind`, `Track`, `Ideas` (`MainWindow.SECTIONS`). A new page goes inside one of
  them, never in a sixth tab, and keeps its own name so `show_page(name)` opens it. `Ctrl+1` to `Ctrl+5` open the
  sections; do not move them.
- **The anchor on Today only reads.** `goals.statement_of_the_day` and `ui/anchor.py` show your own words and nothing
  else: they never plan, score or remind harder. With no words written there is no card.
- **Offline and private.** No telemetry, no accounts. The only network call is downloading a timetable (`prayer_times.fetch_year`).
- **No GTK in the core.** `rhythm`, `pomodoro`, `tasks`, `planner`, `today`, `alarms`, `prayer_times`, `principles`, `goals`, `habits`, `selftest`, `backup`, `database`, `service`, `sound`, `cli` must import without `gi`. Only `fuzzy_journey/ui/` may use GTK.
- **Never write to the user's real data folder in tests.** Use `tests/helpers.DbTestCase` or a temp dir.
- Keep `README.md` accurate: if behaviour, install steps, or flags change, update it in the same change.

## Style

- Python 3.10+, standard library only (PyGObject comes from the system). Type hints on public functions; `from __future__ import annotations`.
- UI: use `clock_now()` from `timeutil`, never `date.today()` or `datetime.now()`, so a pinned clock holds everywhere.
- UI: native libadwaita widgets and theme colours. Custom CSS (`resources/style.css`) is for type and spacing only, never hard-coded colours. Use only APIs available in libadwaita 1.4.
- Minimalism is a feature. Prefer removing a control to adding one; show an element only when it is relevant.
- Wording: plain, calm, no exclamation marks, no scores or guilt.

## Checks

```bash
make test       # core unit tests (see the note below)
make test-ui    # GUI smoke tests under xvfb
make lint       # ruff
```

`make test` and `make test-ui` are both fully green; keep them so. The UI tests need `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1` and `xvfb`.
