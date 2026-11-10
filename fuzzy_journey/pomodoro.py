"""Pomodoro: how a day's work is cut into focus blocks, breaks and planning.

Pure rules, no GTK and no database. The work the day already has (see
:mod:`fuzzy_journey.rhythm`) is the window; this module lays a repeating
cycle of *focus, short break, ... long break* into it, keeps the last
half hour for planning, and says how much real focus is left for tasks.

Like everything else here it counts focus, not clock time: a call that
interrupts a block moves its end later and the focus stays whole. A manual
pause (a glass of water) does the same for everything after it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from .models import Sound
from .rhythm import Pause, finish_with_pauses

PLANNING_MINUTES = 30
#: A focus block shorter than this is not worth starting; the time stays free.
MIN_FOCUS_MINUTES = 10
#: Fill at most this share of a day's focus time with tasks, so overruns have room.
RECOMMENDED_SHARE = 0.9

FOCUS_RANGE = (5, 120)
SHORT_RANGE = (1, 30)
LONG_RANGE = (5, 90)
EVERY_RANGE = (2, 8)

#: A manual pause: (paused at, resumed at). ``None`` means still paused.
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


def build_schedule(
    work: Iterable[tuple[datetime, timedelta]],
    pauses: Sequence[Pause],
    settings: PomodoroSettings,
) -> Schedule:
    """Cut the day's work blocks ``(start, planned)`` into a schedule."""
    spans = sorted(((s, int(p.total_seconds() // 60)) for s, p in work if p > timedelta(0)))
    if not spans:
        return Schedule((), timedelta(0), settings.enabled)
    pauses = sorted(pauses, key=lambda p: p.span.start)
    planning: Segment | None = None

    if settings.planning_enabled:
        start, minutes = spans[-1]
        take = min(PLANNING_MINUTES, minutes)
        end = finish_with_pauses(start, timedelta(minutes=minutes), pauses)
        planning = Segment(SegmentKind.PLANNING, end - timedelta(minutes=take), end, take)
        spans[-1] = (start, minutes - take)

    segments: list[Segment] = []
    focus_total = 0
    if not settings.enabled:
        focus_total = sum(m for _s, m in spans)
    else:
        count = 0  # focus blocks since the last long break
        for start, minutes in spans:
            cursor, left = start, minutes
            while left >= MIN_FOCUS_MINUTES:
                length = min(settings.focus, left)
                begin = _after_pauses(cursor, pauses)
                cursor = finish_with_pauses(begin, timedelta(minutes=length), pauses)
                segments.append(Segment(SegmentKind.FOCUS, begin, cursor, length))
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
    return Schedule(tuple(segments), timedelta(minutes=focus_total), settings.enabled)


def _break_after(count: int, s: PomodoroSettings) -> tuple[SegmentKind, int] | None:
    """The break that follows the ``count``-th focus block, honouring each switch."""
    if s.long_enabled and count % s.long_every == 0:
        return SegmentKind.LONG, s.long
    if s.short_enabled:
        return SegmentKind.SHORT, s.short
    return None


# --------------------------------------------------------------------------
# Manual pauses
# --------------------------------------------------------------------------


def shifted(moment: datetime, pauses: Sequence[ManualPause], now: datetime | None = None) -> datetime | None:
    """``moment`` moved later by every manual pause that began before it.

    While a pause is still open its end is ``now`` (for display); without
    ``now`` the moment is unknown and ``None`` is returned (nothing rings).
    """
    for paused_at, resumed_at in sorted(pauses, key=lambda p: p[0]):
        if moment > paused_at:
            end = resumed_at or now
            if end is None:
                return None
            moment += max(timedelta(0), end - paused_at)
    return moment


def live_segments(schedule: Schedule, pauses: Sequence[ManualPause], now: datetime) -> tuple[Segment, ...]:
    """The schedule as it really runs, with manual pauses applied."""
    if not pauses:
        return schedule.segments
    out = []
    for seg in schedule.segments:
        start, end = shifted(seg.start, pauses, now), shifted(seg.end, pauses, now)
        out.append(Segment(seg.kind, start or seg.start, end or seg.end, seg.minutes))
    return tuple(out)


def current(segments: Iterable[Segment], now: datetime) -> Segment | None:
    return next((s for s in segments if s.start <= now < s.end), None)


def focus_number(segments: Sequence[Segment], seg: Segment) -> tuple[int, int]:
    """``(n, total)``: ``seg`` is the n-th of ``total`` focus blocks.

    ``seg`` must come from ``segments`` itself. After a manual pause the live segments are
    shifted, so it can not be matched against the unshifted schedule by its start time.
    """
    blocks = [s for s in segments if s.kind is SegmentKind.FOCUS]
    number = next((i for i, s in enumerate(blocks) if s is seg), 0) + 1
    return number, len(blocks)


# --------------------------------------------------------------------------
# Alarms
# --------------------------------------------------------------------------


def schedule_events(
    schedule: Schedule, pauses: Sequence[ManualPause], day: date, sound: Sound
):
    """One alarm at the start of every segment, and one when the last focus block ends.

    Returns :class:`fuzzy_journey.alarms.ScheduledEvent` objects. While a pause
    is open nothing after it is due, so nothing rings.
    """
    from .alarms import ScheduledEvent  # local: alarms imports the database, which imports this module

    events = []
    for index, seg in enumerate(schedule.segments):
        due = shifted(seg.start, pauses)
        if due is not None:
            title = f"{seg.title} · {seg.minutes} min"
            events.append(ScheduledEvent(f"pomo:{index}", title, due, sound, day, "Pomodoro"))
    last_focus = max((s for s in schedule.segments if s.kind is SegmentKind.FOCUS),
                     key=lambda s: s.end, default=None)
    if last_focus and schedule.planning is None:
        due = shifted(last_focus.end, pauses)
        if due is not None:
            events.append(ScheduledEvent("pomo:end", "Focus finished", due, sound, day, "Pomodoro"))
    return events
