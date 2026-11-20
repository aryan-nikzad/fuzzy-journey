"""The Flexibility pack, as arithmetic.

No GTK, no database, no clock. Like :mod:`fuzzy_journey.rhythm` and :mod:`fuzzy_journey.pomodoro`, this
module only turns facts into plans, so every rule here can be tested exactly.

The pack is a set of opt-in changes (Preferences -> Flexibility). With it switched off nothing in this
module is ever used, and the app behaves exactly as it did before. With it on:

1. **A morning routine.** Your own list of steps, each with a rough length, plus a *buffer* for the
   days the steps run long. The work of the day begins after it, not at Fajr.
2. **Start work by button** (separate switch). The day's work begins when you press *Start work*, and
   that moment is recorded for the calendar. Until then the plan shows what starting *now* would mean.
3. **Flexible blocks.** Every focus block and every break has its own Start and Stop, so one block can
   run longer and another shorter, and the day ends when you press *End work*.
4. **Do nothing.** A short, protected time with the computer off and nothing to do: placed after work,
   at a fixed time, or before work.

Counting is still *focus, not clock time*: a pause (the gym, a call, the Pause button) never counts as
work, and the figures use the same pauses as the pomodoro schedule.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum

from .pomodoro import PomodoroSettings, SegmentKind, break_after
from .rhythm import Pause, Span, finish_with_pauses, productive_between

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

BUFFER_RANGE = (0, 120)
BUFFER_DEFAULT = 15
ITEM_MINUTES_RANGE = (1, 240)
MAX_ROUTINE_ITEMS = 30
NOTHING_RANGE = (5, 90)
NOTHING_DEFAULT = 20
NOTHING_DEFAULT_AT = time(15, 0)

AFTER_WORK, FIXED_TIME, BEFORE_WORK = "after_work", "fixed", "before_work"
NOTHING_PLACES = (AFTER_WORK, FIXED_TIME, BEFORE_WORK)
NOTHING_LABELS = {
    AFTER_WORK: "After work ends",
    FIXED_TIME: "At a fixed time",
    BEFORE_WORK: "Before work, after the routine",
}

#: What *Do nothing* is, in a few words. Shown on the card and in Preferences.
NOTHING_RULES = "Computer off. No games, no phone, no reading, no planning. Sit, stand, look, walk, or lie down."

PLANNING_AFTER_END = 30  # minutes kept for settling and planning once work has been ended


@dataclass(frozen=True)
class FlexSettings:
    """What is switched on. ``enabled`` is the pack itself: when it is off, nothing else counts."""

    enabled: bool = False
    routine: bool = True
    buffer: int = BUFFER_DEFAULT
    manual_start: bool = False
    blocks: bool = True
    nothing: bool = True
    nothing_minutes: int = NOTHING_DEFAULT
    nothing_where: str = AFTER_WORK
    nothing_at: time = NOTHING_DEFAULT_AT
    nothing_alarm: bool = True

    @property
    def use_routine(self) -> bool:
        return self.enabled and self.routine

    @property
    def use_start(self) -> bool:
        return self.enabled and self.manual_start

    @property
    def use_blocks(self) -> bool:
        return self.enabled and self.blocks

    @property
    def use_nothing(self) -> bool:
        return self.enabled and self.nothing

    @property
    def controls_work(self) -> bool:
        """The person, not the clock, starts and ends the work."""
        return self.use_start or self.use_blocks


# --------------------------------------------------------------------------
# The morning routine
# --------------------------------------------------------------------------


@dataclass
class RoutineItem:
    """One step of the morning: a name and roughly how long it takes."""

    title: str
    minutes: int
    enabled: bool = True
    position: int = 0
    id: int | None = None


def check_routine_item(title: str, minutes: int) -> str | None:
    """Why this step cannot be saved, in words fit to show, or ``None``."""
    if not title.strip():
        return "Give the step a name."
    if not ITEM_MINUTES_RANGE[0] <= minutes <= ITEM_MINUTES_RANGE[1]:
        return f"A step takes between {ITEM_MINUTES_RANGE[0]} and {ITEM_MINUTES_RANGE[1]} minutes."
    return None


@dataclass(frozen=True)
class RoutineStep:
    title: str
    span: Span
    buffer: bool = False  # the slack at the end, not a step of its own

    @property
    def minutes(self) -> int:
        return int(self.span.duration.total_seconds() // 60)


@dataclass(frozen=True)
class RoutinePlan:
    """The morning laid out from ``start``: every step in order, then the buffer."""

    start: datetime
    steps: tuple[RoutineStep, ...]
    end: datetime

    @property
    def total(self) -> timedelta:
        return self.end - self.start

    @property
    def empty(self) -> bool:
        return not self.steps

    def current(self, now: datetime) -> RoutineStep | None:
        return next((s for s in self.steps if s.span.contains(now)), None)

    def following(self, step: RoutineStep) -> RoutineStep | None:
        index = self.steps.index(step)
        return self.steps[index + 1] if index + 1 < len(self.steps) else None


def routine_plan(start: datetime, items: Iterable[RoutineItem], buffer: int) -> RoutinePlan | None:
    """Lay the enabled steps out one after another from ``start``, then add the buffer.

    No steps means no routine, so ``None``: a buffer alone would only delay the day for nothing.
    """
    steps: list[RoutineStep] = []
    cursor = start
    for item in items:
        if not item.enabled or item.minutes <= 0:
            continue
        end = cursor + timedelta(minutes=item.minutes)
        steps.append(RoutineStep(item.title, Span(cursor, end)))
        cursor = end
    if not steps:
        return None
    if buffer > 0:
        end = cursor + timedelta(minutes=buffer)
        steps.append(RoutineStep("Buffer", Span(cursor, end), buffer=True))
        cursor = end
    return RoutinePlan(start, tuple(steps), cursor)


# --------------------------------------------------------------------------
# Do nothing
# --------------------------------------------------------------------------


def nothing_span_fixed(day: date, at: time, minutes: int) -> Span:
    begin = datetime.combine(day, at)
    return Span(begin, begin + timedelta(minutes=minutes))


# --------------------------------------------------------------------------
# What the person has done today
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    """One stretch the person really ran: a focus block or a break, with its true start and stop."""

    kind: SegmentKind
    start: datetime
    stop: datetime | None = None  # None: still running
    id: int | None = None

    @property
    def open(self) -> bool:
        return self.stop is None


@dataclass(frozen=True)
class FlexDay:
    """The record of one day: when work was started and ended, and every block in between."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    runs: tuple[Run, ...] = ()


class Phase(Enum):
    #: Start work is waiting to be pressed (the manual-start option is on).
    WAITING = "waiting"
    #: Flexible blocks: nothing is running; Start begins the next block or break.
    READY = "ready"
    #: A block or break is running (or, with blocks off, the day's work has been started).
    RUNNING = "running"
    #: Work has been ended, by the person or by bedtime.
    ENDED = "ended"


@dataclass(frozen=True)
class FlexState:
    """Where the person's own start/stop day stands at ``now``."""

    phase: Phase
    started_at: datetime | None
    ended_at: datetime | None
    runs: tuple[Run, ...]
    current: Run | None
    next_kind: SegmentKind | None  # what Start would begin (blocks only)
    nominal: int  # minutes of the current block, or of the one Start would begin
    left: timedelta  # of the current block; negative once it has run over
    worked: timedelta  # focus really run today, pauses and breaks left out
    target: timedelta  # the focus the day aims for
    focus_blocks: int  # focus blocks begun so far
    projected_end: datetime | None  # when the target would be reached at this pace
    idle_since: datetime | None  # when the last block was stopped (READY only)

    @property
    def over(self) -> bool:
        """The running block has gone past its planned length."""
        return self.current is not None and self.left < timedelta(0)

    @property
    def target_reached(self) -> bool:
        return self.target > timedelta(0) and self.worked >= self.target

    @property
    def focus_left(self) -> timedelta:
        return max(timedelta(0), self.target - self.worked)


def focus_since_long(runs: Sequence[Run]) -> int:
    """Focus blocks begun since the last long break: where the cycle stands."""
    count = 0
    for run in runs:
        if run.kind is SegmentKind.FOCUS:
            count += 1
        elif run.kind is SegmentKind.LONG:
            count = 0
    return count


def next_kind(runs: Sequence[Run], pomodoro: PomodoroSettings) -> SegmentKind:
    """What Start begins after ``runs``: a break after a focus block when one is due, else focus."""
    if not runs or runs[-1].kind is not SegmentKind.FOCUS or not pomodoro.enabled:
        return SegmentKind.FOCUS
    rest = break_after(focus_since_long(runs), pomodoro)
    return rest[0] if rest else SegmentKind.FOCUS


def nominal_minutes(kind: SegmentKind, pomodoro: PomodoroSettings, focus_left: timedelta) -> int:
    """The planned length of a block. With pomodoro off, work is one stretch: all that is left."""
    if kind is SegmentKind.SHORT:
        return pomodoro.short
    if kind is SegmentKind.LONG:
        return pomodoro.long
    if not pomodoro.enabled:
        return max(10, int(focus_left.total_seconds() // 60))
    return pomodoro.focus


def _project_end(
    now: datetime, state_runs: Sequence[Run], current: Run | None, left: timedelta, remaining: timedelta,
    pomodoro: PomodoroSettings, pauses: Sequence[Pause],
) -> datetime | None:
    """When ``remaining`` focus would be done if every block ran to its planned length from ``now``."""
    if remaining <= timedelta(0):
        return None
    pauses = sorted(pauses, key=lambda p: p.span.start)
    cursor = now
    count = focus_since_long(state_runs)
    todo = remaining
    kind = current.kind if current else next_kind(state_runs, pomodoro)

    if current is not None:
        # Finish what is running first (a run that is already over adds nothing).
        spare = max(timedelta(0), left)
        if spare > timedelta(0):
            cursor = finish_with_pauses(cursor, spare, pauses)
        if current.kind is SegmentKind.FOCUS:
            todo = max(timedelta(0), todo - spare)
            if todo <= timedelta(0):
                return cursor
            rest = break_after(count, pomodoro) if pomodoro.enabled else None
            kind = rest[0] if rest else SegmentKind.FOCUS
        else:
            kind = SegmentKind.FOCUS

    guard = 0
    while todo > timedelta(0) and guard < 200:
        guard += 1
        if kind is SegmentKind.FOCUS:
            block = min(todo, timedelta(minutes=pomodoro.focus)) if pomodoro.enabled else todo
            cursor = finish_with_pauses(cursor, block, pauses)
            todo -= block
            count += 1
            rest = break_after(count, pomodoro) if (pomodoro.enabled and todo > timedelta(0)) else None
            kind = rest[0] if rest else SegmentKind.FOCUS
        else:
            minutes = pomodoro.long if kind is SegmentKind.LONG else pomodoro.short
            cursor = finish_with_pauses(cursor, timedelta(minutes=minutes), pauses)
            if kind is SegmentKind.LONG:
                count = 0
            kind = SegmentKind.FOCUS
    return cursor


def flex_state(
    day: FlexDay,
    *,
    now: datetime,
    pauses: Sequence[Pause],
    pomodoro: PomodoroSettings,
    target: timedelta,
    deadline: datetime | None,
    settings: FlexSettings,
) -> FlexState:
    """Where the person's own start/stop day stands.

    ``deadline`` is bedtime: a day that was started and is still open at bedtime counts as ended, and
    nothing is counted past it (the night is protected, as everywhere else in the app).
    """
    clock = min(now, deadline) if deadline is not None else now
    started = day.started_at
    ended = day.ended_at is not None or (started is not None and deadline is not None and now >= deadline)
    runs = tuple(day.runs)
    current = next((r for r in runs if r.open), None) if not ended else None

    worked = timedelta(0)
    for run in runs:
        if run.kind is not SegmentKind.FOCUS:
            continue
        stop = run.stop or day.ended_at or clock
        worked += productive_between(run.start, min(stop, clock), pauses)

    focus_left = max(timedelta(0), target - worked)
    focus_blocks = sum(1 for r in runs if r.kind is SegmentKind.FOCUS)
    idle_since = runs[-1].stop if runs and not runs[-1].open else None

    if not settings.use_blocks:
        phase = Phase.ENDED if ended else Phase.RUNNING if started else Phase.WAITING
        return FlexState(phase, started, day.ended_at, runs, None, None, 0, timedelta(0), worked, target,
                         focus_blocks, None, None)

    kind = current.kind if current else next_kind(runs, pomodoro)
    left = timedelta(0)
    if current is not None:
        # A block planned as "all that is left" (pomodoro off) is measured against the whole target.
        nominal = nominal_minutes(current.kind, pomodoro, target)
        left = timedelta(minutes=nominal) - productive_between(current.start, clock, pauses)
    else:
        nominal = nominal_minutes(kind, pomodoro, focus_left)
    if ended:
        phase = Phase.ENDED
    elif current is not None:
        phase = Phase.RUNNING
    elif started is None and settings.use_start:
        phase = Phase.WAITING
    else:
        phase = Phase.READY
    projected = None
    if phase in (Phase.READY, Phase.RUNNING, Phase.WAITING):
        projected = _project_end(clock, runs, current, left, focus_left, pomodoro, pauses)
    return FlexState(phase, started, day.ended_at, runs, current, None if current else kind, nominal, left,
                     worked, target, focus_blocks, projected, idle_since)


# --------------------------------------------------------------------------
# Everything the Today screen needs from the pack
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FlexInput:
    """What :func:`fuzzy_journey.today.build_today` is given when the pack is on."""

    settings: FlexSettings
    routine: tuple[RoutineItem, ...] = ()
    day: FlexDay = field(default_factory=FlexDay)


@dataclass(frozen=True)
class FlexView:
    """What the pack worked out for one day, ready to draw."""

    settings: FlexSettings
    routine: RoutinePlan | None = None
    state: FlexState | None = None
    #: The Do-nothing time (``None`` when switched off or not placeable) and where it came from.
    nothing: Span | None = None
    nothing_note: str = ""
    #: Start work is waiting to be pressed, so the plan shown is a projection from "now".
    waiting: bool = False
    #: The day was never started and is over: nothing was worked.
    never_started: bool = False

    @property
    def nothing_active(self) -> bool:
        return self.nothing is not None


def run_events(view_state: FlexState | None, day: date, sound, pauses: Sequence[Pause],
               pomodoro: PomodoroSettings, held: bool) -> list:
    """The one alarm a running block has: its planned end. The block itself never stops by itself."""
    from .alarms import ScheduledEvent  # local: alarms imports the database, which imports this module

    if view_state is None or view_state.current is None or held:
        return []
    run = view_state.current
    if run.kind is SegmentKind.FOCUS and not pomodoro.enabled:
        return []
    due = finish_with_pauses(run.start, timedelta(minutes=view_state.nominal), sorted(pauses, key=lambda p: p.span.start))
    title = (f"{run.kind.label} · {view_state.nominal} min is up · stop when you are ready"
             if run.kind is SegmentKind.FOCUS else f"{run.kind.label} is over · start when you are ready")
    return [ScheduledEvent(f"flex:{run.id}", title, due, sound, day, "Pomodoro")]
