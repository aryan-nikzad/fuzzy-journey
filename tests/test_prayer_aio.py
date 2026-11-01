from __future__ import annotations

import sys
import types
import unittest

# prayer_aio uses requests only for online fetching. These tests exercise
# its local schedule calculations and must remain fully offline.
try:
    import requests  # noqa: F401
except ImportError:
    requests_stub = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    requests_stub.RequestException = RequestException
    requests_stub.get = lambda *args, **kwargs: (_ for _ in ()).throw(
        RequestException("Network access is not used by these tests")
    )
    sys.modules["requests"] = requests_stub

from prayer_aio import build_schedule, calculate_work_blocks, parse_clock_time
from datetime import datetime, time


class EveningStartTests(unittest.TestCase):
    def _raw_rows(self):
        template = {
            "Fajr": "05:42",
            "Sunrise": "07:08",
            "Dhuhr": "12:10",
            "Asr": "14:54",
            "Sunset": "17:12",
            "Maghrib": "17:32",
            "Isha": "18:20",
            "Imsak": "05:32",
            "Midnight": "00:10",
            "FirstThirdOfNight": "21:51",
            "LastThirdOfNight": "02:29",
        }
        first = {"Date": "01-01-2026", **template}
        second = {"Date": "02-01-2026", **template}
        return [first, second]

    def test_evening_start_is_configurable_and_preserves_work_overflow(self):
        rows = build_schedule(self._raw_rows(), evening_start="19:30")
        self.assertEqual(rows[0]["EveningBlockStart_75"], "19:30")
        self.assertEqual(rows[0]["EveningBlockEnd_75"], "20:40")
        self.assertEqual(rows[0]["BedTime_75"], "20:40")

    def test_empty_evening_block_has_equal_times_at_selected_start(self):
        rows = build_schedule(self._raw_rows(), evening_start="19:30")
        self.assertEqual(rows[0]["EveningBlockStart_50"], "19:30")
        self.assertEqual(rows[0]["EveningBlockEnd_50"], "19:30")
        self.assertEqual(rows[0]["WorkOverflow_50"], "00:00")

    def test_evening_start_defaults_to_1800(self):
        rows = build_schedule(self._raw_rows())
        self.assertEqual(rows[0]["EveningBlockStart_75"], "18:00")
        self.assertEqual(rows[0]["EveningBlockEnd_75"], "19:10")

    def test_evening_start_parser_rejects_invalid_clock_values(self):
        self.assertEqual(parse_clock_time("19:30"), time(19, 30))
        with self.assertRaises(Exception):
            parse_clock_time("25:00")


if __name__ == "__main__":
    unittest.main()
