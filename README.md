# Fuzzy Journey

A minimal, single-purpose tool that works out **when you should wake up, work, and sleep** — anchored to Islamic prayer times.

Prayer times are derived from the sun's position, so they're astronomically accurate and fall at consistent points in your day. That makes them excellent anchors for a schedule that respects your body's natural rhythm.

---

## The idea

The time from **Fajr (dawn)** to **Isha (night)** is your main waking window. From that we derive a wake / work / sleep plan:

- **Wake up** = Fajr.
- **Work** is split into two blocks — a morning block (Fajr → **14:00**) and an evening block (**18:00** → onward).
- The fixed **14:00 → 18:00** gap (4 hours) is yours for everything else: a 2-hour gym session (14:00–16:00), a 2-hour call with your girlfriend (16:00–18:00), whatever.
- **Bed time** = the later of the evening block's end or Isha.
- **Sleep** = bed time → next day's Fajr.

You can choose how hard to push: a **50%** plan (a gentler, sustainable day) or a **75%** plan (a longer, more demanding one). The tool tells you exactly what hours each plan implies and how much sleep you'd get — and flags a **sleep deficit** if pushing the plan eats into your natural recovery window.

---

## Features

- Downloads a **full year** of prayer times from the [AlAdhan API](https://aladhan.com/prayer-times-api).
- Derives day/night lengths and both the **50%** and **75%** work/sleep plans.
- **Flex-time** support: add extra `--flex-time HH:MM` of work on top of a plan, re-allocated into the work blocks (morning first, evening if it's full); **`--reset-flex`** clears it back to `00:00`. Shows a labeled **noon block** and warns whenever flex time is applied.
- **`--schedule-only`** to hide the prayer / day-night sections and show just the work/sleep plans.
- **All-in-one** script: fetch → generate → display.
- **Preserves existing data** by default — it won't overwrite CSVs that are already there.
- **`--override`** to refresh, with an automatic **timestamped backup** first.
- **Show today**, **show tomorrow**, or **preview any date**.
- **Filter** to just the 50% or 75% plan.
- Network retries, atomic file writes, and header validation so nothing gets silently corrupted.

---

## Install

Requires Python 3.10+ and one dependency:

```bash
pip install requests
```

That's it — everything else is in the standard library.

---

## Usage

```bash
# First run: download a year + generate + show today
python3 prayer_aio.py

# Just show today from existing data (never downloads)
python3 prayer_aio.py --today

# Show tomorrow
python3 prayer_aio.py --tomorrow

# Only the 50% plan, for tomorrow  (the combo you actually want)
python3 prayer_aio.py --50 --tomorrow

# Only the 75% plan, for today
python3 prayer_aio.py --75

# Preview a specific date
python3 prayer_aio.py --date 15-03-2026

# Add 30 min of flex time on top of the work plan (schedule only)
python3 prayer_aio.py --flex-time 00:30

# Clear any flex time again — schedule rebuilt from raw, no flex time
python3 prayer_aio.py --reset-flex

# Show only the 50% / 75% plans (hide prayer + day/night sections)
python3 prayer_aio.py --schedule-only

# Force a refresh (existing files are backed up first)
python3 prayer_aio.py --override
```

### Options

| Flag | Description |
|------|-------------|
| `--today` | Show only today; never download or change files. |
| `--tomorrow` | Show tomorrow's schedule instead of today's. |
| `--50` | Show only the 50% work/sleep plan. |
| `--75` | Show only the 75% work/sleep plan. |
| `--schedule-only` | Hide the prayer / sun times and day / night-length sections; show only the 50% / 75% plans. Pure view unless combined with `--override` / `--flex-time`. |
| `--date DD-MM-YYYY` | Preview a specific date. |
| `--no-show` | Generate but don't print the schedule. |
| `--override` | Regenerate even if files exist (old files backed up first). |
| `--file PATH` | Show an existing schedule CSV by path. |
| `--flex-time HH:MM` | Extra flexible work time added to the work target and re-allocated into the work blocks (see below). Schedule CSV only; raw data is never changed. Pass `00:00` to remove. |
| `--reset-flex` | Regenerate the schedule with flex time set to `00:00` (looks exactly like the base plan). |
| `--city NAME` | City label used in the filenames. |
| `--year YYYY` | Year to fetch (defaults to the current year). |
| `--lat L --lon L` | Coordinates (defaults to Shahrekord, Iran). |
| `--method N` | AlAdhan calculation method (default: 7). |

Every flag also has a short alias — `-t`, `-T`, `-o`, `-n`, `-d`, `-f`, `-s`, `-S`, `-p`, `-w`, `-r`, `-c`, `-y`, `-l`, `-L`, `-m` — so `-w 00:30 -S` adds flex time and shows just the plans.

---

## Output files

Running a download produces two CSVs in the current folder:

- `<city>_prayer_times_<year>_raw.csv` — the prayer times exactly as returned by the API.
- `<city>_prayer_times_<year>_schedule.csv` — the raw times plus every derived column (day/night lengths, both work plans, wake/bed/sleep durations, a `FlexTime` column, and a `IsToday` flag).

### Flex time

`--flex-time HH:MM` is extra work time you consciously add on top of a plan — think of it as reclaiming spare moments rather than "wasting" anything. It is **added to the work target** and then re-allocated into the work blocks:

- It goes into the **morning block** (Fajr → 14:00) whenever that block still has room.
- If the morning block is already full, it spills into the **evening block** (18:00 → onward).
- It is added to **both** the 50% and 75% plans.

The fixed afternoon break (14:00 → 18:00) is shown explicitly in each plan as the **`Noon block (free)`** line — your wellbeing / other-tasks window. Whenever flex time is applied to a day, the viewer prints a `FLEX TIME APPLIED` banner so you always know it's there; the amount is also stored per day in the `FlexTime` column of the schedule CSV.

The schedule CSV is **always regenerated from the raw CSV** — it is never edited in place — so `--flex-time` only touches the schedule file, never the raw file, and re-running never double-counts it. Use **`--reset-flex`** (or `--flex-time 00:00`) to clear it; the schedule then looks exactly like the plan computed without any flex time.

> If only the schedule CSV is missing but the raw CSV is present, the schedule is recalculated **without any download**. Only a missing/corrupt raw CSV triggers a fresh download.

> CSVs are generated data and are git-ignored — regenerate them anytime with `python3 prayer_aio.py`.

---

## Project files

| File | Purpose |
|------|---------|
| `prayer_aio.py` | All-in-one: fetch, generate, and display. Use this one. |
| `prayer_schedule.py` | Standalone fetch + generate (kept for reference). |
| `today_schedule.py` | Standalone "show today" viewer (kept for reference). |
| `AGENTS.md` | Notes for AI coding agents working on this repo. |

---

## Notes

- Data source: [AlAdhan Prayer Times API](https://aladhan.com/prayer-times-api) (free, no key required).
- Times are shown in local time as returned by the API; durations auto-roll over midnight.
- The `14:00` / `18:00` midday boundaries are hardcoded as the fixed break window — change `limit_14` / `block2_start` in `calculate_work_blocks()` if you want different break hours.
