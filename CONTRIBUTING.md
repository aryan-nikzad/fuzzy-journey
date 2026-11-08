# Contributing

Thanks for helping. Start with [PHILOSOPHY.md](PHILOSOPHY.md) (what the app is for) and [AGENTS.md](AGENTS.md) (what must not break).

## Layout

```
fuzzy_journey/
  philosophy.py     the four ideas, as data (shown in the app)
  rhythm.py         THE RULES: day kinds, time bank, day plan, work clock. Pure.
  pomodoro.py       focus blocks, breaks, planning, pause shifting, pomodoro alarms. Pure.
  tasks.py          task order, load against focus time, validation. Pure.
  planner.py        builds a day (shared by the app and the alarm service).
  today.py          builds everything the Today screen shows from the facts. Pure.
  prayer_times.py   read / download / derive timetables (CSV contract)
  alarms.py         when things ring + the "claim once" guarantee
  database.py       SQLite, migrations, typed settings
  models.py         dataclasses (Alarm, Activity, Sound, Location...)
  sound.py          tones, playback, notifications
  service.py        the background alarm service
  cli.py            the prayer_aio.py command line
  alarm_engine.py, alarm_daemon.py, gui.py
                    LEGACY 1.x code. Nothing imports it; see AGENTS.md.
  ui/               GTK 4 / libadwaita: app, window, pages/, dialogs/, widgets,
                    focus.py (the task list and pomodoro card shared by Today and Tomorrow)
  resources/        stylesheet and icon
  data/             bundled 2026 timetable (Shahrekord)
prayer_aio.py       thin entry point for cli.py
tests/              unit tests (no GTK) and a headless GUI smoke test
scripts/            seed_demo.py, screenshots.sh
```

Data flows one way: `prayer_times` + `database` -> `planner.build_view` -> `today.build_today` (pure; it also builds the pomodoro `Schedule`) -> a page that renders it. The app (`Context`) and the alarm service both go through `planner`, so they always agree on the day. Pages never compute rules.

Pages redraw on *scopes* emitted with `Context.changed`: `all`, `tick` (every 15 s), `day`, `rhythm`, `alarms`, `data`, `location`, `tasks`, `pomodoro`.

## Running

```bash
./run.sh                                  # from the source tree
make test && make test-ui                 # tests (test-ui needs xvfb)
XDG_DATA_HOME=/tmp/fj-demo python3 scripts/seed_demo.py
XDG_DATA_HOME=/tmp/fj-demo FUZZY_JOURNEY_NOW=2026-11-02T10:15 ./run.sh   # a realistic pinned day
```

Debug environment variables: `FUZZY_JOURNEY_NOW` pins the clock, `FUZZY_JOURNEY_PAGE` picks the first screen, `FUZZY_JOURNEY_DEMO=1` hides the service banner.

## Adding things

- **A rule** (how work, rest or sleep is computed): `rhythm.py` + a test + `philosophy.py`/docs if it changes meaning.
- **A day kind or day add-on**: it must survive the `day_type` `CHECK` (see AGENTS.md), so add a column, not a value. Keep everyday choices in `KindSelector.CHOICES` and rescues (like Recovered) behind their own control.
- **A screen**: a `Page` subclass in `ui/pages/`, registered in `ui/window.py`. Declare `listens_to` scopes so it only redraws when needed.
- **A setting**: a typed property on `database.Settings`; show it where it is *used*, and only use Preferences for things set once.
- **A database change**: append a migration function to `MIGRATIONS`; make it idempotent.
- **Renaming the app**: edit `meta.py`, `packaging`/`install.sh` strings and the icon file name.

Run `make screenshots` after visible changes and commit the new images.
