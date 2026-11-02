from __future__ import annotations

import tempfile
import unittest
from datetime import date, time, timedelta
from pathlib import Path

from fuzzy_journey import prayer_times as pt
from fuzzy_journey.models import Location
from fuzzy_journey.paths import BUNDLED_DATA_DIR


def fake_api(url, params, timeout):
    month = int(url.rstrip("/").split("/")[-1])
    return {
        "code": 200,
        "data": [{
            "date": {"gregorian": {"date": f"01-{month:02d}-2027"}},
            "timings": {k: "05:00 (+0330)" for k in pt.API_FIELD_TO_CLEAN_NAME},
        }],
    }


class BundledDataTests(unittest.TestCase):
    def test_rebuilding_the_schedule_reproduces_the_bundled_csv_exactly(self):
        raw = pt.load_rows(BUNDLED_DATA_DIR / "shahrekord_prayer_times_2026_raw.csv")
        old = pt.load_rows(BUNDLED_DATA_DIR / "shahrekord_prayer_times_2026_schedule.csv")
        new = pt.build_schedule(raw, today=date(2026, 1, 1))
        self.assertEqual(len(old), len(new))
        for before, after in zip(old, new):
            for column in pt.SCHEDULE_FIELDNAMES:
                if column != "IsToday":
                    self.assertEqual(before[column], after[column], f"{before['Date']} {column}")

    def test_headers_match_the_contract(self):
        for name, fields in (("raw", pt.RAW_FIELDNAMES), ("schedule", pt.SCHEDULE_FIELDNAMES)):
            path = BUNDLED_DATA_DIR / f"shahrekord_prayer_times_2026_{name}.csv"
            self.assertTrue(pt.csv_matches_header(path, fields))


class PastMidnightTests(unittest.TestCase):
    def test_evening_work_past_midnight_moves_bedtime_and_reports_the_lost_sleep(self):
        # Regression: 1.x reported bed 18:20 and no deficit while work ran until 03:01.
        raw = pt.load_rows(BUNDLED_DATA_DIR / "shahrekord_prayer_times_2026_raw.csv")[:3]
        row = pt.build_schedule(raw, timedelta(hours=11))[0]
        self.assertEqual((row["EveningBlockEnd_50"], row["BedTime_50"]), ("03:01", "03:01"))
        self.assertEqual((row["SleepDuration_50"], row["SleepDeficit_50"]), ("02:41", "08:41"))


class LibraryTests(unittest.TestCase):
    def test_reads_bundled_year(self):
        lib = pt.PrayerLibrary([BUNDLED_DATA_DIR])
        day = lib.day("shahrekord", date(2026, 1, 1))
        self.assertEqual((day.fajr, day.isha), (time(5, 42), time(18, 20)))
        self.assertEqual(len(lib.table("shahrekord", 2026)), 365)
        self.assertEqual(lib.years("shahrekord"), [2026])
        self.assertIsNone(lib.day("shahrekord", date(2030, 1, 1)))
        self.assertIsNone(lib.table("atlantis", 2026))

    def test_user_data_overrides_bundled(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = pt.YearFiles(Path(tmp), "shahrekord", 2026)
            pt.write_csv(
                [{**{k: "01:00" for k in pt.RAW_FIELDNAMES}, "Date": "01-01-2026", "Isha": "02:00"}],
                pt.RAW_FIELDNAMES, files.raw,
            )
            lib = pt.PrayerLibrary([Path(tmp), BUNDLED_DATA_DIR])
            self.assertEqual(lib.day("shahrekord", date(2026, 1, 1)).isha, time(2, 0))


class DownloadTests(unittest.TestCase):
    def test_download_writes_both_files_and_backs_up_old_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "data"
            loc = Location()
            noop = lambda *_: None
            orig_sleep = pt._time.sleep
            pt._time.sleep = noop
            try:
                first = pt.download_year(loc, 2027, directory, http_json=fake_api)
                self.assertEqual(first.days, 12)
                self.assertTrue(first.files.raw.is_file() and first.files.schedule.is_file())
                self.assertIsNone(first.backup)
                self.assertTrue(pt.csv_matches_header(first.files.schedule, pt.SCHEDULE_FIELDNAMES))
            finally:
                pt._time.sleep = orig_sleep

    def test_fetch_retries_then_fails_cleanly(self):
        calls = []

        def broken(url, params, timeout):
            calls.append(1)
            raise OSError("offline")

        with self.assertRaises(pt.FetchError):
            pt.fetch_year(2027, 0, 0, 7, http_json=broken, sleep=lambda s: None)
        self.assertEqual(len(calls), pt.REQUEST_RETRIES)


if __name__ == "__main__":
    unittest.main()
