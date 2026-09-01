#!/usr/bin/env python3
"""
====================================================================
Prayer Times — All-In-One (AIO)
====================================================================

Everything the project needs, in a single script:

    1. FETCH       Download a full year of prayer times from the AlAdhan API
    2. GENERATE    Derive the work / sleep schedule and write two CSVs
    3. SHOW        Print a readable breakdown of today (or any date)

The two files it produces:

    <slug>_prayer_times_<year>_raw.csv
        The prayer times exactly as returned by the API.

    <slug>_prayer_times_<year>_schedule.csv
        The raw times plus every derived column (day/night lengths,
        50% & 75% two-block work schedule, wake/bed/sleep plans, ...).
        See prayer_schedule.py's docstring for the full column list.

DATA PRESERVATION (the default, safe behaviour)
-----------------------------------------------
By default this script will NOT touch files that already exist. If both
CSVs for the requested city/year are already present, it reports that
they were preserved and simply shows today's schedule — it never
overwrites or re-downloads.

Use --override to force a fresh run. Before overwriting, the existing
files are backed up with a timestamp (see the backup/ folder).

OTHER IMPROVEMENTS
------------------
    * Network requests are retried with exponential backoff.
    * CSVs are written atomically (temp file + rename) so an interrupted
      run can never leave a half-written / corrupt file.
    * A pre-existing CSV is only trusted if its header matches exactly,
      so a corrupt or wrong-version file gets regenerated instead of
      silently misused.

USAGE
-----
    # Default: download + generate + show today (skips if data exists)
    python3 prayer_aio.py

    # Just show today (requires existing data, never downloads)
    python3 prayer_aio.py --today

    # Force a fresh run, backing up whatever is there first
    python3 prayer_aio.py --override

    # Preview a specific date instead of today
    python3 prayer_aio.py --date 15-03-2026

    # Add 30 min of flexible work time on top of the work target (schedule only)
    python3 prayer_aio.py --flex-time 00:30

    # Remove any flex time again (schedule rebuilt from raw, no flex time)
    python3 prayer_aio.py --reset-flex

    # Different location / year
    python3 prayer_aio.py --city tehran --year 2027 --lat 35.6892 --lon 51.3890

====================================================================
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ================================================================
# CONFIGURATION (overridable from the command line)
# ================================================================

CITY_SLUG = "shahrekord"
YEAR = date.today().year
LATITUDE = 32.3261
LONGITUDE = 50.8572
METHOD = 7  # AlAdhan calculation method

API_URL_TEMPLATE = "https://api.aladhan.com/v1/calendar/{year}/{month}"
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.5          # seconds between monthly requests (politeness)
REQUEST_RETRIES = 3          # network attempts per month
REQUEST_BACKOFF = 2.0        # exponential backoff base (seconds)

OUTPUT_DIR = Path(".")
BACKUP_DIR = OUTPUT_DIR / "backup"

# Derived output paths (recomputed below so CLI args take effect).
RAW_FILE: Path = OUTPUT_DIR / f"{CITY_SLUG}_prayer_times_{YEAR}_raw.csv"
SCHEDULE_FILE: Path = OUTPUT_DIR / f"{CITY_SLUG}_prayer_times_{YEAR}_schedule.csv"

# Names as they appear in the AlAdhan API response (used to read the JSON).
API_TIME_FIELDS = [
    "Fajr", "Sunrise", "Dhuhr", "Asr", "Sunset", "Maghrib", "Isha",
    "Imsak", "Midnight", "Firstthird", "Lastthird",
]

# Clean, human-readable equivalents used in both output files.
API_FIELD_TO_CLEAN_NAME = {
    "Fajr": "Fajr",
    "Sunrise": "Sunrise",
    "Dhuhr": "Dhuhr",
    "Asr": "Asr",
    "Sunset": "Sunset",
    "Maghrib": "Maghrib",
    "Isha": "Isha",
    "Imsak": "Imsak",
    "Midnight": "Midnight",
    "Firstthird": "FirstThirdOfNight",  # start of the night's first third
    "Lastthird": "LastThirdOfNight",    # start of the night's last third
}

RAW_FIELDNAMES = ["Date", *API_FIELD_TO_CLEAN_NAME.values()]

SCHEDULE_FIELDNAMES = [
    "Date",
    # ---- prayer / sun times, straight from the API -----------------
    "Fajr", "Sunrise", "Dhuhr", "Asr", "Sunset", "Maghrib", "Isha",
    "Imsak", "Midnight", "FirstThirdOfNight", "LastThirdOfNight",

    # ---- day / night lengths ----------------------------------------
    "DaylightDuration",            # Sunrise -> Sunset
    "NighttimeDuration",           # Sunset -> next day's Sunrise
    "FajrToIshaDuration",          # Fajr -> Isha
    "IshaToNextFajrDuration",      # Isha -> next day's Fajr

    # ---- 50% / 75% two-block work schedule ---------------------------
    "WorkTarget_50", "WorkOverflow_50",
    "MorningBlockStart_50", "MorningBlockEnd_50",
    "EveningBlockStart_50", "EveningBlockEnd_50",
    "WorkTarget_75", "WorkOverflow_75",
    "MorningBlockStart_75", "MorningBlockEnd_75",
    "EveningBlockStart_75", "EveningBlockEnd_75",

    # ---- flex time (added to the work target when requested) --------
    "FlexTime",

    # ---- wake / sleep, 50% plan --------------------------------------
    "WakeTime_50", "BedTime_50", "AwakeDuration_50",
    "SleepDuration_50", "SleepDeficit_50",

    # ---- wake / sleep, 75% plan --------------------------------------
    "WakeTime_75", "BedTime_75", "AwakeDuration_75",
    "SleepDuration_75", "SleepDeficit_75",

    "IsToday",   # "X" on the row matching today's date
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("prayer_aio")


# ================================================================
# STEP 1 - FETCH RAW DATA FROM THE API (with retries)
# ================================================================

def fetch_year(year: int, latitude: float, longitude: float, method: int) -> list[dict]:
    """
    Download prayer times for every day of `year` from the AlAdhan API.

    Each monthly request is retried up to REQUEST_RETRIES times with
    exponential backoff so a transient network hiccup won't abort the
    whole download. Returns a list of plain dicts (one per day) keyed
    by RAW_FIELDNAMES. Raises RuntimeError on unrecoverable API failure.
    """

    rows: list[dict] = []

    for month in range(1, 13):
        log.info("Requesting %d/%02d ...", year, month)

        url = API_URL_TEMPLATE.format(year=year, month=month)
        params = {"latitude": latitude, "longitude": longitude, "method": method}

        attempt = 0
        while True:
            attempt += 1
            try:
                response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                result = response.json()
                break  # success
            except (requests.RequestException, ValueError) as exc:
                if attempt >= REQUEST_RETRIES:
                    raise RuntimeError(
                        f"Failed to fetch {year}/{month} after {attempt} attempts: {exc}"
                    ) from exc
                wait = REQUEST_BACKOFF ** attempt
                log.warning("  Retry %d/%d in %.1fs (%s)", attempt, REQUEST_RETRIES, wait, exc)
                time.sleep(wait)

        if result.get("code") != 200:
            raise RuntimeError(f"API error for {year}/{month}: {result}")

        for day in result["data"]:
            timings = day["timings"]
            row = {"Date": day["date"]["gregorian"]["date"]}
            for api_field, clean_name in API_FIELD_TO_CLEAN_NAME.items():
                # "04:04 (+0330)" -> "04:04"
                row[clean_name] = timings[api_field].split(" ")[0]
            rows.append(row)

        time.sleep(REQUEST_DELAY)  # avoid hammering the API

    return rows


# ================================================================
# STEP 2 - TIME HELPERS
# ================================================================

def parse_time(value: str) -> datetime:
    """Convert an 'HH:MM' string into a datetime (date part is arbitrary)."""
    return datetime.strptime(value, "%H:%M")


def duration_string(start: datetime, end: datetime) -> str:
    """
    Duration between two times, formatted as HH:MM.
    If `end` is earlier than `start`, assume it belongs to the next day.
    """
    duration = end - start
    if duration.total_seconds() < 0:
        duration += timedelta(days=1)
    return timedelta_to_string(duration)


def timedelta_to_string(duration: timedelta) -> str:
    """Convert a timedelta into HH:MM."""
    total_minutes = int(duration.total_seconds() / 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def parse_hhmm(value: str) -> timedelta:
    """
    Parse an 'HH:MM' string into a timedelta for --flex-time.
    Used as an argparse ``type=`` callback, so a bad value raises a
    clean argparse error instead of a traceback.
    """
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"expected HH:MM, got: {value!r}"
        )
    try:
        hours, minutes = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected integer hours/minutes in HH:MM, got: {value!r}"
        )
    if hours < 0 or minutes < 0 or minutes >= 60:
        raise argparse.ArgumentTypeError(
            f"minutes must be 00-59 and value non-negative, got: {value!r}"
        )
    return timedelta(hours=hours, minutes=minutes)


# ================================================================
# STEP 3 - TWO-BLOCK WORK SCHEDULE
# ================================================================

@dataclass
class WorkBlocks:
    total: timedelta
    remain: timedelta
    block1_start: datetime
    block1_end: datetime
    block2_start: datetime
    block2_end: datetime


def calculate_work_blocks(
    fajr: datetime, isha: datetime, percentage: float, flex: timedelta = timedelta(0)
) -> WorkBlocks:
    """
    Split `percentage` of the Fajr -> Isha window into two blocks, then add
    any `flex` time on top of that target:

        Block 1: Fajr -> 14:00 (as much of the target as fits)
        Block 2: 18:00 -> onward (whatever didn't fit in block 1)

    The flex time is folded straight into the target and re-allocated
    through the same block logic, so it lands in Block 1 whenever Block 1
    still has room before 14:00 and otherwise spills into Block 2 — i.e.
    "add it to the first block if it has space, else to the second".
    """
    total_duration = isha - fajr
    if total_duration.total_seconds() < 0:
        total_duration += timedelta(days=1)

    target = total_duration * percentage + flex

    limit_14 = fajr.replace(hour=14, minute=0, second=0, microsecond=0)
    if limit_14 < fajr:
        limit_14 += timedelta(days=1)
    block1_available = limit_14 - fajr

    block1_duration = min(target, block1_available)
    remaining = target - block1_duration

    block1_start = fajr
    block1_end = fajr + block1_duration

    block2_start = fajr.replace(hour=18, minute=0, second=0, microsecond=0)
    if block2_start < fajr:
        block2_start += timedelta(days=1)
    block2_end = block2_start + remaining

    return WorkBlocks(
        total=target,
        remain=remaining,
        block1_start=block1_start,
        block1_end=block1_end,
        block2_start=block2_start,
        block2_end=block2_end,
    )


# ================================================================
# STEP 4 - BUILD THE SCHEDULE ROWS
# ================================================================

def build_schedule(raw_rows: list[dict], flex: timedelta = timedelta(0)) -> list[dict]:
    """
    Turn raw API rows into fully-populated schedule rows.

    Each output row is built FRESH (rather than mutating the input
    dict), so it can never end up with stray keys that don't match
    SCHEDULE_FIELDNAMES.

    `flex` is extra work time added on top of the % work target (see
    calculate_work_blocks()). It is a generation-time input only: the
    schedule is always rebuilt from `raw_rows`, so re-running never
    double-counts it.
    """
    n = len(raw_rows)
    schedule: list[dict] = [dict.fromkeys(SCHEDULE_FIELDNAMES, "") for _ in range(n)]
    today = date.today().strftime("%d-%m-%Y")  # CSV dates are DD-MM-YYYY

    for i, raw in enumerate(raw_rows):
        out = schedule[i]
        next_raw: Optional[dict] = raw_rows[i + 1] if i + 1 < n else None

        fajr = parse_time(raw["Fajr"])
        sunrise = parse_time(raw["Sunrise"])
        sunset = parse_time(raw["Sunset"])
        isha = parse_time(raw["Isha"])

        # ---- original times (copied straight through) -------------
        out["Date"] = raw["Date"]
        out["Fajr"] = raw["Fajr"]
        out["Sunrise"] = raw["Sunrise"]
        out["Dhuhr"] = raw["Dhuhr"]
        out["Asr"] = raw["Asr"]
        out["Sunset"] = raw["Sunset"]
        out["Maghrib"] = raw["Maghrib"]
        out["Isha"] = raw["Isha"]
        out["Imsak"] = raw["Imsak"]
        out["Midnight"] = raw["Midnight"]
        out["FirstThirdOfNight"] = raw["FirstThirdOfNight"]
        out["LastThirdOfNight"] = raw["LastThirdOfNight"]

        # ---- day / night lengths ---------------------------------
        out["DaylightDuration"] = duration_string(sunrise, sunset)
        out["FajrToIshaDuration"] = duration_string(fajr, isha)

        if next_raw is not None:
            next_sunrise = parse_time(next_raw["Sunrise"])
            next_fajr = parse_time(next_raw["Fajr"])
            out["NighttimeDuration"] = duration_string(sunset, next_sunrise)
            out["IshaToNextFajrDuration"] = duration_string(isha, next_fajr)

        # ---- flex time + 50% / 75% two-block schedule --------------
        # Flex time is written once per row; it feeds both plans below.
        out["FlexTime"] = timedelta_to_string(flex)
        for pct, suffix in ((0.50, "50"), (0.75, "75")):
            blocks = calculate_work_blocks(fajr, isha, pct, flex)
            out[f"WorkTarget_{suffix}"] = timedelta_to_string(blocks.total)
            out[f"WorkOverflow_{suffix}"] = timedelta_to_string(blocks.remain)
            out[f"MorningBlockStart_{suffix}"] = blocks.block1_start.strftime("%H:%M")
            out[f"MorningBlockEnd_{suffix}"] = blocks.block1_end.strftime("%H:%M")
            out[f"EveningBlockStart_{suffix}"] = blocks.block2_start.strftime("%H:%M")
            out[f"EveningBlockEnd_{suffix}"] = blocks.block2_end.strftime("%H:%M")

        # ---- wake / bed --------------------------------------------
        for suffix in ("50", "75"):
            out[f"WakeTime_{suffix}"] = raw["Fajr"]
            block2_end = parse_time(out[f"EveningBlockEnd_{suffix}"])
            bed = max(block2_end, isha)
            out[f"BedTime_{suffix}"] = bed.strftime("%H:%M")

        if today == raw["Date"]:
            out["IsToday"] = "X"

    # ---- awake / sleep (needs next row's wake time, 2nd pass) -------
    for i, out in enumerate(schedule):
        next_out = schedule[i + 1] if i + 1 < n else None
        for suffix in ("50", "75"):
            wake = parse_time(out[f"WakeTime_{suffix}"])
            bed = parse_time(out[f"BedTime_{suffix}"])
            out[f"AwakeDuration_{suffix}"] = duration_string(wake, bed)
            if next_out is not None:
                next_wake = parse_time(next_out[f"WakeTime_{suffix}"])
                out[f"SleepDuration_{suffix}"] = duration_string(bed, next_wake)

    # ---- sleep deficit (needs next row's Fajr) -----------------------
    for i, out in enumerate(schedule):
        next_raw = raw_rows[i + 1] if i + 1 < n else None
        if next_raw is None:
            continue
        isha = parse_time(out["Isha"])
        next_fajr = parse_time(next_raw["Fajr"])
        default_sleep = next_fajr - isha
        if default_sleep.total_seconds() < 0:
            default_sleep += timedelta(days=1)
        for suffix in ("50", "75"):
            bed = parse_time(out[f"BedTime_{suffix}"])
            actual_sleep = next_fajr - bed
            if actual_sleep.total_seconds() < 0:
                actual_sleep += timedelta(days=1)
            deficit = max(timedelta(0), default_sleep - actual_sleep)
            out[f"SleepDeficit_{suffix}"] = timedelta_to_string(deficit)

    return schedule


# ================================================================
# STEP 5 - ATOMIC CSV I/O + HEADER VALIDATION
# ================================================================

def write_csv(rows: list[dict], fieldnames: list[str], path: Path) -> None:
    """
    Write `rows` to `path` atomically: data is written to a temporary
    file in the same directory, then os.replace()d into place. An
    interrupted write therefore leaves either the old file or the new
    one intact, never a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up the temp file if anything went wrong.
        tmp_path.unlink(missing_ok=True)
        raise
    log.info("Saved to: %s", path)


def read_header(path: Path) -> list[str] | None:
    """Return the first line of a CSV as a list of field names, or None."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            return next(reader, None)  # the first line IS the header
    except FileNotFoundError:
        return None


def csv_matches_header(path: Path, expected: list[str]) -> bool:
    """True if the file exists and its header exactly matches `expected`."""
    header = read_header(path)
    return header is not None and header == expected


def backup_existing_files() -> None:
    """
    Copy any existing output CSVs into backup/<timestamp>/ so a forced
    refresh never destroys the current data. Missing files are skipped.
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / timestamp
    dest.mkdir(parents=True, exist_ok=True)

    for src in (RAW_FILE, SCHEDULE_FILE):
        if src.is_file():
            shutil.copy2(src, dest / src.name)
            log.info("Backed up %s -> %s", src.name, dest.name)
        else:
            log.info("Nothing to back up: %s", src.name)


# ================================================================
# STEP 6 - SHOW TODAY'S SCHEDULE (merged from today_schedule.py)
# ================================================================

SCHEDULE_GLOB = "*_prayer_times_*_schedule.csv"
CSV_DATE_FORMAT = "%d-%m-%Y"
LINE = "-" * 62
DLINE = "=" * 62


def load_rows(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def find_row_for_date(rows: list[dict], target: date) -> dict | None:
    target_str = target.strftime(CSV_DATE_FORMAT)
    for row in rows:
        if row.get("Date") == target_str:
            return row
    return None


def section(title: str) -> None:
    print()
    print(title)
    print(LINE)


def line(label: str, value: str, note: str = "") -> None:
    label = f"{label}:"
    if note:
        print(f"  {label:<24} {value:<10} ({note})")
    else:
        print(f"  {label:<24} {value}")


def print_plan(row: dict, suffix: str) -> None:
    """Print the full wake/work/sleep breakdown for the 50 or 75 plan."""
    pct = suffix

    section(f"{pct}% WORK/SLEEP PLAN")
    print(f"  Plan target: work {pct}% of the Fajr-to-Isha window,")
    print(f"  split into a morning block and an evening block.")
    print()

    line("Wake up", row[f"WakeTime_{pct}"], "same as Fajr")
    print()

    print("  Work blocks:")
    line(
        "  Morning block",
        f"{row[f'MorningBlockStart_{pct}']} - {row[f'MorningBlockEnd_{pct}']}",
    )
    line("  Noon block (free)", "14:00 - 18:00", "wellbeing / other tasks")
    line(
        "  Evening block",
        f"{row[f'EveningBlockStart_{pct}']} - {row[f'EveningBlockEnd_{pct}']}",
    )
    line("  Total work target", row[f"WorkTarget_{pct}"])
    flex = row["FlexTime"]
    if flex != "00:00":
        line("  + Flex time", flex, "added on top of the %s%% target" % pct)
    overflow = row[f"WorkOverflow_{pct}"]
    if overflow != "00:00":
        line("  Overflow to evening", overflow, "didn't fit before 14:00")
    print()

    line("Bed time", row[f"BedTime_{pct}"], "later of evening block end / Isha")
    line("Awake duration", row[f"AwakeDuration_{pct}"], "wake -> bed")
    line("Sleep duration", row[f"SleepDuration_{pct}"], "bed -> next Fajr")

    deficit = row[f"SleepDeficit_{pct}"]
    if deficit == "00:00":
        line("Sleep deficit", deficit, "no deficit vs. the default Isha->Fajr window")
    else:
        line("Sleep deficit", deficit, "less sleep than the default Isha->Fajr window")


def print_plan_filters(plans: list[str]) -> None:
    """Print a compact note describing which plans are shown (50 / 75 / both)."""
    if len(plans) == 2:
        return
    label = ", ".join(f"{p}%" for p in plans)
    print(f"  Showing only: {label} plan(s)")


def print_today_summary(
    row: dict, target_date: date, plans: list[str] | None = None, schedule_only: bool = False
) -> None:
    if plans is None:
        plans = ["50", "75"]

    # ---- flex-time warning (shown whenever any flex time is applied) --------
    flex = row.get("FlexTime", "00:00")
    if flex and flex != "00:00":
        print(DLINE)
        print(f"  ! FLEX TIME APPLIED: {flex} is added to the work target(s) below.")
        print("    It is stored per day in the schedule CSV; clear it with --reset-flex.")
        print(DLINE)
        print()

    print(DLINE)
    print(f" SCHEDULE FOR {target_date.strftime('%A, %d %B %Y')}")
    print(DLINE)

    if not schedule_only:
        section("PRAYER / SUN TIMES")
        line("Imsak", row["Imsak"], "fasting begins")
        line("Fajr", row["Fajr"], "dawn prayer")
        line("Sunrise", row["Sunrise"])
        line("Dhuhr", row["Dhuhr"], "noon prayer")
        line("Asr", row["Asr"], "afternoon prayer")
        line("Sunset", row["Sunset"])
        line("Maghrib", row["Maghrib"], "sunset prayer")
        line("Isha", row["Isha"], "night prayer")
        line("Midnight", row["Midnight"], "Islamic midpoint of the night")
        line("First third of night", row["FirstThirdOfNight"])
        line("Last third of night", row["LastThirdOfNight"])

        section("DAY / NIGHT LENGTH")
        line("Daylight duration", row["DaylightDuration"], "Sunrise -> Sunset")
        line("Nighttime duration", row["NighttimeDuration"], "Sunset -> next Sunrise")
        line("Fajr-to-Isha duration", row["FajrToIshaDuration"])
        line("Isha-to-next-Fajr duration", row["IshaToNextFajrDuration"])

    for suffix in ("50", "75"):
        if suffix in plans:
            print_plan(row, suffix)

    print()
    print(DLINE)


# ================================================================
# DATE RESOLUTION
# ================================================================

def resolve_target_date(args: argparse.Namespace) -> tuple[date, str | None]:
    """
    Work out which date to display.

    Priority (most specific first): --date  >  --tomorrow  >  today.
    Returns (target_date, None) on success or (None, error_message)
    if --date was malformed.
    """
    if args.date:
        try:
            return datetime.strptime(args.date, CSV_DATE_FORMAT).date(), None
        except ValueError:
            return None, f"--date must be in DD-MM-YYYY format, got: {args.date}"
    if args.tomorrow:
        return date.today() + timedelta(days=1), None
    return date.today(), None


def resolve_plan_filters(args: argparse.Namespace) -> list[str]:
    """Decide which plans to display: explicitly chosen 50 / 75, or both."""
    plans = []
    if getattr(args, "fifty", False):
        plans.append("50")
    if getattr(args, "seventyfive", False):
        plans.append("75")
    return plans or ["50", "75"]


# ================================================================
# ARGUMENT PARSING
# ================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="All-in-one prayer-times fetch / generate / show tool.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Short aliases (first char of the long flag, upper-cased where it would
    # otherwise collide, e.g. -t today / -T tomorrow, -l lat / -L lon).
    parser.add_argument("--today", "-t", action="store_true",
                        help="Only show today's schedule; never download or change files.")
    parser.add_argument("--override", "-o", action="store_true",
                        help="Regenerate even if the CSVs already exist (old files are backed up first).")
    parser.add_argument("--no-show", "-n", action="store_true",
                        help="After generating, do not print today's schedule.")
    parser.add_argument("--date", "-d", help="Show a specific date instead of today (DD-MM-YYYY).")
    parser.add_argument("--tomorrow", "-T", action="store_true",
                        help="Show tomorrow's schedule instead of today's.")
    parser.add_argument("--50", "-f", dest="fifty", action="store_true",
                        help="Show only the 50%% work/sleep plan.")
    parser.add_argument("--75", "-s", dest="seventyfive", action="store_true",
                        help="Show only the 75%% work/sleep plan.")
    parser.add_argument("--schedule-only", "-S", action="store_true",
                        help="Hide the prayer / sun times and day / night-length sections; "
                             "show only the 50%% / 75%% wake/work/sleep plans (respecting --50 / --75).")
    parser.add_argument("--file", "-p", help="Show an existing schedule CSV by path (implies --today).")

    parser.add_argument("--flex-time", "-w", type=parse_hhmm, default=None,
                        help="Extra flexible work time (HH:MM) added to the work target and "
                             "re-allocated into the work blocks. Schedule only; raw data "
                             "is never changed. Pass 00:00 to remove it.")
    parser.add_argument("--reset-flex", "-r", action="store_true",
                        help="Remove all flex time (set to 00:00) by regenerating the "
                             "schedule from raw (no flex time).")

    parser.add_argument("--city", "-c", default=CITY_SLUG, help="City name (used for the filename).")
    parser.add_argument("--year", "-y", type=int, default=YEAR, help="Year to fetch.")
    parser.add_argument("--lat", "-l", type=float, default=LATITUDE, help="Latitude.")
    parser.add_argument("--lon", "-L", type=float, default=LONGITUDE, help="Longitude.")
    parser.add_argument("--method", "-m", type=int, default=METHOD, help="AlAdhan calculation method.")

    return parser.parse_args()


# ================================================================
# MAIN
# ================================================================

def resolve_paths(args: argparse.Namespace) -> None:
    """Recompute the output paths from the (possibly overridden) config."""
    global RAW_FILE, SCHEDULE_FILE, CITY_SLUG, YEAR
    CITY_SLUG = args.city
    YEAR = args.year
    RAW_FILE = OUTPUT_DIR / f"{CITY_SLUG}_prayer_times_{YEAR}_raw.csv"
    SCHEDULE_FILE = OUTPUT_DIR / f"{CITY_SLUG}_prayer_times_{YEAR}_schedule.csv"


def main() -> None:
    args = parse_args()
    resolve_paths(args)

    print("=" * 70)
    print("PRAYER TIMES — ALL-IN-ONE")
    print("=" * 70)
    print(f"City / slug : {CITY_SLUG}")
    print(f"Year        : {YEAR}")
    print(f"Location    : {args.lat}, {args.lon}  (method {args.method})")
    print()

    # -----------------------------------------------------------
    # Work out which date to show and which plans to render, up front.
    # --date > --tomorrow > today ; --50 / --75 restrict the plans.
    # -----------------------------------------------------------
    target_date, date_error = resolve_target_date(args)
    if date_error:
        print(date_error)
        return 1
    plans = resolve_plan_filters(args)

    # -----------------------------------------------------------
    # SHOW PATH (existing data, no download needed).
    # --file always shows; --today or a --date preview (without
    # --override) never download or change any file.
    # -----------------------------------------------------------
    def show_schedule(explicit_path: Optional[Path] = None) -> int:
        path = explicit_path or SCHEDULE_FILE
        if explicit_path and not explicit_path.is_file():
            print(f"File not found: {explicit_path}")
            return 1
        if not path.is_file():
            print(f"No schedule CSV at {path}.")
            print("Run without --today to download/generate, or pass --file <path>.")
            return 1
        if not csv_matches_header(path, SCHEDULE_FIELDNAMES):
            print(f"Warning: {path} header does not match the expected schema.")
            print("Regenerating with --override recommended.")
            return 1

        rows = load_rows(path)
        row = find_row_for_date(rows, target_date)
        if row is None:
            print(f"No entry for {target_date.strftime(CSV_DATE_FORMAT)} in {path}.")
            print("The CSV may not cover this year, or it needs to be regenerated.")
            return 1

        print(f"Using schedule file: {path}")
        print(f"Date                  : {target_date.strftime(CSV_DATE_FORMAT)} "
              f"({target_date.strftime('%A, %d %B %Y')})")
        print_plan_filters(plans)
        print_today_summary(row, target_date, plans, schedule_only=args.schedule_only)
        return 0

    # -----------------------------------------------------------
    # Explicit --file: always show-only.
    # -----------------------------------------------------------
    if args.file:
        return show_schedule(Path(args.file))

    # -----------------------------------------------------------
    # VIEW PATH: show existing data without downloading or changing
    # files. --schedule-only is a pure view option too — unless the
    # user also asks to generate (--override / --flex-time /
    # --reset-flex), in which case it falls through to the normal
    # (generate) path and the schedule-only filter is applied on show.
    # -----------------------------------------------------------
    if args.file:
        return show_schedule(Path(args.file))

    if args.today or args.tomorrow or (args.date and not args.override):
        return show_schedule()

    if args.schedule_only and not (
        args.override or args.flex_time is not None or args.reset_flex
    ):
        return show_schedule()

    # -----------------------------------------------------------
    # NORMAL PATH: decide what to (re)generate.
    #
    #   raw   = prayer times (only ever changed by a fetch / --override)
    #   sched = derived schedule, ALWAYS rebuilt from raw — it is never
    #           edited in place, so a flex-time change only touches it.
    #
    #   need_download = we must hit the API (override, or raw is gone).
    #   want_schedule = we must rebuild the schedule (override, flex
    #                   time changed/reset, or the schedule is missing).
    #                   Note: if only the schedule is missing and the raw
    #                   file is already there, we recalc with NO download.
    # -----------------------------------------------------------
    raw_exists = csv_matches_header(RAW_FILE, RAW_FIELDNAMES)
    sched_exists = csv_matches_header(SCHEDULE_FILE, SCHEDULE_FIELDNAMES)

    # Resolve the flex-time input for this run.
    if args.reset_flex:
        flex: Optional[timedelta] = timedelta(0)  # reset -> 00:00
    else:
        flex = args.flex_time  # a timedelta, or None if --flex-time absent

    want_schedule = (
        args.override
        or args.flex_time is not None
        or args.reset_flex
        or not sched_exists
    )
    need_download = args.override or not raw_exists

    # Warn if the existing schedule doesn't cover the target date (stale).
    if not need_download and not want_schedule:
        rows = load_rows(SCHEDULE_FILE)
        if find_row_for_date(rows, target_date) is None:
            print(f"Note: existing schedule does not contain "
                  f"{target_date.strftime(CSV_DATE_FORMAT)} —")
            print("      re-run with --override to refresh it.")

    # Preserve everything when there is genuinely nothing to regenerate.
    if not need_download and not want_schedule:
        print("✓ Data already present — PRESERVED (nothing downloaded or overwritten).")
        print(f"  Raw     : {RAW_FILE}")
        print(f"  Schedule: {SCHEDULE_FILE}")
        print("Use --override to regenerate (existing files are backed up first).")
        print("Use --flex-time HH:MM to add flex time, or --reset-flex to clear it.")
        print()
        return show_schedule()

    # ---- backups ----
    if args.override and (raw_exists or sched_exists):
        print("⚠ Override requested — backing up existing files first.")
        backup_existing_files()

    # ---- explain what we are about to do ----
    if need_download and not args.override and (raw_exists or sched_exists):
        missing = [p.name for p in (RAW_FILE, SCHEDULE_FILE) if not p.is_file()]
        print(f"Missing files detected ({', '.join(missing)}) — downloading to complete the set.")
    elif not need_download and not sched_exists and raw_exists:
        print("Schedule file missing — recalculating schedule from the existing "
              "raw data (no download needed).")

    if args.reset_flex:
        print("Flex time cleared (00:00) — schedule rebuilt from raw, no flex time.")
    elif args.flex_time is not None:
        print(f"Flex time set to {timedelta_to_string(args.flex_time)} — added to the "
              "work target (schedule only; raw data is left untouched).")

    # ---- fetch raw (only when we must) ----
    raw_rows: Optional[list[dict]] = None
    if need_download:
        try:
            raw_rows = fetch_year(args.year, args.lat, args.lon, args.method)
        except RuntimeError as exc:
            print(f"\n✗ Fetch failed: {exc}")
            return 1

        if not raw_rows:
            print("✗ No data returned from the API.")
            return 1

        write_csv(raw_rows, RAW_FIELDNAMES, RAW_FILE)

    # ---- build + write schedule (only when we must) ----
    if want_schedule:
        if raw_rows is None:
            # We are only (re)building the schedule; the raw data is already
            # on disk. Load it so the schedule is always generated from raw.
            raw_rows = load_rows(RAW_FILE)
        log.info("Calculating schedule for %d days ...", len(raw_rows))
        schedule_rows = build_schedule(raw_rows, flex if flex is not None else timedelta(0))
        write_csv(schedule_rows, SCHEDULE_FIELDNAMES, SCHEDULE_FILE)

    # ---- done ----
    print()
    print("Done.")
    print(f"  Raw data : {RAW_FILE}")
    print(f"  Schedule : {SCHEDULE_FILE}")
    print("=" * 70)

    if not args.no_show:
        print()
        return show_schedule()
    return 0


if __name__ == "__main__":
    sys.exit(main())
