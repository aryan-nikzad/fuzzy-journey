"""The philosophy of Fuzzy Journey, as arithmetic.

This module is pure: no GTK, no database, no files, no clock. Give it times
and it gives back plans, so every rule can be tested exactly.

The four ideas (see :mod:`fuzzy_journey.philosophy`) map to code like this:

1. **The day is given.**   :func:`plan_day` takes Fajr as the wake time and
   Isha as the end of the day. Nothing else defines the day.
2. **Work a share.**       :class:`DayKind` holds the share (50% or 75%);
   :func:`calculate_work_blocks` fills the morning up to 14:00 first and
   lets only the overflow spill into the evening.
3. **Bank the rest.**      :func:`summarize_bank` turns day kinds into a
   balance: Push earns half a day, Rest spends one, and debt is allowed.
4. **Protect the night.**  :func:`plan_day` measures sleep from bedtime to
   the next Fajr and reports ``sleep_lost`` against the Isha-to-Fajr night.

The two practices live here as well: :func:`finish_with_pauses` and
:func:`work_progress` count focused time, so an interruption moves the finish
later instead of eating the work.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from math import ceil, floor
from typing import TYPE_CHECKING

from .timeutil import mask_includes, span_after

if TYPE_CHECKING:  # pragma: no cover
    from .models import Activity

# --------------------------------------------------------------------------
# Constants of the rhythm
# --------------------------------------------------------------------------

#: The morning block may not run past this time; the afternoon belongs to you.
NOON_LIMIT = time(14, 0)
#: Where evening work begins by default, and the earliest it may be set.
DEFAULT_EVENING_START = time(18, 0)
MIN_EVENING_START = NOON_LIMIT


# --------------------------------------------------------------------------
# Day kinds
# --------------------------------------------------------------------------


class DayKind(Enum):
    """How much of the day work gets, and what that does to the bank."""

    STEADY = "50"
    PUSH = "75"
    REST = "off"
    #: A Steady day that began late: half of the time you are awake, afternoon allowed.
    #: Stored as a Steady entry with a start time, so older versions still read it.
    RECOVERED = "recovered"

    @property
    def share(self) -> float:
        return {DayKind.STEADY: 0.50, DayKind.PUSH: 0.75, DayKind.REST: 0.0, DayKind.RECOVERED: 0.50}[self]

    @property
    def bank_delta(self) -> float:
        """Days added to (or taken from) the bank by one day of this kind."""
        return {DayKind.STEADY: 0.0, DayKind.PUSH: 0.5, DayKind.REST: -1.0, DayKind.RECOVERED: 0.0}[self]

    @property
    def label(self) -> str:
        return {DayKind.STEADY: "Steady", DayKind.PUSH: "Push", DayKind.REST: "Rest", DayKind.RECOVERED: "Recovered"}[self]

    @property
    def percent(self) -> str:
        return {DayKind.STEADY: "50%", DayKind.PUSH: "75%", DayKind.REST: "Rest day", DayKind.RECOVERED: "50% from waking"}[self]

    @property
    def blurb(self) -> str:
        return {
            DayKind.STEADY: "Half the day for work. Neutral for the bank.",
            DayKind.PUSH: "Three quarters of the day for work. Banks half a day.",
            DayKind.REST: "No work today. Spends one day from the bank.",
            DayKind.RECOVERED: "You woke late. Half of the time you are awake, afternoon included. Neutral for the bank.",
        }[self]

    @classmethod
    def from_code(cls, code: str | None, default: DayKind | None = None) -> DayKind:
        for kind in cls:
            if kind.value == code:
                return kind
        return default if default is not None else cls.STEADY


# --------------------------------------------------------------------------
# Time bank
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BankSummary:
    start: date
    through: date
    push_days: int
    rest_days: int
    steady_days: int
    earned: float
    spent: float
    balance: float

    @property
    def in_debt(self) -> bool:
        return self.balance < 0

    @property
    def whole_rest_days(self) -> int:
        """Rest days you can take right now without going into debt."""
        return max(0, floor(self.balance))

    @property
    def push_days_to_next_whole_day(self) -> int:
        """Push days needed to reach the next whole day (or to reach zero when in debt)."""
        target = floor(self.balance) + 1 if self.balance >= 0 else 0
        needed = ceil(round((target - self.balance) / DayKind.PUSH.bank_delta, 6))
        return max(0, needed)


def summarize_bank(
    entries: Mapping[date, DayKind],
    start: date,
    today: date,
) -> BankSummary:
    """Count only days from ``start`` through ``today``.

    Unclassified days count as Steady. Days before the baseline and in the
    future are ignored, so the bank always starts from zero.
    """
    counted = [kind for day, kind in entries.items() if start <= day <= today]
    push = sum(1 for kind in counted if kind is DayKind.PUSH)
    rest = sum(1 for kind in counted if kind is DayKind.REST)
    elapsed = max(0, (today - start).days + 1)
    earned = push * DayKind.PUSH.bank_delta
    spent = rest * -DayKind.REST.bank_delta
    return BankSummary(
        start=start,
        through=today,
        push_days=push,
        rest_days=rest,
        steady_days=max(0, elapsed - push - rest),
        earned=earned,
        spent=spent,
        balance=earned - spent,
    )


# --------------------------------------------------------------------------
# Work blocks
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkBlocks:
    """A work target split into a morning block and an evening overflow."""

    total: timedelta
    remain: timedelta
    block1_start: datetime
    block1_end: datetime
    block2_start: datetime
    block2_end: datetime


def calculate_work_blocks(
    fajr: datetime,
    isha: datetime,
    percentage: float,
    flex: timedelta = timedelta(0),
    evening_start: time | str = DEFAULT_EVENING_START,
) -> WorkBlocks:
    """Split ``percentage`` of the Fajr-to-Isha window into two blocks.

    ``flex`` is extra work added on top of that target and allocated by the
    same rule, so it lands in the morning while there is room before 14:00
    and spills into the evening otherwise::

        Block 1: Fajr -> 14:00   (as much of the target as fits)
        Block 2: evening_start -> onward (whatever did not fit)
    """
    total_window = isha - fajr
    if total_window.total_seconds() < 0:
        total_window += timedelta(days=1)

    target = total_window * percentage + flex

    limit = fajr.replace(hour=NOON_LIMIT.hour, minute=NOON_LIMIT.minute, second=0, microsecond=0)
    if limit < fajr:
        limit += timedelta(days=1)
    morning_room = limit - fajr

    morning = min(target, morning_room)
    overflow = target - morning

    if isinstance(evening_start, str):
        evening_start = parse_evening_start(evening_start)
    block2_start = fajr.replace(
        hour=evening_start.hour, minute=evening_start.minute, second=0, microsecond=0
    )
    if block2_start < fajr:
        block2_start += timedelta(days=1)

    return WorkBlocks(
        total=target,
        remain=overflow,
        block1_start=fajr,
        block1_end=fajr + morning,
        block2_start=block2_start,
        block2_end=block2_start + overflow,
    )


def parse_evening_start(value: str) -> time:
    """Validate an evening-work start: a 24-hour time at or after 14:00."""
    try:
        parsed = datetime.strptime(str(value).strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"expected a valid 24-hour HH:MM time, got: {value!r}") from exc
    if parsed < MIN_EVENING_START:
        raise ValueError(f"evening work must start at or after 14:00, got: {value!r}")
    return parsed


# --------------------------------------------------------------------------
# Planning a whole day
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True)
class DayPlan:
    """Everything the rhythm says about one day, before personal activities."""

    day: date
    kind: DayKind
    wake: datetime
    bedtime: datetime
    next_wake: datetime
    target: timedelta
    morning: Span | None
    evening: Span | None
    free: Span | None
    sleep: timedelta
    sleep_lost: timedelta
    overtime: Span | None = None  # night work after Isha: not recommended, and it costs sleep

    @property
    def blocks(self) -> tuple[Span, ...]:
        return tuple(b for b in (self.morning, self.evening, self.overtime) if b is not None)


#: Night work (after Isha) is chosen in steps of half an hour, from one hour to four.
OVERTIME_RANGE = (60, 240)
OVERTIME_STEP = 30
#: Optional evening work, per day: range and step in minutes.
EVENING_RANGE = (30, 240)
EVENING_STEP = 30

#: A recovered day needs at least this long between its start and Isha.
MIN_RECOVERED_WINDOW = timedelta(hours=1)


def recovered_start(fajr_at: datetime, isha_at: datetime, start: time | None) -> datetime:
    """When a recovered day begins: ``start``, kept between Fajr and an hour before Isha."""
    if start is None:
        return fajr_at
    moment = datetime.combine(fajr_at.date(), start)
    return min(max(moment, fajr_at), isha_at - MIN_RECOVERED_WINDOW)


def check_recovered_start(fajr: time, isha: time, start: time) -> str | None:
    """Why ``start`` cannot begin a recovered day, or ``None``."""
    if start <= fajr:
        return f"That is before Fajr ({fajr:%H:%M}). The day already starts then."
    if datetime.combine(date.min, isha) - datetime.combine(date.min, start) < MIN_RECOVERED_WINDOW:
        return f"Too close to Isha ({isha:%H:%M}). There would be under an hour left to work."
    return None


def _whole_minutes(value: timedelta) -> timedelta:
    return timedelta(minutes=int(value.total_seconds() // 60))


def plan_day(
    day: date,
    kind: DayKind,
    *,
    fajr: time,
    isha: time,
    next_fajr: time | None = None,
    evening_start: time = DEFAULT_EVENING_START,
    flex: timedelta = timedelta(0),
    start: time | None = None,
    overtime: timedelta = timedelta(0),
    evening_extra: timedelta = timedelta(0),
) -> DayPlan:
    """Plan one day from its Fajr and Isha.

    ``next_fajr`` is tomorrow's Fajr. When it is unknown (last day of a
    downloaded year) tomorrow is assumed to start at the same time.

    ``start`` is only used by a *Recovered* day: the moment the day really began.
    Work is then half of the time from ``start`` to Isha, begins at ``start`` and
    may run into the afternoon, so there is no 14:00 limit and no evening block.

    ``evening_extra`` is an optional evening block for any working day (not recommended): it
    begins at ``evening_start`` (or when the last block ends, if later) and lengthens the
    evening block when the day already has one. Like all evening work it only pushes bedtime
    when it runs past Isha, and ``sleep_lost`` shows the price.

    ``overtime`` is work added after the last prayer, at night. It begins at Isha
    (or when the last block ends, if later), pushes bedtime out, and is paid for
    in sleep, which ``sleep_lost`` shows. Rest days have none.
    """
    fajr_at = datetime.combine(day, fajr)
    isha_at = datetime.combine(day, isha)
    if isha_at <= fajr_at:
        isha_at += timedelta(days=1)
    next_fajr_at = datetime.combine(day + timedelta(days=1), next_fajr or fajr)

    wake_at = fajr_at
    if kind is DayKind.REST:
        target = timedelta(0)
        morning = evening = None
    elif kind is DayKind.RECOVERED:
        wake_at = recovered_start(fajr_at, isha_at, start)
        target = _whole_minutes((isha_at - wake_at) * kind.share + flex)
        morning = Span(wake_at, wake_at + target) if target > timedelta(0) else None
        evening = None
    else:
        blocks = calculate_work_blocks(fajr_at, isha_at, kind.share, flex, evening_start)
        # Whole minutes throughout: what the clock shows is what the arithmetic used.
        target = _whole_minutes(blocks.total)
        overflow = _whole_minutes(blocks.remain)
        morning_end = blocks.block1_end.replace(second=0, microsecond=0)
        morning = Span(blocks.block1_start, morning_end) if morning_end > blocks.block1_start else None
        evening = Span(blocks.block2_start, blocks.block2_start + overflow) if overflow > timedelta(0) else None

    extra = _whole_minutes(evening_extra)
    if kind is not DayKind.REST and extra > timedelta(0):
        if evening:
            evening = Span(evening.start, evening.end + extra)
        else:
            begin = datetime.combine(day, evening_start)
            if morning:
                begin = max(begin, morning.end)
            evening = Span(begin, begin + extra)

    # Evening work is the last resort: it only pushes bedtime when it runs past Isha.
    last_end = evening.end if evening else (morning.end if kind is DayKind.RECOVERED and morning else None)
    late = None  # night work, after the last prayer
    if kind is not DayKind.REST and overtime > timedelta(0):
        begin = max(isha_at, last_end or isha_at)
        late = Span(begin, begin + _whole_minutes(overtime))
    bedtime = max(late.end if late else (last_end or isha_at), isha_at)

    free_start = morning.end if morning else wake_at
    free_end = evening.start if evening else (late.start if late else bedtime)
    free = Span(free_start, free_end) if free_end > free_start else None

    night = next_fajr_at - isha_at
    sleep = max(timedelta(0), next_fajr_at - bedtime)
    sleep_lost = max(timedelta(0), night - sleep)

    return DayPlan(
        day=day,
        kind=kind,
        wake=wake_at,
        bedtime=bedtime,
        next_wake=next_fajr_at,
        target=target,
        morning=morning,
        evening=evening,
        free=free,
        sleep=sleep,
        sleep_lost=sleep_lost,
        overtime=late,
    )


# --------------------------------------------------------------------------
# The work clock: counting focus, not clock time
# --------------------------------------------------------------------------


class WorkStatus(Enum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"


#: Title of a pause the user made with the Pause button (an activity such as the gym has its own).
MANUAL_PAUSE_TITLE = "your pause"


@dataclass(frozen=True)
class Pause:
    span: Span
    title: str
    #: Made with the Pause button (and nothing else is pausing at the same time).
    manual: bool = False
    #: The user has not resumed yet. ``span.end`` is then "now", or later if an activity overlaps.
    open: bool = False


@dataclass(frozen=True)
class WorkProgress:
    status: WorkStatus
    start: datetime
    end: datetime
    planned: timedelta
    remaining: timedelta
    pause: Pause | None = None
    #: Focus that no longer fits before bedtime. ``planned`` already excludes it.
    cut: timedelta = timedelta(0)

    @property
    def done(self) -> timedelta:
        return self.planned - self.remaining

    @property
    def fraction(self) -> float:
        if self.planned <= timedelta(0):
            return 0.0
        return min(1.0, max(0.0, self.done / self.planned))


def merge_pauses(raw: Iterable[Pause]) -> list[Pause]:
    """Sort pauses and merge every overlap into one.

    Where an activity and a manual pause overlap, the merged pause keeps the activity's
    name (it is what the person is actually doing); it stays *open* while the manual pause is.
    """
    merged: list[Pause] = []
    for pause in sorted(raw, key=lambda p: p.span.start):
        if not merged or pause.span.start > merged[-1].span.end:
            merged.append(pause)
            continue
        last = merged[-1]
        if last.manual and not pause.manual:
            title = pause.title
        elif pause.manual and not last.manual or last.title == pause.title:
            title = last.title
        else:
            title = "Other activity"
        merged[-1] = Pause(
            Span(last.span.start, max(last.span.end, pause.span.end)),
            title,
            manual=last.manual and pause.manual,
            open=last.open or pause.open,
        )
    return merged


def collect_pauses(activities: Iterable[Activity], anchor: date) -> list[Pause]:
    """Every enabled non-work activity near ``anchor``, merged into pauses.

    The day before and after are included so activities that cross midnight
    still count. Overlapping pauses merge into one.
    """
    raw: list[Pause] = []
    for activity in activities:
        if not activity.enabled or activity.is_work:
            continue
        for offset in (-1, 0, 1):
            day = anchor + timedelta(days=offset)
            if not mask_includes(activity.days_mask, day):
                continue
            start, end = span_after(day, activity.start_clock, activity.end_clock)
            raw.append(Pause(Span(start, end), activity.title or "Activity"))
    return merge_pauses(raw)


def with_manual_pauses(
    pauses: Iterable[Pause], manual: Iterable[tuple[datetime, datetime | None]], now: datetime
) -> list[Pause]:
    """Add the user's Pause-button pauses. One still open lasts until ``now``.

    A manual pause is a pause like any other: the work clock and the pomodoro schedule
    both count only the time outside every pause, so the two can never disagree.
    """
    extra = [
        Pause(Span(paused_at, resumed_at or max(now, paused_at)), MANUAL_PAUSE_TITLE,
              manual=True, open=resumed_at is None)
        for paused_at, resumed_at in manual
    ]
    return merge_pauses([*pauses, *extra])


def productive_between(start: datetime, end: datetime, pauses: Iterable[Pause]) -> timedelta:
    """Time between ``start`` and ``end`` that is not inside a pause."""
    if end <= start:
        return timedelta(0)
    total = end - start
    for pause in pauses:
        overlap = min(end, pause.span.end) - max(start, pause.span.start)
        if overlap > timedelta(0):
            total -= overlap
    return max(timedelta(0), total)


def finish_with_pauses(start: datetime, planned: timedelta, pauses: Iterable[Pause]) -> datetime:
    """When a block that needs ``planned`` of focus really finishes.

    Time spent inside a pause does not count, so the finish moves later by
    exactly the overlap. A pause that ends before the block starts, or that
    begins after the block would already be done, changes nothing.
    """
    remaining = planned
    cursor = start
    for pause in sorted(pauses, key=lambda p: p.span.start):
        if pause.span.end <= cursor:
            continue
        if pause.span.start > cursor:
            productive = pause.span.start - cursor
            if productive >= remaining:
                return cursor + remaining
            remaining -= productive
            cursor = pause.span.start
        cursor = max(cursor, pause.span.end)
    return cursor + remaining


def work_progress(
    start: datetime,
    planned: timedelta,
    pauses: Iterable[Pause],
    now: datetime,
    deadline: datetime | None = None,
) -> WorkProgress:
    """Where a block stands at ``now``, excluding paused time.

    ``deadline`` (bedtime) protects the night: however long the pauses were, work never runs
    past it. Focus that no longer fits is reported as ``cut`` and left out of ``planned``.
    """
    pauses = list(pauses)
    finish = finish_with_pauses(start, planned, pauses)
    cut = timedelta(0)
    if deadline is not None and finish > deadline:
        finish = max(start, deadline)
        cut = max(timedelta(0), planned - productive_between(start, finish, pauses))
        planned -= cut

    if now < start:
        return WorkProgress(WorkStatus.UPCOMING, start, finish, planned, planned, cut=cut)
    if now >= finish:
        return WorkProgress(WorkStatus.DONE, start, finish, planned, timedelta(0), cut=cut)

    paused = timedelta(0)
    active: Pause | None = None
    for pause in pauses:
        overlap_start = max(start, pause.span.start)
        overlap_end = min(now, pause.span.end, finish)
        if overlap_end > overlap_start:
            paused += overlap_end - overlap_start
        if pause.span.contains(now) or (pause.open and pause.span.start <= now <= pause.span.end):
            active = pause

    elapsed = max(timedelta(0), min(now, finish) - start)
    productive = min(planned, max(timedelta(0), elapsed - paused))
    return WorkProgress(
        WorkStatus.PAUSED if active else WorkStatus.ACTIVE,
        start,
        finish,
        planned,
        max(timedelta(0), planned - productive),
        active,
        cut,
    )
