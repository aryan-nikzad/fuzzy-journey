"""Prayer timetables: reading them, downloading them, deriving schedules from them.

Two CSV files exist per city and year (the format is shared with the
``prayer_aio.py`` command-line tool and must stay stable):

``<slug>_prayer_times_<year>_raw.csv``
    The prayer times exactly as returned by the AlAdhan API.

``<slug>_prayer_times_<year>_schedule.csv``
    The raw times plus derived columns: day and night lengths, the 50% / 75%
    work blocks, wake / bed / sleep. Both files use UTF-8 with a BOM, dates as
    ``DD-MM-YYYY``, and are written atomically.

The app itself only needs the raw times (the plan is computed live from them,
see :mod:`fuzzy_journey.rhythm`). The schedule CSV is kept for the CLI and for
spreadsheets.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .meta import VERSION
from .models import Location
from .paths import APP_DATA_DIR, BACKUP_DIR, BUNDLED_DATA_DIR
from .rhythm import DEFAULT_EVENING_START, calculate_work_blocks
from .timeutil import duration_hhmm

log = logging.getLogger(__name__)

CSV_DATE_FORMAT = "%d-%m-%Y"
CSV_ENCODING = "utf-8-sig"

API_URL_TEMPLATE = "https://api.aladhan.com/v1/calendar/{year}/{month}"
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.5  # politeness delay between monthly requests
REQUEST_RETRIES = 3
REQUEST_BACKOFF = 2.0

#: API field -> clean column name, in file order.
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
    "Firstthird": "FirstThirdOfNight",
    "Lastthird": "LastThirdOfNight",
}

RAW_FIELDNAMES = ["Date", *API_FIELD_TO_CLEAN_NAME.values()]

SCHEDULE_FIELDNAMES = [
    "Date",
    "Fajr", "Sunrise", "Dhuhr", "Asr", "Sunset", "Maghrib", "Isha",
    "Imsak", "Midnight", "FirstThirdOfNight", "LastThirdOfNight",
    "DaylightDuration", "NighttimeDuration", "FajrToIshaDuration", "IshaToNextFajrDuration",
    "WorkTarget_50", "WorkOverflow_50",
    "MorningBlockStart_50", "MorningBlockEnd_50",
    "EveningBlockStart_50", "EveningBlockEnd_50",
    "WorkTarget_75", "WorkOverflow_75",
    "MorningBlockStart_75", "MorningBlockEnd_75",
    "EveningBlockStart_75", "EveningBlockEnd_75",
    "FlexTime",
    "WakeTime_50", "BedTime_50", "AwakeDuration_50", "SleepDuration_50", "SleepDeficit_50",
    "WakeTime_75", "BedTime_75", "AwakeDuration_75", "SleepDuration_75", "SleepDeficit_75",
    "IsToday",
]

# --------------------------------------------------------------------------
# File naming
# --------------------------------------------------------------------------


def raw_filename(slug: str, year: int) -> str:
    return f"{slug}_prayer_times_{year}_raw.csv"


def schedule_filename(slug: str, year: int) -> str:
    return f"{slug}_prayer_times_{year}_schedule.csv"


@dataclass(frozen=True)
class YearFiles:
    """The pair of CSV files for one city and year inside one directory."""

    directory: Path
    slug: str
    year: int

    @property
    def raw(self) -> Path:
        return self.directory / raw_filename(self.slug, self.year)

    @property
    def schedule(self) -> Path:
        return self.directory / schedule_filename(self.slug, self.year)


# --------------------------------------------------------------------------
# Reading a timetable
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PrayerDay:
    day: date
    times: dict[str, time]

    def get(self, name: str) -> time | None:
        return self.times.get(name)

    def at(self, name: str) -> datetime | None:
        value = self.times.get(name)
        return datetime.combine(self.day, value) if value else None

    @property
    def fajr(self) -> time:
        return self.times["Fajr"]

    @property
    def isha(self) -> time:
        return self.times["Isha"]


@dataclass(frozen=True)
class PrayerTable:
    slug: str
    year: int
    source: Path
    days: dict[date, PrayerDay] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.days)

    def ordered(self) -> list[PrayerDay]:
        return [self.days[d] for d in sorted(self.days)]


def parse_prayer_row(row: dict[str, str]) -> PrayerDay | None:
    try:
        day = datetime.strptime(row["Date"], CSV_DATE_FORMAT).date()
    except (KeyError, ValueError):
        return None
    times: dict[str, time] = {}
    for name in RAW_FIELDNAMES[1:]:
        text = (row.get(name) or "").strip()
        if not text:
            continue
        try:
            times[name] = datetime.strptime(text[:5], "%H:%M").time()
        except ValueError:
            continue
    if "Fajr" not in times or "Isha" not in times:
        return None
    return PrayerDay(day, times)


def read_table(path: Path, slug: str, year: int) -> PrayerTable:
    days: dict[date, PrayerDay] = {}
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        for row in csv.DictReader(handle):
            parsed = parse_prayer_row(row)
            if parsed:
                days[parsed.day] = parsed
    return PrayerTable(slug=slug, year=year, source=path, days=days)


class PrayerLibrary:
    """Finds and caches timetables.

    The user's own data folder wins over the timetable bundled with the app,
    so a downloaded year always replaces the built-in one. Files are re-read
    only when they change on disk.
    """

    def __init__(self, directories: Sequence[Path] | None = None) -> None:
        self.directories = tuple(directories) if directories else (APP_DATA_DIR, BUNDLED_DATA_DIR)
        self._cache: dict[Path, tuple[int, PrayerTable]] = {}

    def find(self, slug: str, year: int) -> Path | None:
        # Raw files are smaller and carry everything the app needs.
        for directory in self.directories:
            files = YearFiles(directory, slug, year)
            for candidate in (files.raw, files.schedule):
                if candidate.is_file():
                    return candidate
        return None

    def table(self, slug: str, year: int) -> PrayerTable | None:
        path = self.find(slug, year)
        if path is None:
            return None
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return None
        cached = self._cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            table = read_table(path, slug, year)
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            log.warning("Could not read %s: %s", path, exc)
            return None
        self._cache[path] = (stamp, table)
        return table

    def day(self, slug: str, day: date) -> PrayerDay | None:
        table = self.table(slug, day.year)
        return table.days.get(day) if table else None

    def years(self, slug: str) -> list[int]:
        found: set[int] = set()
        for directory in self.directories:
            if not directory.is_dir():
                continue
            for path in directory.glob(f"{slug}_prayer_times_*_*.csv"):
                try:
                    found.add(int(path.name.split("_prayer_times_")[1][:4]))
                except (IndexError, ValueError):
                    continue
        return sorted(found)


# --------------------------------------------------------------------------
# CSV input / output
# --------------------------------------------------------------------------


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding=CSV_ENCODING, newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(rows: Iterable[dict[str, str]], fieldnames: list[str], path: Path) -> None:
    """Write atomically: a temp file is renamed into place, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", newline="", encoding=CSV_ENCODING) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    log.info("Saved %s", path)


def read_header(path: Path) -> list[str] | None:
    try:
        with open(path, encoding=CSV_ENCODING, newline="") as handle:
            return next(csv.reader(handle), None)
    except FileNotFoundError:
        return None


def csv_matches_header(path: Path, expected: list[str]) -> bool:
    """A file is only trusted if its header matches exactly."""
    header = read_header(path)
    return header is not None and header == expected


def backup_files(files: Iterable[Path], destination_root: Path = BACKUP_DIR) -> Path | None:
    """Copy existing files to ``<destination_root>/<timestamp>/``. Returns that folder if anything was copied."""
    existing = [f for f in files if f.is_file()]
    if not existing:
        return None
    folder = destination_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    for source in existing:
        shutil.copy2(source, folder / source.name)
        log.info("Backed up %s -> %s", source.name, folder)
    return folder


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------


class FetchError(RuntimeError):
    pass


def _http_json(url: str, params: dict[str, object], timeout: float) -> dict:
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": f"fuzzy-journey/{VERSION}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https URL)
        return json.load(response)


def fetch_year(
    year: int,
    latitude: float,
    longitude: float,
    method: int,
    *,
    progress: Callable[[int], None] | None = None,
    http_json: Callable[[str, dict, float], dict] = _http_json,
    sleep: Callable[[float], None] = _time.sleep,
) -> list[dict[str, str]]:
    """Download every day of ``year`` from AlAdhan, month by month, with retries and backoff."""
    rows: list[dict[str, str]] = []
    for month in range(1, 13):
        log.info("Requesting %d/%02d ...", year, month)
        url = API_URL_TEMPLATE.format(year=year, month=month)
        params = {"latitude": latitude, "longitude": longitude, "method": method}

        attempt = 0
        while True:
            attempt += 1
            try:
                result = http_json(url, params, REQUEST_TIMEOUT)
                break
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if attempt >= REQUEST_RETRIES:
                    raise FetchError(f"Failed to fetch {year}/{month} after {attempt} attempts: {exc}") from exc
                wait = REQUEST_BACKOFF**attempt
                log.warning("  Retry %d/%d in %.1fs (%s)", attempt, REQUEST_RETRIES, wait, exc)
                sleep(wait)

        if result.get("code") != 200:
            raise FetchError(f"API error for {year}/{month}: {result}")

        for day in result["data"]:
            timings = day["timings"]
            row = {"Date": day["date"]["gregorian"]["date"]}
            for api_field, clean_name in API_FIELD_TO_CLEAN_NAME.items():
                row[clean_name] = timings[api_field].split(" ")[0]  # "04:04 (+0330)" -> "04:04"
            rows.append(row)

        if progress:
            progress(month)
        sleep(REQUEST_DELAY)
    return rows


# --------------------------------------------------------------------------
# Deriving the schedule CSV
# --------------------------------------------------------------------------


def _clock(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M")


def _span_text(start: datetime, end: datetime) -> str:
    delta = end - start
    if delta.total_seconds() < 0:
        delta += timedelta(days=1)
    return duration_hhmm(delta)


def build_schedule(
    raw_rows: list[dict[str, str]],
    flex: timedelta = timedelta(0),
    evening_start: time | str = DEFAULT_EVENING_START,
    *,
    today: date | None = None,
) -> list[dict[str, str]]:
    """Turn raw rows into full schedule rows.

    Rows are always built fresh from ``raw_rows``, so re-running never
    double-counts flex time.
    """
    count = len(raw_rows)
    schedule = [dict.fromkeys(SCHEDULE_FIELDNAMES, "") for _ in range(count)]
    today_text = (today or date.today()).strftime(CSV_DATE_FORMAT)
    bed_moments: list[dict[str, datetime]] = [{} for _ in range(count)]  # per row: "isha", "50", "75"

    for i, raw in enumerate(raw_rows):
        out = schedule[i]
        following = raw_rows[i + 1] if i + 1 < count else None

        fajr, sunrise, sunset, isha = (_clock(raw[k]) for k in ("Fajr", "Sunrise", "Sunset", "Isha"))
        for name in RAW_FIELDNAMES:
            out[name] = raw[name]

        out["DaylightDuration"] = _span_text(sunrise, sunset)
        out["FajrToIshaDuration"] = _span_text(fajr, isha)
        if following:
            out["NighttimeDuration"] = _span_text(sunset, _clock(following["Sunrise"]))
            out["IshaToNextFajrDuration"] = _span_text(isha, _clock(following["Fajr"]))

        out["FlexTime"] = duration_hhmm(flex)
        isha_end = isha if isha > fajr else isha + timedelta(days=1)
        bed_moments[i]["isha"] = isha_end
        for percentage, suffix in ((0.50, "50"), (0.75, "75")):
            blocks = calculate_work_blocks(fajr, isha_end, percentage, flex, evening_start)
            out[f"WorkTarget_{suffix}"] = duration_hhmm(blocks.total)
            out[f"WorkOverflow_{suffix}"] = duration_hhmm(blocks.remain)
            out[f"MorningBlockStart_{suffix}"] = blocks.block1_start.strftime("%H:%M")
            out[f"MorningBlockEnd_{suffix}"] = blocks.block1_end.strftime("%H:%M")
            out[f"EveningBlockStart_{suffix}"] = blocks.block2_start.strftime("%H:%M")
            out[f"EveningBlockEnd_{suffix}"] = blocks.block2_end.strftime("%H:%M")

            # An empty evening block must not push bedtime to the configured start.
            bed = max(blocks.block2_end, isha_end) if blocks.remain > timedelta(0) else isha_end
            bed = bed.replace(second=0, microsecond=0)  # whole minutes, as displayed
            out[f"WakeTime_{suffix}"] = raw["Fajr"]
            out[f"BedTime_{suffix}"] = bed.strftime("%H:%M")
            out[f"AwakeDuration_{suffix}"] = _span_text(fajr, bed)
            bed_moments[i][suffix] = bed

        if raw["Date"] == today_text:
            out["IsToday"] = "X"

    # Sleep needs the next day's Fajr, which is always on the following calendar day.
    for i, out in enumerate(schedule):
        if i + 1 >= count:
            continue
        next_fajr = _clock(raw_rows[i + 1]["Fajr"]) + timedelta(days=1)
        night = next_fajr - bed_moments[i]["isha"]
        for suffix in ("50", "75"):
            bed = bed_moments[i][suffix]
            actual = max(timedelta(0), next_fajr - bed)
            out[f"SleepDuration_{suffix}"] = duration_hhmm(actual)
            out[f"SleepDeficit_{suffix}"] = duration_hhmm(max(timedelta(0), night - actual))

    return schedule


# --------------------------------------------------------------------------
# Download + save a whole year
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DownloadResult:
    files: YearFiles
    days: int
    backup: Path | None


def download_year(
    location: Location,
    year: int,
    directory: Path = APP_DATA_DIR,
    *,
    evening_start: time = DEFAULT_EVENING_START,
    flex: timedelta = timedelta(0),
    progress: Callable[[int], None] | None = None,
    http_json: Callable[[str, dict, float], dict] = _http_json,
) -> DownloadResult:
    """Fetch a full year, back up anything it replaces, and write both CSV files."""
    rows = fetch_year(
        year, location.latitude, location.longitude, location.method,
        progress=progress, http_json=http_json,
    )
    if not rows:
        raise FetchError("The service returned no data.")
    files = YearFiles(directory, location.slug, year)
    backup = backup_files([files.raw, files.schedule])
    write_csv(rows, RAW_FIELDNAMES, files.raw)
    write_csv(build_schedule(rows, flex, evening_start), SCHEDULE_FIELDNAMES, files.schedule)
    return DownloadResult(files=files, days=len(rows), backup=backup)
