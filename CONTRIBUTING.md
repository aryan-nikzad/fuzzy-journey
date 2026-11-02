# Contributing

Thanks for helping. Start with [PHILOSOPHY.md](PHILOSOPHY.md) (what the app is for) and [AGENTS.md](AGENTS.md) (what must not break).

## Layout

```
fuzzy_journey/
  philosophy.py     the four ideas, as data (shown in the app)
  rhythm.py         THE RULES: day kinds, time bank, day plan, work clock. Pure.
  today.py          builds everything the Today screen shows from the facts. Pure.
  prayer_times.py   read / download / derive timetables (CSV contract)
  alarms.py         when things ring + the "claim once" guarantee
  database.py       SQLite, migrations, typed settings
  models.py         dataclasses (Alarm, Activity, Sound, Location...)
  sound.py          tones, playback, notifications
  service.py        the background alarm service
  cli.py            the prayer_aio.py command line
  ui/               GTK 4 / libadwaita: app, window, pages/, dialogs/, widgets
  resources/        stylesheet and icon
  data/             bundled 2026 timetable (Shahrekord)
prayer_aio.py       thin entry point for cli.py
tests/              unit tests (no GTK) and a headless GUI smoke test
scripts/            seed_demo.py, screenshots.sh
```

Data flows one way: `prayer_times` + `database` -> `today.build_today` (pure) -> a page that renders it. Pages never compute rules; they call `rhythm`/`today` and `Context`.

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
- **A screen**: a `Page` subclass in `ui/pages/`, registered in `ui/window.py`. Declare `listens_to` scopes so it only redraws when needed.
- **A setting**: a typed property on `database.Settings`; show it where it is *used*, and only use Preferences for things set once.
- **A database change**: append a migration function to `MIGRATIONS`; make it idempotent.
- **Renaming the app**: edit `meta.py`, `packaging`/`install.sh` strings and the icon file name.

Run `make screenshots` after visible changes and commit the new images.
