from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fuzzy_journey.database import Database
from fuzzy_journey.models import Activity


class DbTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Database(Path(self._tmp.name) / "test.sqlite3")


def activity(title, start, end, category="personal", mask=127, **kw) -> Activity:
    return Activity(title=title, category=category, start=start, end=end, days_mask=mask, **kw)
