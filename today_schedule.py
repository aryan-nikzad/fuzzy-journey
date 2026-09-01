#!/usr/bin/env python3
"""
====================================================================
Today's Prayer & Sleep/Work Schedule Viewer
====================================================================

Reads the *_schedule.csv file produced by prayer_schedule.py, finds
the row for TODAY using the computer's actual system date (it does
NOT trust the "IsToday" column already baked into the CSV), and
prints a full, readable breakdown of:

    - Today's prayer / sun times
    - Day & night length
    - The 50% work/sleep plan (wake, work blocks, bed, sleep, deficit)
    - The 75% work/sleep plan (same, at the higher target)

Usage:
    python3 today_schedule.py
    python3 today_schedule.py --file shahrekord_prayer_times_2026_schedule.csv
    python3 today_schedule.py --date 15-03-2026     (preview any date)

====================================================================
"""

from __future__ import annotations

import argparse
import csv
import glob
import sys
from datetime import date, datetime
from pathlib import Path

# ================================================================
# CONFIG
# ================================================================

# Auto-discovery pattern used if --file isn't given, matching the
# naming convention from prayer_schedule.py: <slug>_prayer_times_<year>_schedule.csv
SCHEDULE_GLOB = "*_prayer_times_*_schedule.csv"

CSV_DATE_FORMAT = "%d-%m-%Y"  # must match the "Date" column in the CSV

LINE = "-" * 62
DLINE = "=" * 62


# ================================================================
# FILE DISCOVERY / LOADING
# ================================================================

def find_schedule_file(explicit_path: str | None) -> Path:
    """Return the schedule CSV to use, or exit with a helpful error."""

    if explicit_path:
        path = Path(explicit_path)
        if not path.is_file():
            sys.exit(f"File not found: {path}")
        return path

    matches = sorted(glob.glob(SCHEDULE_GLOB))
    if not matches:
        sys.exit(
            "No schedule CSV found in this folder.\n"
            f"Expected something matching: {SCHEDULE_GLOB}\n"
            "Run prayer_schedule.py first, or pass --file <path>."
        )

    if len(matches) > 1:
        print(f"Note: multiple schedule files found, using the first one: {matches[0]}")

    return Path(matches[0])


def load_rows(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def find_row_for_date(rows: list[dict], target: date) -> dict | None:
    target_str = target.strftime(CSV_DATE_FORMAT)
    for row in rows:
        if row.get("Date") == target_str:
            return row
    return None


# ================================================================
# DISPLAY HELPERS
# ================================================================

def section(title: str) -> None:
    print()
    print(title)
    print(LINE)


def line(label: str, value: str, note: str = "") -> None:
    label = f"{label}:"
    if note:
        print(f"  {label:<22} {value:<10} ({note})")
    else:
        print(f"  {label:<22} {value}")


def print_plan(row: dict, suffix: str) -> None:
    """Print the full wake/work/sleep breakdown for the 50 or 75 plan."""

    pct = suffix  # "50" or "75"

    section(f"{pct}% WORK/SLEEP PLAN")
    print(f"  Today's target: work {pct}% of the Fajr-to-Isha window,")
    print(f"  split into a morning block and an evening block.")
    print()

    line("Wake up", row[f"WakeTime_{pct}"], "same as Fajr")
    print()

    print("  Work blocks:")
    line(
        "  Morning block",
        f"{row[f'MorningBlockStart_{pct}']} - {row[f'MorningBlockEnd_{pct}']}",
    )
    line(
        "  Evening block",
        f"{row[f'EveningBlockStart_{pct}']} - {row[f'EveningBlockEnd_{pct}']}",
    )
    line("  Total work target", row[f"WorkTarget_{pct}"])
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


def print_today_summary(row: dict, target_date: date) -> None:
    print(DLINE)
    print(f" SCHEDULE FOR {target_date.strftime('%A, %d %B %Y')}")
    print(DLINE)

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

    print_plan(row, "50")
    print_plan(row, "75")

    print()
    print(DLINE)


# ================================================================
# MAIN
# ================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show today's prayer/work/sleep schedule.")
    parser.add_argument("--file", help="Path to a *_schedule.csv file (auto-detected if omitted)")
    parser.add_argument(
        "--date",
        help="Preview a specific date instead of today, format DD-MM-YYYY",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    schedule_path = find_schedule_file(args.file)
    rows = load_rows(schedule_path)

    if args.date:
        try:
            target_date = datetime.strptime(args.date, CSV_DATE_FORMAT).date()
        except ValueError:
            sys.exit(f"--date must be in DD-MM-YYYY format, got: {args.date}")
    else:
        target_date = date.today()  # <-- real system date, not the CSV's own "IsToday" flag

    row = find_row_for_date(rows, target_date)

    if row is None:
        sys.exit(
            f"No entry for {target_date.strftime(CSV_DATE_FORMAT)} in {schedule_path}.\n"
            "Either the CSV doesn't cover this year, or it needs to be regenerated."
        )

    print_today_summary(row, target_date)


if __name__ == "__main__":
    main()
