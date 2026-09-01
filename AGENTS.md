# AGENTS.md — Notes for AI Agents

Read this before editing the repo. It captures the conventions, guarantees, and gotchas that are *not* obvious from the code alone.

## What this project is

A minimal tool that computes a **wake / work / sleep schedule** anchored to Islamic prayer times (sun-position based, so accurate and rhythm-friendly). It downloads a year of prayer times, derives work/sleep plans, and prints a readable daily breakdown.

The one script you should develop in is **`prayer_aio.py`** (all-in-one). The other two are kept for reference only:

- `prayer_schedule.py` — standalone fetch + generate.
- `today_schedule.py` — standalone "show today" viewer.

Keep `prayer_aio.py` as the source of truth and, when you touch shared logic, mirror meaningful changes into the reference scripts so they don't silently diverge.

## Layout of `prayer_aio.py`

The file is organized into numbered steps (see the section headers):

1. `fetch_year()` — downloads every month of a year from the AlAdhan API. **Retries** each monthly request (up to `REQUEST_RETRIES`, exponential backoff `REQUEST_BACKOFF`). Returns a list of dicts keyed by `RAW_FIELDNAMES`.
2. Time helpers — `parse_time()` (`HH:MM` → `datetime`), `duration_string()` / `timedelta_to_string()` (durations auto-roll over midnight).
3. `calculate_work_blocks()` — splits a % of the Fajr→Isha window into a **morning block (Fajr→14:00)** and an **evening block (18:00→onward)**; the optional `flex` timedelta is added to the target first. The 14:00–18:00 gap is the fixed break window (shown as the `Noon block (free)` display line). Re-allocating the (increased) target fills Block 1 first and spills into Block 2, which is exactly the "add flex to the morning block if it has room, else the evening block" rule.
4. `build_schedule(raw_rows, flex=timedelta(0))` — turns raw rows into fully-populated schedule rows. Builds each row **fresh** from `SCHEDULE_FIELDNAMES` (never mutates input), so output can't gain stray keys. `flex` is folded into both plans via `calculate_work_blocks()` and stored in the `FlexTime` column.
5. CSV I/O — `write_csv()` (atomic: temp file + `os.replace`), `read_header()` / `csv_matches_header()` (schema validation), `backup_existing_files()`.
6. Show/display — `load_rows()`, `find_row_for_date()`, `section()`/`line()`, `print_plan()`, `print_today_summary()`, `print_plan_filters()`.
7. Helpers — `resolve_target_date()` (`--date` > `--tomorrow` > today), `resolve_plan_filters()` (`--50`/`--75` → plan list), `parse_args()`, `resolve_paths()`, `main()`.

## Hard conventions (don't break these)

- **CSV encoding**: always open/read/write with `encoding="utf-8-sig"` (UTF-8 **with BOM**). The BOM is stripped on read; dropping it will corrupt the `Date` column key for consumers.
- **Line endings**: the `csv` module writes `\r\n` by default. This is intentional and RFC-4180 compliant; keep it. All readers open with `newline=""`, so they handle it. Don't "normalize" to `\n`.
- **Date format everywhere is `DD-MM-YYYY`** (`CSV_DATE_FORMAT = "%d-%m-%Y"`). Do not switch to ISO internally without updating every format string.
- **Header validation**: a pre-existing CSV is only trusted if `csv_matches_header()` returns True (exact field-name match). A corrupt/wrong-schema file is regenerated, not used.
- **Preserve-by-default**: the default run must **not** overwrite existing, valid CSVs. Only `--override` regenerates, and it backs up first.

## Output schema

Both schema lists live at the top of the module: `RAW_FIELDNAMES` and `SCHEDULE_FIELDNAMES`. If you add a derived column, add it to **both** the list and every place that writes/reads it (`write_csv`, `build_schedule`, and the display functions). `SCHEDULE_FIELDNAMES` is authoritative for the schedule file.

`FlexTime` lives **only** in `SCHEDULE_FIELDNAMES` (never in `RAW_FIELDNAMES`): flex time describes derived work, not prayer times.

## CLI contract

- Flags: `--today --tomorrow --50 --75 --schedule-only --date --no-show --override --file --flex-time --reset-flex --city --year --lat --lon --method`.
- `--flex-time HH:MM` uses `type=parse_hhmm` (argparse `type=` callback); it parses `HH:MM` → `timedelta` and raises a clean `ArgumentTypeError` on bad input. `--reset-flex` is `store_true`. Every flag also has a short alias (`-t -T -o -n -d -f -s -S -p -w -r -c -y -l -L -m`).
- `--50`/`--75` use `dest="fifty"`/`dest="seventyfive"` so `args.fifty` works (argparse can't derive an identifier from `--50`).
- **`%` in argparse help must be escaped as `%%`** — argparse uses `%`-formatting on help strings, so a literal `50%` raises on `--help`.
- Date resolution priority: `resolve_target_date()` → `--date` (validated) wins, else `--tomorrow`, else today.

## Behavior guarantees

- **Atomic writes**: `write_csv()` writes to `<file>.tmp` then `os.replace()`. An interrupted run leaves either the old or new file intact, never a half-written one. The temp file is cleaned up on failure.
- **Override backups**: existing CSVs are copied to `backup/<YYYYMMDD-HHMMSS>/` before regeneration (see `backup_existing_files()`).
- **Stale warning**: if existing data doesn't contain the requested target date, the default run warns and suggests `--override`.
- **Show path never downloads**: `--today`, a `--date` preview without `--override`, and `--file` are read-only (they return before any regeneration).
- **Regeneration is driven by `need_download` vs `want_schedule`** in `main()`:
  - `need_download = override or not raw_exists` — only a `--override` or a missing/corrupt raw CSV hits the API.
  - `want_schedule = override or (flex-time given) or reset-flex or not sched_exists` — the schedule is always rebuilt from raw; it is **never edited in place**.
  - So: missing schedule + present raw → **recalc with no download**; changing `--flex-time` / `--reset-flex` → **schedule-only** update, raw untouched; since raw never stores flex time, re-running never double-counts it.
  - `--today` stays strictly show-only even if `--flex-time`/`--reset-flex` are passed (the documented "never change files" contract); to apply/reset flex time and view, run `--flex-time HH:MM` / `--reset-flex` directly (they default to showing today).
  - `--schedule-only` (`-S`) is a **pure view filter** (it passes `schedule_only=` to `print_today_summary()`): it hides the prayer / day-night sections, but still regenerates the schedule when combined with `--override`/`--flex-time`/`--reset-flex`.

## Testing / manual checks

```bash
python3 -m py_compile prayer_aio.py        # syntax
python3 prayer_aio.py --help                # must render (checks %% escaping)
python3 prayer_aio.py                       # first run: download + generate + show today
python3 prayer_aio.py --today               # preserve mode: shows today, no download
python3 prayer_aio.py --50 --tomorrow       # the headline combo
python3 prayer_aio.py --override            # backs up + regenerates
python3 prayer_aio.py --date 32-13-2026     # bad date -> clean error, exit code 1
```

Generated CSVs are git-ignored (see `.gitignore`), so a fresh clone only contains source. Run the script once to materialize them.

## Do-not-break checklist

- Keep `utf-8-sig` + `\r\n` + `DD-MM-YYYY` together; they're interdependent.
- Keep the preserve-by-default guarantee — never let a default run overwrite valid data.
- Keep `write_csv` atomic; don't write in place.
- When adding columns, update `*_FIELDNAMES` and every reader/writer.
- Flex time is a **generation-time** input: it must be re-derived from `raw_rows` every run, never stored and re-added on top of an existing schedule.
- Display: `print_plan()` shows a fixed `Noon block (free)` line (14:00 – 18:00) between the morning and evening blocks, plus a `+ Flex time` line when flex > 0. `print_today_summary()` prints a `FLEX TIME APPLIED` banner whenever the viewed day's flex time is non-zero.
- Preserve the AlAdhan `latitude`/`longitude`/`method` params in `fetch_year`'s URL/params.
