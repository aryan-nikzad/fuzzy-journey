"""A private habit calendar: per day, whether a habit happened and how many times.

Each habit is counted on its own, from its own start date. The start date only decides *what is
counted*: days before it keep their marks and can still be edited, they are just left out of the
figures. Averages are never shown early: a weekly figure needs seven finished days since the start
and a monthly one thirty, so a number built from two days cannot mislead. Today is never part of a
figure, because it is not finished; it is counted tomorrow.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

#: The two habits, as stored: the key, then how it is named on screen.
HABITS = (("masturbation", "Masturbation"), ("porn", "Porn"))
KEYS = tuple(key for key, _name in HABITS)

WEEK = 7
MONTH = 30
MAX_COUNT = 99


@dataclass(frozen=True)
class HabitStat:
    """What one habit did over a run of finished days."""

    days: int
    total: int  # times, all days together
    days_with: int  # days it happened on

    @property
    def clean_days(self) -> int:
        return self.days - self.days_with

    @property
    def average(self) -> float:
        """Times per day."""
        return self.total / self.days if self.days else 0.0


def days_passed(start: date, today: date) -> int:
    """Finished days since ``start``: today is not finished, so it is not one of them."""
    return max(0, (today - start).days)


def _stat(counts: Mapping[date, int], first: date, last: date) -> HabitStat:
    days = (last - first).days + 1
    seen = [counts.get(first + timedelta(days=i), 0) for i in range(days)]
    return HabitStat(days, sum(seen), sum(1 for n in seen if n > 0))


def window_stat(counts: Mapping[date, int], start: date, today: date, length: int) -> HabitStat | None:
    """The last ``length`` finished days, or ``None`` until that many have passed since ``start``."""
    if days_passed(start, today) < length:
        return None
    return _stat(counts, today - timedelta(days=length), today - timedelta(days=1))


def since_start(counts: Mapping[date, int], start: date, today: date) -> HabitStat | None:
    """Every finished day since ``start``, or ``None`` before the first one has passed."""
    passed = days_passed(start, today)
    return _stat(counts, start, today - timedelta(days=1)) if passed else None


def days_left(start: date, today: date, length: int) -> int:
    """How many more days must pass before the ``length``-day figure appears."""
    return max(0, length - days_passed(start, today))


def clamp(count: int) -> int:
    return min(MAX_COUNT, max(0, int(count)))
