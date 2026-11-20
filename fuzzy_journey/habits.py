"""A private habit calendar: habits you choose, each marked per day with how many times it happened.

A habit is one you want to **quit** (do less of) or one you want to **build** (do more of). The counting is
the same for both; only the words and colours differ: a quit habit speaks of days it happened and days
*without*, a build habit of days *done* and days *missed*. You add, rename, reorder and remove habits
yourself, so the page fits whatever you are working on.

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

QUIT = "quit"
BUILD = "build"
KINDS = (QUIT, BUILD)
KIND_LABELS = {QUIT: "Quit: something I want to do less", BUILD: "Build: something I want to do more"}

WEEK = 7
MONTH = 30
MAX_COUNT = 99
MAX_NAME = 40
MAX_HABITS = 24

#: A few ideas shown when adding a habit. Nothing is added until you choose.
SUGGESTIONS = (
    ("Exercise", BUILD), ("Reading", BUILD), ("Drinking water", BUILD), ("Prayer", BUILD),
    ("Smoking", QUIT), ("Sugar", QUIT), ("Social media", QUIT), ("Late nights", QUIT),
)


@dataclass
class Habit:
    """One habit being tracked. ``start`` only decides what the figures count; no day is ever erased."""

    name: str
    kind: str
    start: date
    id: int | None = None
    position: int = 0

    @property
    def quitting(self) -> bool:
        return self.kind == QUIT


def check_habit(name: str, kind: str) -> str | None:
    """Why a habit cannot be saved, or None when it is fine."""
    if kind not in KINDS:
        return "Choose whether you want to quit it or build it."
    if not name.strip():
        return "Give the habit a name."
    if len(name.strip()) > MAX_NAME:
        return f"Keep the name under {MAX_NAME} characters."
    return None


@dataclass(frozen=True)
class HabitStat:
    """What one habit did over a run of finished days."""

    days: int
    total: int  # times, all days together
    days_with: int  # days it happened on

    @property
    def clean_days(self) -> int:
        """Days it did not happen. For a habit being built these are the days missed."""
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


def describe(stat: HabitStat | None, wait: int, kind: str) -> str:
    """One line for a figure, or what must happen before there is one."""
    if stat is None:
        return f"Shown after {wait} more day{'s' if wait != 1 else ''} have passed."
    times = f"{stat.total} time{'s' if stat.total != 1 else ''}"
    if kind == QUIT:
        tail = f"happened on {stat.days_with} of {stat.days} days · {stat.clean_days} without"
    else:
        tail = f"done on {stat.days_with} of {stat.days} days · {stat.clean_days} missed"
    return f"{stat.average:.2f} a day · {times} · {tail}"
