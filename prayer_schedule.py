#!/usr/bin/env python3
"""
====================================================================
Prayer Times Fetcher & Daily Schedule Calculator
====================================================================

Fetches a full year of prayer times from the AlAdhan API and derives
a light / work / sleep schedule from them.

Running this script produces TWO files:

    1. RAW_FILE
       The prayer times exactly as returned by the API
       (Fajr, Sunrise, Dhuhr, Asr, Sunset, Maghrib, Isha, Imsak,
       Midnight, Firstthird, Lastthird).

    2. SCHEDULE_FILE
       The raw times plus every derived column:

       Day / Night
           DayLen      Sunrise -> Sunset
           NightLen    Sunset  -> next day's Sunrise
           LightLen    Fajr    -> Isha
           DarkLen     Isha    -> next day's Fajr

       50% / 75% two-block work schedule
           Wxx          xx% of Fajr -> Isha
           WxxRem       portion pushed into block 2
           WxxB1Start   Fajr
           WxxB1End     end of block 1 (capped at 14:00)
           WxxB2Start   18:00
           WxxB2End     end of block 2

       Wake / Bed / Sleep
           Wakexx       Fajr
           Bedxx        later of WxxB2End or Isha
           Awakexx      Wakexx -> Bedxx
           Sleepxx      Bedxx  -> next day's Fajr
           SleepDefxx   max(0, (Isha -> next Fajr) - Sleepxx)

       Today
           "X" on the row matching today's date.

    All duration math automatically rolls over midnight, e.g.
    Isha 20:00 -> next Fajr 05:00 gives DarkLen 09:00.

====================================================================
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ================================================================
# CONFIGURATION
# ================================================================

CITY_SLUG = "shahrekord"
YEAR = 2026
LATITUDE = 32.3261
LONGITUDE = 50.8572
METHOD = 7  # AlAdhan calculation method

API_URL_TEMPLATE = "https://api.aladhan.com/v1/calendar/{year}/{month}"
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.5  # seconds between monthly requests, to be polite to the API

OUTPUT_DIR = Path(".")
RAW_FILE = OUTPUT_DIR / f"{CITY_SLUG}_prayer_times_{YEAR}_raw.csv"
SCHEDULE_FILE = OUTPUT_DIR / f"{CITY_SLUG}_prayer_times_{YEAR}_schedule.csv"

# Names as they appear in the AlAdhan API response.
API_TIME_FIELDS = [
    "Fajr",
    "Sunrise",
    "Dhuhr",
    "Asr",
    "Sunset",
    "Maghrib",
    "Isha",
    "Imsak",
    "Midnight",
    "Firstthird",
    "Lastthird",
]

RAW_FIELDNAMES = ["Date", *API_TIME_FIELDS]

SCHEDULE_FIELDNAMES = [
    "Date",
    "Fajr", "Rise", "Dhuhr", "Asr", "Set", "Maghrib", "Isha",
    "Imsak", "Midnight", "FirstThird", "LastThird",
    "DayLen", "NightLen", "LightLen", "DarkLen",
    "W50", "W50Rem", "W50B1Start", "W50B1End", "W50B2Start", "W50B2End",
    "W75", "W75Rem", "W75B1Start", "W75B1End", "W75B2Start", "W75B2End",
    "Wake50", "Bed50", "Awake50", "Sleep50", "SleepDef50",
    "Wake75", "Bed75", "Awake75", "Sleep75", "SleepDef75",
    "Today",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("prayer_schedule")


# ================================================================
# STEP 1 - FETCH RAW DATA FROM THE API
# ================================================================

def fetch_year(year: int, latitude: float, longitude: float, method: int) -> list[dict]:
    """
    Download prayer times for every day of `year` from the AlAdhan API.

    Returns a list of plain dicts, one per day, using RAW_FIELDNAMES keys.
    Raises requests.HTTPError / RuntimeError on API failure.
    """

    rows: list[dict] = []

    for month in range(1, 13):
        log.info("Requesting %d/%02d ...", year, month)

        url = API_URL_TEMPLATE.format(year=year, month=month)
        params = {"latitude": latitude, "longitude": longitude, "method": method}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = response.json()

        if result.get("code") != 200:
            raise RuntimeError(f"API error for {year}/{month}: {result}")

        for day in result["data"]:
            timings = day["timings"]

            row = {"Date": day["date"]["gregorian"]["date"]}
            for field in API_TIME_FIELDS:
                # "04:04 (+0330)" -> "04:04"
                row[field] = timings[field].split(" ")[0]

            rows.append(row)

        time.sleep(REQUEST_DELAY)  # avoid hammering the API

    return rows


def write_raw_csv(rows: list[dict], path: Path) -> None:
    """Write the untouched API data to `path`."""

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    log.info("Raw data saved to: %s", path)


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


def calculate_work_blocks(fajr: datetime, isha: datetime, percentage: float) -> WorkBlocks:
    """
    Split `percentage` of the Fajr -> Isha window into two blocks:

        Block 1: Fajr -> 14:00 (as much of the target as fits)
        Block 2: 18:00 -> onward (whatever didn't fit in block 1)
    """

    total_duration = isha - fajr
    if total_duration.total_seconds() < 0:
        total_duration += timedelta(days=1)

    target = total_duration * percentage

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

def build_schedule(raw_rows: list[dict]) -> list[dict]:
    """
    Turn raw API rows into fully-populated schedule rows.

    Each output row is built FRESH (rather than mutating the input
    dict), so it can never end up with stray keys that don't match
    SCHEDULE_FIELDNAMES.
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

        # ---- original times (renamed for readability) -----------
        out["Date"] = raw["Date"]
        out["Fajr"] = raw["Fajr"]
        out["Rise"] = raw["Sunrise"]
        out["Dhuhr"] = raw["Dhuhr"]
        out["Asr"] = raw["Asr"]
        out["Set"] = raw["Sunset"]
        out["Maghrib"] = raw["Maghrib"]
        out["Isha"] = raw["Isha"]
        out["Imsak"] = raw["Imsak"]
        out["Midnight"] = raw["Midnight"]
        out["FirstThird"] = raw["Firstthird"]
        out["LastThird"] = raw["Lastthird"]

        # ---- day / night lengths ---------------------------------
        out["DayLen"] = duration_string(sunrise, sunset)
        out["LightLen"] = duration_string(fajr, isha)

        if next_raw is not None:
            next_sunrise = parse_time(next_raw["Sunrise"])
            next_fajr = parse_time(next_raw["Fajr"])
            out["NightLen"] = duration_string(sunset, next_sunrise)
            out["DarkLen"] = duration_string(isha, next_fajr)

        # ---- 50% / 75% two-block schedule ------------------------
        for pct, prefix in ((0.50, "W50"), (0.75, "W75")):
            blocks = calculate_work_blocks(fajr, isha, pct)
            out[prefix] = timedelta_to_string(blocks.total)
            out[f"{prefix}Rem"] = timedelta_to_string(blocks.remain)
            out[f"{prefix}B1Start"] = blocks.block1_start.strftime("%H:%M")
            out[f"{prefix}B1End"] = blocks.block1_end.strftime("%H:%M")
            out[f"{prefix}B2Start"] = blocks.block2_start.strftime("%H:%M")
            out[f"{prefix}B2End"] = blocks.block2_end.strftime("%H:%M")

        # ---- wake / bed --------------------------------------------
        for prefix in ("50", "75"):
            out[f"Wake{prefix}"] = raw["Fajr"]
            block2_end = parse_time(out[f"W{prefix}B2End"])
            bed = max(block2_end, isha)
            out[f"Bed{prefix}"] = bed.strftime("%H:%M")

        if today == raw["Date"]:
            out["Today"] = "X"

    # ---- awake / sleep (needs next row's Wake, done as a 2nd pass) --
    for i, out in enumerate(schedule):
        next_out = schedule[i + 1] if i + 1 < n else None

        for prefix in ("50", "75"):
            wake = parse_time(out[f"Wake{prefix}"])
            bed = parse_time(out[f"Bed{prefix}"])
            out[f"Awake{prefix}"] = duration_string(wake, bed)

            if next_out is not None:
                next_wake = parse_time(next_out[f"Wake{prefix}"])
                out[f"Sleep{prefix}"] = duration_string(bed, next_wake)

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

        for prefix in ("50", "75"):
            bed = parse_time(out[f"Bed{prefix}"])
            actual_sleep = next_fajr - bed
            if actual_sleep.total_seconds() < 0:
                actual_sleep += timedelta(days=1)

            deficit = max(timedelta(0), default_sleep - actual_sleep)
            out[f"SleepDef{prefix}"] = timedelta_to_string(deficit)

    return schedule


def write_schedule_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SCHEDULE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    log.info("Schedule saved to: %s", path)


# ================================================================
# MAIN
# ================================================================

def main() -> None:
    print("=" * 70)
    print("PRAYER TIMES FETCHER & DAILY SCHEDULE CALCULATOR")
    print("=" * 70)
    print(f"City / slug : {CITY_SLUG}")
    print(f"Year        : {YEAR}")
    print(f"Location    : {LATITUDE}, {LONGITUDE}  (method {METHOD})")
    print()

    raw_rows = fetch_year(YEAR, LATITUDE, LONGITUDE, METHOD)
    write_raw_csv(raw_rows, RAW_FILE)

    log.info("Calculating schedule for %d days ...", len(raw_rows))
    schedule_rows = build_schedule(raw_rows)
    write_schedule_csv(schedule_rows, SCHEDULE_FILE)

    print()
    print("Done.")
    print(f"  Raw data : {RAW_FILE}")
    print(f"  Schedule : {SCHEDULE_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
