"""Pomodoro: how a day's work is cut into focus blocks, breaks and planning.

Pure rules, no GTK and no database. The work the day already has (see
:mod:`fuzzy_journey.rhythm`) is the window; this module lays a repeating
cycle of *focus, short break, ... long break* into it, keeps the last
half hour for planning, and says how much real focus is left for tasks.

Like everything else here it counts focus, not clock time: a call that
interrupts a block moves its end later and the focus stays whole. A manual
pause (a glass of water) is just another pause, so it does the same, and the
schedule is always laid out from the real pauses rather than patched afterwards.

Nothing runs past bedtime: when pauses push the work too far, the schedule is
cut short there (planning keeps its place at the end) and says how much was cut.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from .models import Sound
from .rhythm import Pause, finish_with_pauses, productive_between

PLANNING_MINUTES = 30
#: A focus block shorter than this is not worth starting; the time stays free.
MIN_FOCUS_MINUTES = 10
#: Fill at most this share of a day's focus time with tasks, so overruns have room.
RECOMMENDED_SHARE = 0.9

FOCUS_RANGE = (5, 120)
SHORT_RANGE = (1, 30)
LONG_RANGE = (5, 90)
EVERY_RANGE = (2, 8)

#: A manual pause as stored: (paused at, resumed at). ``None`` means still paused.
ManualPause = tuple[datetime, datetime | None]


class SegmentKind(Enum):
    FOCUS = "focus"
    SHORT = "short"
    LONG = "long"
    PLANNING = "planning"

    @property
    def label(self) -> str:
        return {"focus": "Focus", "short": "Short break", "long": "Long break",
                "planning": "Planning"}[self.value]


@dataclass(frozen=True)
class PomodoroSettings:
    enabled: bool = True
    focus: int = 50
    short_enabled: bool = True
    short: int = 10
    long_enabled: bool = True
    long: int = 30
    long_every: int = 3  # focus blocks before a long break
    planning_enabled: bool = True


@dataclass(frozen=True)
class Segment:
    kind: SegmentKind
    start: datetime
    end: datetime
    minutes: int  # focus/break length, before any interruption moved the end

    @property
    def title(self) -> str:
        return self.kind.label

    @property
    def is_break(self) -> bool:
        return self.kind in (SegmentKind.SHORT, SegmentKind.LONG)


@dataclass(frozen=True)
class Schedule:
    """The day's segments in order, and the focus time they leave for tasks."""

    segments: tuple[Segment, ...]
    focus: timedelta
    pomodoro: bool
    #: The stretches (start, end) in which focus happens, before any pause is taken out.
    windows: tuple[tuple[datetime, datetime], ...] = ()
    #: Focus that did not fit before the deadline (bedtime) and was left out.
    cut: timedelta = timedelta(0)

    @property
    def planning(self) -> Segment | None:
        return next((s for s in self.segments if s.kind is SegmentKind.PLANNING), None)

    @property
    def focus_minutes(self) -> int:
        return int(self.focus.total_seconds() // 60)

    @property
    def recommended_minutes(self) -> int:
        return recommended(self.focus_minutes)


def recommended(focus_minutes: int) -> int:
    """90% of the focus time, to the nearest five minutes below."""
    return int(focus_minutes * RECOMMENDED_SHARE) // 5 * 5


# --------------------------------------------------------------------------
# Laying out the day
# --------------------------------------------------------------------------


def _after_pauses(moment: datetime, pauses: Sequence[Pause]) -> datetime:
    for pause in pauses:
        if pause.span.start <= moment < pause.span.end:
            moment = pause.span.end
    return moment


def _start_for(end: datetime, minutes: int, pauses: Sequence[Pause]) -> datetime:
    """The moment from which ``minutes`` of un-paused time lead up to ``end``."""
    need, cursor = timedelta(minutes=minutes), end
    for pause in sorted(pauses, key=lambda p: p.span.end, reverse=True):
        if pause.span.start >= cursor:
            continue
        if pause.span.end < cursor:
            gap = cursor - pause.span.end
            if gap >= need:
                return cursor - need
            need -= gap
        cursor = min(cursor, pause.span.start)
    return cursor - need


def build_schedule(
    work: Iterable[tuple[datetime, timedelta]],
    pauses: Sequence[Pause],
    settings: PomodoroSettings,
    deadline: datetime | None = None,
) -> Schedule:
    """Cut the day's work blocks ``(start, planned)`` into a schedule.

    ``deadline`` is bedtime. Work that pauses would push past it is cut, so the focus blocks
    stop in time and planning still happens before the night.
    """
    pauses = sorted(pauses, key=lambda p: p.span.start)
    spans: list[tuple[datetime, int]] = []
    cut = timedelta(0)
    for start, planned in work:
        if planned <= timedelta(0):
            continue
        minutes = int(planned.total_seconds() // 60)
        if deadline is not None and finish_with_pauses(start, planned, pauses) > deadline:
            fits = int(productive_between(start, deadline, pauses).total_seconds() // 60)
            cut += timedelta(minutes=max(0, minutes - fits))
            minutes = min(minutes, fits)
        if minutes > 0:
            spans.append((start, minutes))
    spans.sort()
    if not spans:
        return Schedule((), timedelta(0), settings.enabled, (), cut)
    planning: Segment | None = None

    if settings.planning_enabled:
        start, minutes = spans[-1]
        take = min(PLANNING_MINUTES, minutes)
        end = finish_with_pauses(start, timedelta(minutes=minutes), pauses)
        planning = Segment(SegmentKind.PLANNING, _start_for(end, take, pauses), end, take)
        spans[-1] = (start, minutes - take)

    segments: list[Segment] = []
    windows: list[tuple[datetime, datetime]] = []
    focus_total = 0
    if not settings.enabled:
        focus_total = sum(m for _s, m in spans)
        windows = [(s, finish_with_pauses(s, timedelta(minutes=m), pauses)) for s, m in spans]
    else:
        count = 0  # focus blocks since the last long break
        for start, minutes in spans:
            cursor, left = start, minutes
            while left >= MIN_FOCUS_MINUTES:
                length = min(settings.focus, left)
                begin = _after_pauses(cursor, pauses)
                cursor = finish_with_pauses(begin, timedelta(minutes=length), pauses)
                segments.append(Segment(SegmentKind.FOCUS, begin, cursor, length))
                windows.append((begin, cursor))
                focus_total += length
                left -= length
                count += 1
                rest = _break_after(count, settings)
                if rest is None:
                    continue  # no break is due: the next block follows straight away
                if left - rest[1] < MIN_FOCUS_MINUTES:
                    break  # a break is due but no useful block would follow it: the cycle ends here
                kind, length = rest
                begin = _after_pauses(cursor, pauses)
                cursor = finish_with_pauses(begin, timedelta(minutes=length), pauses)
                segments.append(Segment(kind, begin, cursor, length))
                left -= length
                if kind is SegmentKind.LONG:
                    count = 0

    if planning:
        segments.append(planning)
    return Schedule(tuple(segments), timedelta(minutes=focus_total), settings.enabled, tuple(windows), cut)


def _break_after(count: int, s: PomodoroSettings) -> tuple[SegmentKind, int] | None:
    """The break that follows the ``count``-th focus block, honouring each switch."""
    if s.long_enabled and count % s.long_every == 0:
        return SegmentKind.LONG, s.long
    if s.short_enabled:
        return SegmentKind.SHORT, s.short
    return None


# --------------------------------------------------------------------------
# The clock now
# --------------------------------------------------------------------------


def current(segments: Iterable[Segment], now: datetime) -> Segment | None:
    return next((s for s in segments if s.start <= now < s.end), None)


def focus_number(segments: Sequence[Segment], seg: Segment) -> tuple[int, int]:
    """``(n, total)``: ``seg`` is the n-th of ``total`` focus blocks."""
    blocks = [s for s in segments if s.kind is SegmentKind.FOCUS]
    number = next((i for i, s in enumerate(blocks) if s is seg), 0) + 1
    return number, len(blocks)


def left_in(seg: Segment, pauses: Sequence[Pause], now: datetime) -> timedelta:
    """Time of ``seg`` still to be lived, outside every pause. Frozen while a pause lasts."""
    return productive_between(max(now, seg.start), seg.end, pauses)


def focus_worked(schedule: Schedule, pauses: Sequence[Pause], now: datetime) -> timedelta:
    """Focus the clock has really run up to ``now``: no pauses, no breaks, no planning."""
    total = timedelta(0)
    for start, end in schedule.windows:
        total += productive_between(start, min(end, now), pauses)
    return total


def closing_moment(schedule: Schedule | None, work_end: datetime | None) -> datetime | None:
    """When the day's work is over and its tasks should be settled.

    That is when planning begins (planning *is* the settling slot) or, with planning off,
    when the last block of work ends.
    """
    if schedule is not None and schedule.planning is not None:
        return schedule.planning.start
    return work_end


# --------------------------------------------------------------------------
# Alarms
# --------------------------------------------------------------------------


def schedule_events(schedule: Schedule, day: date, sound: Sound, hold_after: datetime | None = None):
    """One alarm at the start of every segment, and one when the last focus block ends.

    Returns :class:`fuzzy_journey.alarms.ScheduledEvent` objects. ``hold_after`` is the start of
    a pause the user has not ended: nothing at or after it is due, so nothing rings.
    """
    from .alarms import ScheduledEvent  # local: alarms imports the database, which imports this module

    def held(moment: datetime) -> bool:
        return hold_after is not None and moment >= hold_after

    events = []
    for index, seg in enumerate(schedule.segments):
        if not held(seg.start):
            title = f"{seg.title} · {seg.minutes} min"
            events.append(ScheduledEvent(f"pomo:{index}", title, seg.start, sound, day, "Pomodoro"))
    last_focus = max((s for s in schedule.segments if s.kind is SegmentKind.FOCUS),
                     key=lambda s: s.end, default=None)
    if last_focus and schedule.planning is None and not held(last_focus.end):
        events.append(ScheduledEvent("pomo:end", "Focus finished", last_focus.end, sound, day, "Pomodoro"))
    return events
