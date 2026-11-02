# AGENTS.md

Rules for anyone (human or AI) changing this repository. Read [PHILOSOPHY.md](PHILOSOPHY.md) first:
a change that does not serve one of its four ideas probably does not belong.

## Do not break

- **The philosophy is the spec.** The arithmetic lives only in `fuzzy_journey/rhythm.py`. The app, the alarm service and the CLI must all use it; never re-implement a rule elsewhere. If you change a rule, change `philosophy.py`, `PHILOSOPHY.md`, `README.md` and the tests in the same commit (`tests/test_docs.py` fails when they drift).
- **The CLI contract.** `prayer_aio.py` keeps its flags and its output text. Compare old and new output before changing `fuzzy_journey/cli.py`.
- **The CSV contract.** `*_raw.csv` and `*_schedule.csv` keep their column names and order (`prayer_times.RAW_FIELDNAMES`, `SCHEDULE_FIELDNAMES`), UTF-8 with BOM, `DD-MM-YYYY` dates. `tests/test_prayer_times.py` rebuilds the bundled schedule and requires an exact match.
- **Existing databases keep working.** Never edit a migration in `database.py`; append a new one and bump nothing else. Keep tables and columns compatible with 1.x.
- **Alarms ring exactly once.** Claim in a transaction (`alarms.py`) *before* delivering. Keep the five-minute catch-up window, and keep one-time alarms disabling themselves when claimed.
- **Offline and private.** No telemetry, no accounts. The only network call is downloading a timetable (`prayer_times.fetch_year`).
- **No GTK in the core.** `rhythm`, `today`, `alarms`, `prayer_times`, `database`, `service`, `sound`, `cli` must import without `gi`. Only `fuzzy_journey/ui/` may use GTK.
- **Never write to the user's real data folder in tests.** Use `tests/helpers.DbTestCase` or a temp dir.
- Keep `README.md` accurate: if behaviour, install steps, or flags change, update it in the same change.

## Style

- Python 3.10+, standard library only (PyGObject comes from the system). Type hints on public functions; `from __future__ import annotations`.
- UI: native libadwaita widgets and theme colours. Custom CSS (`resources/style.css`) is for type and spacing only, never hard-coded colours. Use only APIs available in libadwaita 1.4.
- Minimalism is a feature. Prefer removing a control to adding one; show an element only when it is relevant.
- Wording: plain, calm, no exclamation marks, no scores or guilt.

## Checks

```bash
make test       # core unit tests
make test-ui    # GUI smoke tests under xvfb
make lint       # ruff
```
