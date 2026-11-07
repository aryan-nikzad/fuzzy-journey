"""Task rules: order, load against focus time, and what a status means.

Pure functions, no GTK. Saving and carrying tasks over lives in
:class:`fuzzy_journey.database.Database`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from .models import Task, TaskStatus
from .pomodoro import recommended
from .timeutil import human_duration

ORDER_SEQUENCE = "sequence"  # the user puts tasks in the order to do them
ORDER_LEVEL = "level"  # each task has an importance; the most important comes first
ORDER_MODES = (ORDER_SEQUENCE, ORDER_LEVEL)

MIN_MINUTES, MAX_MINUTES, STEP_MINUTES = 5, 360, 5


def in_order(tasks: Iterable[Task], mode: str) -> list[Task]:
    """Tasks as they should be done. Settled tasks sink below open ones."""
    def key(t: Task):
        settled = t.status is not TaskStatus.UNSET
        level = t.level if mode == ORDER_LEVEL else 0
        return (settled, level, t.position, t.id or 0)

    return sorted(tasks, key=key)


@dataclass(frozen=True)
class Load:
    """How much of a day's focus time its tasks use."""

    planned: int  # minutes of tasks that still count (everything except cancelled)
    focus: int  # minutes of focus the day has

    @property
    def left(self) -> int:
        return max(0, self.focus - self.planned)

    @property
    def fraction(self) -> float:
        return min(1.0, self.planned / self.focus) if self.focus else 0.0

    @property
    def over_recommended(self) -> bool:
        return self.planned > recommended(self.focus)

    @property
    def over(self) -> bool:
        return self.planned > self.focus


def load(tasks: Iterable[Task], focus_minutes: int) -> Load:
    planned = sum(t.minutes for t in tasks if t.status is not TaskStatus.CANCELLED)
    return Load(planned, focus_minutes)


def check_task(title: str, minutes: int, others: Iterable[Task], focus_minutes: int) -> str | None:
    """Why this task cannot be saved, or ``None``. ``others`` excludes the task being edited."""
    if not title.strip():
        return "Give the task a title."
    if not MIN_MINUTES <= minutes <= MAX_MINUTES or minutes % STEP_MINUTES:
        return f"Choose a length from {MIN_MINUTES} to {MAX_MINUTES} minutes, in steps of {STEP_MINUTES}."
    if focus_minutes <= 0:
        return "This day has no focus time to plan."
    left = focus_minutes - load(others, focus_minutes).planned
    if minutes > left:
        if left <= 0:
            return "This day’s focus time is already full."
        return f"Only {human_duration_min(left)} of focus time is left on this day."
    return None


def human_duration_min(minutes: int) -> str:
    return human_duration(timedelta(minutes=minutes))
