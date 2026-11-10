"""Plain data objects shared by the database, the alarm service and the UI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import Enum
from pathlib import Path

from .rhythm import DayKind
from .timeutil import ALL_DAYS, parse_clock

# --------------------------------------------------------------------------
# Sounds
# --------------------------------------------------------------------------

SOUND_PRESETS = {
    "classic": "Classic",
    "gentle": "Gentle",
    "urgent": "Urgent",
    "digital": "Digital",
}


@dataclass(frozen=True)
class Sound:
    """How an alarm should sound: off, a built-in tone, or a personal file."""

    enabled: bool = True
    key: str = "classic"
    custom_path: str | None = None

    def describe(self) -> str:
        if not self.enabled:
            return "Silent"
        if self.custom_path:
            return Path(self.custom_path).name
        return SOUND_PRESETS.get(self.key, "Classic")


# --------------------------------------------------------------------------
# Reminders, activities, prayer alarms, day entries
# --------------------------------------------------------------------------


@dataclass
class Alarm:
    """A reminder: a time, plus either repeat weekdays or one specific date."""

    title: str
    time: str  # "HH:MM" or "HH:MM:SS"
    days_mask: int = ALL_DAYS
    one_shot_date: str | None = None
    sound: Sound = field(default_factory=Sound)
    enabled: bool = True
    last_fired_date: str | None = None
    id: int | None = None

    @property
    def clock(self) -> time:
        return parse_clock(self.time)

    @property
    def is_one_shot(self) -> bool:
        return bool(self.one_shot_date)


ACTIVITY_CATEGORIES = {
    "personal": "Personal",
    "work": "Work",
    "health": "Health",
    "call": "Call",
    "prayer": "Prayer",
    "wake": "Wake-up",
    "sleep": "Sleep",
}


@dataclass
class Activity:
    """A recurring block of the day: a call, the gym, a custom work shift, sleep."""

    title: str
    category: str
    start: str  # "HH:MM"
    end: str  # "HH:MM"
    days_mask: int = ALL_DAYS
    alarm_at_start: bool = False
    alarm_at_end: bool = False
    sound: Sound = field(default_factory=Sound)
    enabled: bool = True
    id: int | None = None

    @property
    def start_clock(self) -> time:
        return parse_clock(self.start)

    @property
    def end_clock(self) -> time:
        return parse_clock(self.end)

    @property
    def is_work(self) -> bool:
        return self.category.lower() == "work"

    @property
    def category_label(self) -> str:
        return ACTIVITY_CATEGORIES.get(self.category, self.category.title())


PRAYER_NAMES = ("Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha")


@dataclass
class PrayerAlarm:
    key: str
    enabled: bool = False
    offset_minutes: int = 0
    sound: Sound = field(default_factory=Sound)


@dataclass(frozen=True)
class DayEntry:
    day: date
    kind: DayKind
    note: str = ""
    start: time | None = None  # when a Recovered day really began
    overtime: int = 0  # minutes of night work, after Isha
    evening: int = 0  # minutes of optional evening work added to the day (not recommended)


@dataclass(frozen=True)
class DayProgress:
    """How much focus a day really had: the time the clock ran, not paused, not on a break."""

    day: date
    worked: timedelta
    capacity: timedelta  # the focus time the day offered
    steady: timedelta  # the focus time a Steady day would have offered
    block_minutes: int  # length of one focus block when it was recorded
    final: bool = False  # the day is over and the figure will not change

    @property
    def hours(self) -> float:
        return self.worked.total_seconds() / 3600

    @property
    def percent(self) -> float | None:
        """Share of a Steady day's focus time, or ``None`` when there is nothing to compare with."""
        if self.steady <= timedelta(0):
            return None
        return 100 * self.worked / self.steady

    @property
    def blocks(self) -> float:
        """Focus blocks, with decimals: 2.5 is two and a half blocks of focus."""
        return self.worked.total_seconds() / 60 / max(1, self.block_minutes)


PROGRESS_UNITS = {"hours": "Hours", "percent": "% of a Steady day", "blocks": "Focus blocks"}


def describe_progress(progress: DayProgress, units: Iterable[str]) -> str:
    """One line for a day, in the units the person chose: "2h 40m · 71% · 3.2 blocks"."""
    from .timeutil import human_duration  # local: timeutil is a leaf, but keep models import-light

    parts = []
    for unit in units:
        if unit == "hours":
            parts.append(human_duration(progress.worked) if progress.worked >= timedelta(minutes=1) else "0m")
        elif unit == "percent":
            parts.append("—" if progress.percent is None else f"{progress.percent:.0f}%")
        elif unit == "blocks":
            parts.append(f"{progress.blocks:.1f} block{'s' if round(progress.blocks, 1) != 1 else ''}")
    return " · ".join(parts)


@dataclass(frozen=True)
class FiredEvent:
    title: str
    fired_at: str


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------

#: AlAdhan calculation methods (https://aladhan.com/calculation-methods).
CALCULATION_METHODS = {
    0: "Shia Ithna-Ashari, Leva Institute, Qum",
    1: "University of Islamic Sciences, Karachi",
    2: "Islamic Society of North America (ISNA)",
    3: "Muslim World League",
    4: "Umm Al-Qura University, Makkah",
    5: "Egyptian General Authority of Survey",
    7: "Institute of Geophysics, University of Tehran",
    8: "Gulf Region",
    9: "Kuwait",
    10: "Qatar",
    11: "Majlis Ugama Islam Singapura",
    12: "Union Organisation Islamique de France",
    13: "Diyanet İşleri Başkanlığı, Turkey",
}


@dataclass(frozen=True)
class Location:
    name: str = "Shahrekord"
    latitude: float = 32.3261
    longitude: float = 50.8572
    method: int = 7

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def method_name(self) -> str:
        return CALCULATION_METHODS.get(self.method, f"Method {self.method}")


def slugify(name: str) -> str:
    """Lowercase ASCII-ish file slug: ``"New York"`` -> ``"new-york"``."""
    keep = [c.lower() if c.isalnum() else "-" for c in name.strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "home"


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


class TaskStatus(Enum):
    """Where a task stands. A task starts ``UNSET`` and the user settles it."""

    UNSET = "unset"
    DONE = "done"
    CANCELLED = "cancelled"  # never needs doing
    CARRIED = "carried"  # not done in time; a copy waits on the next day

    @property
    def label(self) -> str:
        return {"unset": "Not set", "done": "Done", "cancelled": "Cancelled",
                "carried": "Moved on"}[self.value]


TASK_LEVELS = {1: "High", 2: "Normal", 3: "Low"}


@dataclass
class Task:
    """Something to do on one day. Tasks belong to their day; only a status moves them on."""

    title: str
    minutes: int
    day: date
    level: int = 2  # 1 High, 2 Normal, 3 Low; used by the "by importance" order
    position: int = 0  # used by the "my order" order
    status: TaskStatus = TaskStatus.UNSET
    origin_id: int | None = None  # the task this one was carried over from
    id: int | None = None
    kind: str = "task"  # "prayer" for the five daily prayers: zero length, never focus time

    @property
    def is_prayer(self) -> bool:
        return self.kind == "prayer"

    @property
    def level_label(self) -> str:
        return TASK_LEVELS.get(self.level, "Normal")
