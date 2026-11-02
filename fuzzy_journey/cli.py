"""Command-line planner (``python3 prayer_aio.py``).

The flags and output are a compatibility contract; see AGENTS.md. This module
only does argument handling and printing. The arithmetic lives in
:mod:`fuzzy_journey.rhythm` and the data handling in :mod:`fuzzy_journey.prayer_times`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import prayer_times as pt
from .paths import APP_DATA_DIR, BUNDLED_DATA_DIR
from .rhythm import DEFAULT_EVENING_START, parse_evening_start
from .timeutil import duration_hhmm, parse_hhmm_duration

LINE = "-" * 62
DLINE = "=" * 62
DEFAULT_CITY = "shahrekord"


# --------------------------------------------------------------------------
# argparse types
# --------------------------------------------------------------------------


def parse_clock_time(value: str) -> time:
    """argparse type for ``--evening-start``."""
    try:
        return parse_evening_start(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parse_hhmm(value: str) -> timedelta:
    """argparse type for ``--flex-time``."""
    try:
        return parse_hhmm_duration(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="All-in-one prayer-times fetch / generate / show tool.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add = parser.add_argument
    add("--today", "-t", action="store_true", help="Only show today's schedule; never download or change files.")
    add("--override", "-o", action="store_true",
        help="Regenerate even if the CSVs already exist (old files are backed up first).")
    add("--no-show", "-n", action="store_true", help="After generating, do not print today's schedule.")
    add("--date", "-d", help="Show a specific date instead of today (DD-MM-YYYY).")
    add("--tomorrow", "-T", action="store_true", help="Show tomorrow's schedule instead of today's.")
    add("--50", "-f", dest="fifty", action="store_true", help="Show only the 50%% work/sleep plan.")
    add("--75", "-s", dest="seventyfive", action="store_true", help="Show only the 75%% work/sleep plan.")
    add("--schedule-only", "-S", action="store_true",
        help="Hide the prayer / sun times and day / night-length sections; show only the 50%% / 75%% "
             "wake/work/sleep plans (respecting --50 / --75).")
    add("--file", "-p", help="Show an existing schedule CSV by path (implies --today).")
    add("--flex-time", "-w", type=parse_hhmm, default=None,
        help="Extra flexible work time (HH:MM) added to the work target and re-allocated into the "
             "work blocks. Schedule only; raw data is never changed. Pass 00:00 to remove it.")
    add("--reset-flex", "-r", action="store_true",
        help="Remove all flex time (set to 00:00) by regenerating the schedule from raw (no flex time).")
    add("--evening-start", type=parse_clock_time, default=None,
        help="Set the evening work-block start (HH:MM; effective default 18:00). When supplied, the "
             "schedule is rebuilt from existing raw data without downloading.")
    add("--city", "-c", default=DEFAULT_CITY, help="City name (used for the filename).")
    add("--year", "-y", type=int, default=date.today().year, help="Year to fetch.")
    add("--lat", "-l", type=float, default=32.3261, help="Latitude.")
    add("--lon", "-L", type=float, default=50.8572, help="Longitude.")
    add("--method", "-m", type=int, default=7, help="AlAdhan calculation method.")
    return parser


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------


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


def print_plan(row: dict, pct: str) -> None:
    """The wake / work / sleep breakdown for the 50 or 75 plan."""
    section(f"{pct}% WORK/SLEEP PLAN")
    print(f"  Plan target: work {pct}% of the Fajr-to-Isha window,")
    print("  split into a morning block and an evening block.")
    print()

    line("Wake up", row[f"WakeTime_{pct}"], "same as Fajr")
    print()

    print("  Work blocks:")
    line("  Morning block", f"{row[f'MorningBlockStart_{pct}']} - {row[f'MorningBlockEnd_{pct}']}")
    evening_start = row[f"EveningBlockStart_{pct}"]
    evening_end = row[f"EveningBlockEnd_{pct}"]
    line("  Noon block (free)", f"14:00 - {evening_start}", "wellbeing / other tasks")
    if evening_start != evening_end:
        line("  Evening block", f"{evening_start} - {evening_end}")
    else:
        line("  Evening block", "None", "no overflow work")
    line("  Total work target", row[f"WorkTarget_{pct}"])
    flex = row["FlexTime"]
    if flex != "00:00":
        line("  + Flex time", flex, f"added on top of the {pct}% target")
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


def print_today_summary(row: dict, target_date: date, plans: list[str] | None = None,
                        schedule_only: bool = False) -> None:
    plans = plans or ["50", "75"]

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


def find_row_for_date(rows: list[dict], target: date) -> dict | None:
    text = target.strftime(pt.CSV_DATE_FORMAT)
    return next((row for row in rows if row.get("Date") == text), None)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def resolve_target_date(args: argparse.Namespace) -> tuple[date | None, str | None]:
    """``--date`` beats ``--tomorrow`` beats today."""
    if args.date:
        try:
            return datetime.strptime(args.date, pt.CSV_DATE_FORMAT).date(), None
        except ValueError:
            return None, f"--date must be in DD-MM-YYYY format, got: {args.date}"
    if args.tomorrow:
        return date.today() + timedelta(days=1), None
    return date.today(), None


def resolve_plan_filters(args: argparse.Namespace) -> list[str]:
    plans = []
    if getattr(args, "fifty", False):
        plans.append("50")
    if getattr(args, "seventyfive", False):
        plans.append("75")
    return plans or ["50", "75"]


def _readable_schedule(files: pt.YearFiles) -> Path | None:
    """The schedule to *show*: the working directory first, then the data folder, then the bundled year."""
    for directory in (files.directory, APP_DATA_DIR, BUNDLED_DATA_DIR):
        candidate = pt.YearFiles(directory, files.slug, files.year).schedule
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
    args = build_parser().parse_args(argv)
    files = pt.YearFiles(Path("."), args.city, args.year)

    print("=" * 70)
    print("PRAYER TIMES — ALL-IN-ONE")
    print("=" * 70)
    print(f"City / slug : {args.city}")
    print(f"Year        : {args.year}")
    print(f"Location    : {args.lat}, {args.lon}  (method {args.method})")
    print()

    target_date, date_error = resolve_target_date(args)
    if date_error:
        print(date_error)
        return 1
    plans = resolve_plan_filters(args)

    def show(explicit: Path | None = None) -> int:
        path = explicit or _readable_schedule(files)
        if explicit and not explicit.is_file():
            print(f"File not found: {explicit}")
            return 1
        if path is None or not path.is_file():
            print(f"No schedule CSV at {files.schedule}.")
            print("Run without --today to download/generate, or pass --file <path>.")
            return 1
        if not pt.csv_matches_header(path, pt.SCHEDULE_FIELDNAMES):
            print(f"Warning: {path} header does not match the expected schema.")
            print("Regenerating with --override recommended.")
            return 1
        row = find_row_for_date(pt.load_rows(path), target_date)
        if row is None:
            print(f"No entry for {target_date.strftime(pt.CSV_DATE_FORMAT)} in {path}.")
            print("The CSV may not cover this year, or it needs to be regenerated.")
            return 1
        print(f"Using schedule file: {path}")
        print(f"Date                  : {target_date.strftime(pt.CSV_DATE_FORMAT)} "
              f"({target_date.strftime('%A, %d %B %Y')})")
        if len(plans) != 2:
            print(f"  Showing only: {', '.join(p + '%' for p in plans)} plan(s)")
        print_today_summary(row, target_date, plans, schedule_only=args.schedule_only)
        return 0

    if args.file:
        return show(Path(args.file))

    # View-only paths: never download or change files.
    if (args.today or args.tomorrow or (args.date and not args.override)) and args.evening_start is None:
        return show()
    if args.schedule_only and args.evening_start is None and not (
        args.override or args.flex_time is not None or args.reset_flex
    ):
        return show()

    # Normal path. raw = prayer times (changed only by a fetch); schedule = always rebuilt from raw.
    raw_exists = pt.csv_matches_header(files.raw, pt.RAW_FIELDNAMES)
    sched_exists = pt.csv_matches_header(files.schedule, pt.SCHEDULE_FIELDNAMES)

    if args.evening_start is not None and not args.override and not raw_exists:
        print(f"Cannot rebuild the {args.year} schedule: local raw data is missing at {files.raw}.")
        print("Download the year's data first; changing the evening start itself does not fetch data.")
        return 1

    flex: timedelta | None = timedelta(0) if args.reset_flex else args.flex_time
    if args.evening_start is not None and args.flex_time is None and not args.reset_flex and sched_exists:
        existing = pt.load_rows(files.schedule)
        if existing:
            try:
                flex = parse_hhmm_duration(existing[0].get("FlexTime", "00:00"))
            except ValueError:
                flex = timedelta(0)

    want_schedule = bool(
        args.override or args.flex_time is not None or args.reset_flex
        or args.evening_start is not None or not sched_exists
    )
    need_download = args.override or not raw_exists

    if not need_download and not want_schedule:
        if find_row_for_date(pt.load_rows(files.schedule), target_date) is None:
            print(f"Note: existing schedule does not contain {target_date.strftime(pt.CSV_DATE_FORMAT)} —")
            print("      re-run with --override to refresh it.")
        print("✓ Data already present — PRESERVED (nothing downloaded or overwritten).")
        print(f"  Raw     : {files.raw}")
        print(f"  Schedule: {files.schedule}")
        print("Use --override to regenerate (existing files are backed up first).")
        print("Use --flex-time HH:MM to add flex time, or --reset-flex to clear it.")
        print()
        return show()

    # Backups
    if args.override and (raw_exists or sched_exists):
        print("⚠ Override requested — backing up existing files first.")
        pt.backup_files([files.raw, files.schedule], Path("backup"))
    elif args.evening_start is not None and sched_exists:
        folder = pt.backup_files([files.schedule], Path("backup"))
        print(f"Backed up previous derived schedule -> {folder}")

    if need_download and not args.override and (raw_exists or sched_exists):
        missing = [p.name for p in (files.raw, files.schedule) if not p.is_file()]
        print(f"Missing files detected ({', '.join(missing)}) — downloading to complete the set.")
    elif not need_download and not sched_exists and raw_exists:
        print("Schedule file missing — recalculating schedule from the existing raw data (no download needed).")

    if args.evening_start is not None:
        print(f"Evening work starts at {args.evening_start.strftime('%H:%M')} — schedule rebuilt from local raw data.")
    if args.reset_flex:
        print("Flex time cleared (00:00) — schedule rebuilt from raw, no flex time.")
    elif args.flex_time is not None:
        print(f"Flex time set to {duration_hhmm(args.flex_time)} — added to the work target "
              "(schedule only; raw data is left untouched).")

    raw_rows = None
    if need_download:
        try:
            raw_rows = pt.fetch_year(args.year, args.lat, args.lon, args.method)
        except pt.FetchError as exc:
            print(f"\n✗ Fetch failed: {exc}")
            return 1
        if not raw_rows:
            print("✗ No data returned from the API.")
            return 1
        pt.write_csv(raw_rows, pt.RAW_FIELDNAMES, files.raw)

    if want_schedule:
        if raw_rows is None:
            raw_rows = pt.load_rows(files.raw)
        schedule = pt.build_schedule(raw_rows, flex or timedelta(0), args.evening_start or DEFAULT_EVENING_START)
        pt.write_csv(schedule, pt.SCHEDULE_FIELDNAMES, files.schedule)

    print()
    print("Done.")
    print(f"  Raw data : {files.raw}")
    print(f"  Schedule : {files.schedule}")
    print("=" * 70)

    if not args.no_show:
        print()
        return show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
