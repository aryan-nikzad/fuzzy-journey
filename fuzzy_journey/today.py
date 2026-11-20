"""Everything the Today screen shows, computed in one pure function.

:func:`build_today` takes the facts (prayer times, the chosen day kind, the
user's activities and alarms) and returns a :class:`TodayView`. The GUI only
renders it, so every rule here is covered by plain unit tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from enum import Enum

from . import alarms as alarm_rules
from .flex import (
    AFTER_WORK,
    BEFORE_WORK,
    FIXED_TIME,
    PLANNING_AFTER_END,
    FlexInput,
    FlexView,
    nothing_span_fixed,
    routine_plan,
    run_events,
)
from .flex import flex_state as compute_flex_state
from .models import Activity, Alarm, PrayerAlarm, Sound
from .pomodoro import (
    ManualPause,
    PomodoroSettings,
    Schedule,
    build_schedule,
    closing_moment,
    focus_worked,
    schedule_events,
)
from .prayer_times import PrayerDay
from .rhythm import (
    DEFAULT_EVENING_START,
    DayKind,
    DayPlan,
    Pause,
    Span,
    WorkProgress,
    WorkStatus,
    collect_pauses,
    merge_pauses,
    plan_day,
    with_manual_pauses,
    work_progress,
)
from .timeutil import mask_includes, span_after

DAILY_PRAYERS = ("Dhuhr", "Asr", "Maghrib", "Isha")


class Slot(Enum):
    WAKE = "wake"
    ROUTINE = "routine"  # a step of the morning routine (Flexibility pack)
    NOTHING = "nothing"  # the Do-nothing time (Flexibility pack)
    WORK = "work"
    FREE = "free"
    PRAYER = "prayer"
    ACTIVITY = "activity"
    REMINDER = "reminder"
    SLEEP = "sleep"


class RowState(Enum):
    PAST = "past"
    NOW = "now"
    LATER = "later"


@dataclass(frozen=True)
class WorkItem:
    title: str
    progress: WorkProgress
    activity: Activity | None = None


@dataclass(frozen=True)
class TimelineRow:
    start: datetime
    end: datetime | None
    slot: Slot
    title: str
    detail: str
    state: RowState
    has_alarm: bool = False

    @property
    def signature(self) -> tuple:
        return (self.start, self.end, self.slot, self.title, self.detail, self.state, self.has_alarm)


@dataclass(frozen=True)
class DayBarSegment:
    span: Span
    kind: str  # "work" | "pause" | "free"


@dataclass(frozen=True)
class NextAlarm:
    due: datetime
    title: str


@dataclass(frozen=True)
class TodayView:
    now: datetime
    day: date
    kind: DayKind
    plan: DayPlan | None
    wake: datetime | None
    bedtime: datetime | None
    sleep: timedelta | None
    sleep_lost: timedelta
    work: tuple[WorkItem, ...]
    work_remaining: timedelta
    focus: WorkItem | None
    timeline: tuple[TimelineRow, ...]
    segments: tuple[DayBarSegment, ...]
    prayer_marks: tuple[datetime, ...]
    next_alarm: NextAlarm | None = None
    alarm_times: frozenset[datetime] = field(default_factory=frozenset)
    schedule: Schedule | None = None
    #: Every pause of the day, the user's own included. The one list both clocks count from.
    pauses: tuple[Pause, ...] = ()
    #: Focus the clock has really run so far today: no pauses, breaks or planning.
    worked: timedelta = timedelta(0)
    #: When the day's work is over and its tasks should be settled (planning begins).
    closing_at: datetime | None = None
    pomodoro_events: tuple = ()
    #: Everything the Flexibility pack worked out. ``None`` when the pack is off: nothing else changes then.
    flexpack: FlexView | None = None

    @property
    def closing_due(self) -> bool:
        return self.closing_at is not None and self.now >= self.closing_at

    @property
    def work_cut(self) -> timedelta:
        """Focus left out so that work never runs past bedtime."""
        return sum((w.progress.cut for w in self.work), timedelta(0))

    @property
    def has_prayer_data(self) -> bool:
        return self.plan is not None

    @property
    def work_total(self) -> timedelta:
        return sum((w.progress.planned for w in self.work), timedelta(0))

    @property
    def work_done(self) -> bool:
        return bool(self.work) and all(w.progress.status is WorkStatus.DONE for w in self.work)


def _state(now: datetime, start: datetime, end: datetime | None) -> RowState:
    if end is not None and start <= now < end:
        return RowState.NOW
    if (end or start) <= now:
        return RowState.PAST
    return RowState.LATER


def _hm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _pretty(delta: timedelta) -> str:
    from .timeutil import human_duration

    return human_duration(delta)


def build_today(
    now: datetime,
    kind: DayKind,
    *,
    prayer_day: PrayerDay | None,
    next_fajr: time | None,
    activities: Iterable[Activity],
    reminders: Iterable[Alarm],
    prayer_alarms: Mapping[str, PrayerAlarm],
    evening_start: time = DEFAULT_EVENING_START,
    flex: timedelta = timedelta(0),
    start: time | None = None,
    overtime: int = 0,
    evening: int = 0,
    protect_bedtime: bool = True,
    pomodoro: PomodoroSettings | None = None,
    pomodoro_sound: Sound | None = None,
    pomodoro_pauses: Sequence[ManualPause] = (),
    flexpack: FlexInput | None = None,
) -> TodayView:
    day = now.date()
    activities = [a for a in activities]
    todays = [a for a in activities if a.enabled and mask_includes(a.days_mask, day)]
    wake_act = next((a for a in todays if a.category == "wake"), None)
    sleep_act = next((a for a in todays if a.category == "sleep"), None)

    recovered_from = start  # (``start`` is reused below for other spans)

    def make_plan(work_start: datetime | None = None) -> DayPlan | None:
        if not prayer_day:
            return None
        return plan_day(
            day, kind, fajr=prayer_day.fajr, isha=prayer_day.isha, next_fajr=next_fajr,
            evening_start=evening_start, flex=flex, start=recovered_from,
            overtime=timedelta(minutes=overtime), evening_extra=timedelta(minutes=evening),
            work_start=work_start,
        )

    plan = make_plan()

    # ---- Flexibility pack (opt-in): the morning routine, a work start of your own, the Do-nothing time.
    # With the pack off ``fx`` is None and every line below this block behaves exactly as it always did.
    fx = flexpack if flexpack is not None and flexpack.settings.enabled else None
    fs = fx.settings if fx else None
    routine = None
    waiting = never_started = False
    nothing_where = ""
    nothing_before = timedelta(0)
    day_start = None
    if fx and plan:
        day_start = datetime.combine(day, wake_act.start_clock) if wake_act else plan.wake
        nothing_where = fs.nothing_where if fs.use_nothing else ""
        if kind.no_work and nothing_where in (AFTER_WORK, BEFORE_WORK):
            nothing_where = FIXED_TIME  # no work to come after or before: keep it at a set time
        if nothing_where == BEFORE_WORK:
            nothing_before = timedelta(minutes=fs.nothing_minutes)
        if fs.use_routine:
            routine = routine_plan(day_start, fx.routine, fs.buffer)
        shifted = routine is not None or nothing_before > timedelta(0)
        base = (routine.end if routine else day_start) + nothing_before
        flex_start = None
        if fs.controls_work and not kind.no_work:
            if fx.day.started_at is not None:
                flex_start = fx.day.started_at
            else:
                flex_start = max(base if shifted else plan.wake, now.replace(second=0, microsecond=0))
                waiting = fs.use_start
        elif shifted and not kind.no_work:
            flex_start = base
        if flex_start is not None:
            planned = make_plan(flex_start)
            if fs.controls_work and fx.day.started_at is None and now >= plan.bedtime:
                # Never started, and the day is over: nothing was worked. Do not invent an evening of it.
                never_started, waiting = True, False
                planned = replace(plan, morning=None, evening=None, overtime=None, free=None, target=timedelta(0))
            plan = planned

    # ---- wake and bedtime: personal Wake / Sleep activities override the prayer-derived defaults
    wake = bedtime = None
    sleep: timedelta | None = None
    sleep_lost = plan.sleep_lost if plan else timedelta(0)
    if plan:
        wake, bedtime, sleep = plan.wake, plan.bedtime, plan.sleep
    if wake_act:
        wake = datetime.combine(day, wake_act.start_clock)
    elif sleep_act and not plan:
        wake = datetime.combine(day, sleep_act.end_clock)
    if sleep_act:
        start, end = span_after(day, sleep_act.start_clock, sleep_act.end_clock)
        bedtime, sleep, sleep_lost = start, end - start, timedelta(0)
        if wake and bedtime <= wake:
            bedtime += timedelta(days=1)

    # ---- work: generated blocks plus the user's own work activities
    # The user's own pauses are pauses like any other, so the work clock and the pomodoro
    # schedule count the same time. Bedtime is the deadline: work never runs past it.
    pauses = with_manual_pauses(collect_pauses(activities, day), pomodoro_pauses, now)
    nothing: Span | None = None
    nothing_note = ""
    if fx and nothing_where == FIXED_TIME:
        nothing = nothing_span_fixed(day, fs.nothing_at, fs.nothing_minutes)
        pauses = merge_pauses([*pauses, Pause(nothing, "Do nothing")])  # work waits for it, like for the gym
    elif fx and nothing_where == BEFORE_WORK and day_start is not None:
        begin = routine.end if routine else day_start
        nothing = Span(begin, begin + nothing_before)
    deadline = bedtime if protect_bedtime else None
    work: list[WorkItem] = []
    if plan:
        first = "Recovered work" if kind is DayKind.RECOVERED else "Morning work"
        for title, span in ((first, plan.morning), ("Evening work", plan.evening)):
            if span:
                work.append(WorkItem(title, work_progress(span.start, span.duration, pauses, now, deadline)))
    if plan and plan.overtime:
        night = plan.overtime
        work.append(WorkItem("Night work", work_progress(night.start, night.duration, pauses, now, deadline)))
    if not kind.no_work:
        for act in todays:
            if act.is_work:
                start, end = span_after(day, act.start_clock, act.end_clock)
                work.append(WorkItem(act.title, work_progress(start, end - start, pauses, now, deadline), act))
    work.sort(key=lambda w: w.progress.start)

    focus = (
        next((w for w in work if w.progress.status in (WorkStatus.ACTIVE, WorkStatus.PAUSED)), None)
        or next((w for w in work if w.progress.status is WorkStatus.UPCOMING), None)
        or (work[-1] if work else None)
    )
    remaining = sum((w.progress.remaining for w in work), timedelta(0))

    # ---- pomodoro and planning (only when the caller opts in)
    schedule: Schedule | None = None
    pomo_events = []
    state = None
    controlled = bool(fx and fs.controls_work and plan and not kind.no_work and not never_started)
    if pomodoro is not None:
        # When you start and end the work yourself, planning follows *End work* instead of sitting at a fixed place.
        laid_out = replace(pomodoro, planning_enabled=False) if controlled else pomodoro
        schedule = build_schedule(
            [(w.progress.start, w.progress.planned) for w in work], pauses, laid_out, deadline
        )
        held = next((p.span.start for p in pauses if p.open), None)  # nothing rings until resumed
        pomo_events = schedule_events(schedule, day, pomodoro_sound or Sound(), hold_after=held)
        if controlled:
            state = compute_flex_state(
                fx.day, now=now, pauses=pauses, pomodoro=pomodoro,
                target=schedule.focus, deadline=deadline, settings=fs,
            )
            if fs.use_blocks:
                pomo_events = run_events(state, day, pomodoro_sound or Sound(), pauses, pomodoro, held is not None)
            elif waiting:
                pomo_events = []
            elif fx.day.ended_at is not None:
                pomo_events = [e for e in pomo_events if e.due <= fx.day.ended_at]

    # ---- the Do-nothing time after work, and the pack's own alarms
    if fx and nothing_where == AFTER_WORK and not kind.no_work and not never_started:
        gap = timedelta(minutes=PLANNING_AFTER_END if (pomodoro is None or pomodoro.planning_enabled) else 0)
        if controlled and fx.day.ended_at is not None:
            begin = fx.day.ended_at + gap
        elif controlled:
            end_of_work = max((w.progress.end for w in work), default=None)
            begin = end_of_work + gap if end_of_work else None
            nothing_note = "after you end work"
        else:
            planning = schedule.planning if schedule else None
            end_of_work = planning.end if planning else max((w.progress.end for w in work), default=None)
            begin = end_of_work
        if begin is not None:
            nothing = Span(begin, begin + timedelta(minutes=fs.nothing_minutes))
    if fx and nothing is not None and fs.nothing_alarm and not nothing_note:
        from .alarms import ScheduledEvent  # local: alarms imports the database, which imports this module

        ring = pomodoro_sound or Sound()
        pomo_events = [
            *pomo_events,
            ScheduledEvent("nothing:start", f"Do nothing · {fs.nothing_minutes} min · computer off",
                           nothing.start, ring, day, "Schedule"),
            ScheduledEvent("nothing:end", "Do nothing is over", nothing.end, ring, day, "Schedule"),
        ]
    if fx and fs.use_start and waiting and routine is not None:
        from .alarms import ScheduledEvent

        pomo_events = [*pomo_events, ScheduledEvent(
            "flex:routine-over", "Morning routine is over · press Start work", routine.end,
            pomodoro_sound or Sound(), day, "Schedule")]

    # ---- alarms
    reminder_due = {
        r.id: datetime.combine(day, r.clock)
        for r in reminders
        if r.enabled and alarm_rules.repeats_on(r, day)
    }
    reminder_list = [r for r in reminders if r.id in reminder_due]
    events = [
        e
        for e in alarm_rules.scheduled_events(
            day, prayer_day=prayer_day, prayer_alarms=prayer_alarms, activities=activities,
            kinds={day: kind},
        )
        if e.due.date() == day
    ]
    events += [e for e in pomo_events if e.due.date() == day]
    alarm_moments = [*reminder_due.values(), *(e.due for e in events)]
    upcoming = sorted(
        [(reminder_due[r.id], r.title) for r in reminder_list] + [(e.due, e.title) for e in events]
    )
    next_alarm = next((NextAlarm(due, title) for due, title in upcoming if due >= now), None)
    prayer_alarm_names = {n for n, a in prayer_alarms.items() if a.enabled}

    # ---- timeline
    rows: list[TimelineRow] = []

    def add(start, end, slot, title, detail="", alarm=False):
        rows.append(TimelineRow(start, end, slot, title, detail, _state(now, start, end), alarm))

    if wake:
        label = "Wake" if not plan or kind is DayKind.RECOVERED else "Wake · Fajr"
        add(wake, None, Slot.WAKE, label, "", "Fajr" in prayer_alarm_names and not wake_act and kind is not DayKind.RECOVERED)

    for item in work:
        p = item.progress
        if p.status is WorkStatus.UPCOMING:
            detail = f"{_hm(p.start)}–{_hm(p.end)} · {_pretty(p.planned)}"
        elif p.status is WorkStatus.DONE:
            detail = f"{_hm(p.start)}–{_hm(p.end)} · done"
        elif p.status is WorkStatus.PAUSED and p.pause:
            who = "by you" if p.pause.manual else f"for {p.pause.title}"
            detail = f"Paused {who} · {_pretty(p.remaining)} left"
        else:
            detail = f"{_hm(p.start)}–{_hm(p.end)} · {_pretty(p.remaining)} left"
        if p.cut > timedelta(0):
            detail += f" · {_pretty(p.cut)} cut to protect sleep"
        has_alarm = bool(item.activity and (item.activity.alarm_at_start or item.activity.alarm_at_end))
        add(p.start, p.end, Slot.WORK, item.title, detail, has_alarm)

    if schedule and schedule.planning:
        p = schedule.planning
        add(p.start, p.end, Slot.WORK, "Planning",
            f"{_hm(p.start)}–{_hm(p.end)} · settle today, plan tomorrow", True)

    if fx:
        if routine:
            for step in routine.steps:
                detail = (f"{_hm(step.span.start)}–{_hm(step.span.end)} · {step.minutes} min"
                          + (" · slack for a slow morning" if step.buffer else ""))
                add(step.span.start, step.span.end, Slot.ROUTINE, step.title, detail)
        if state:
            if state.started_at:
                add(state.started_at, None, Slot.WORK, "Work started", "You pressed Start work")
            for run in state.runs:
                until = run.stop or (now if run.stop is None and state.ended_at is None else None)
                length = int(((run.stop or min(now, deadline or now)) - run.start).total_seconds() // 60)
                tail = _hm(run.stop) if run.stop else "now"
                add(run.start, run.stop or until, Slot.WORK if run.kind.value == "focus" else Slot.ACTIVITY,
                    run.kind.label, f"{_hm(run.start)}–{tail} · {max(0, length)} min")
            if state.ended_at:
                add(state.ended_at, None, Slot.WORK, "Work ended", "You pressed End work")
                if pomodoro is None or pomodoro.planning_enabled:
                    add(state.ended_at, state.ended_at + timedelta(minutes=PLANNING_AFTER_END), Slot.WORK, "Planning",
                        "Settle today, plan tomorrow", True)
        if nothing is not None and fs.use_nothing:
            detail = f"{_hm(nothing.start)}–{_hm(nothing.end)} · {fs.nothing_minutes} min · computer off"
            add(nothing.start, nothing.end, Slot.NOTHING, "Do nothing",
                detail + (f" · {nothing_note}" if nothing_note else ""), fs.nothing_alarm and not nothing_note)

    if plan and kind is DayKind.OFFLINE:
        add(plan.wake, plan.bedtime, Slot.FREE, "Offline day", "No work · computer off")
    elif plan and kind is DayKind.REST:
        add(plan.wake, plan.bedtime, Slot.FREE, "Rest day", "No work today")
    elif plan and plan.free:
        # Free time begins when the morning work really finishes (an interruption may delay it).
        free_start = plan.free.start
        morning = next((w for w in work if w.activity is None and w.title in ("Morning work", "Recovered work")), None)
        if morning:
            free_start = max(free_start, morning.progress.end)
        free_end = plan.free.end
        if free_end - free_start >= timedelta(minutes=30):
            add(free_start, free_end, Slot.FREE, "Free time",
                f"{_hm(free_start)}–{_hm(free_end)} · {_pretty(free_end - free_start)}")

    if prayer_day:
        for name in DAILY_PRAYERS:
            moment = prayer_day.at(name)
            if moment:
                add(moment, None, Slot.PRAYER, name, "", name in prayer_alarm_names)

    for act in todays:
        if act.is_work or act.category in ("wake", "sleep"):
            continue
        start, end = span_after(day, act.start_clock, act.end_clock)
        flags = [t for t, on in (("start alarm", act.alarm_at_start), ("end alarm", act.alarm_at_end)) if on]
        detail = f"{_hm(start)}–{_hm(end)} · {act.category_label}"
        add(start, end, Slot.ACTIVITY, act.title, detail, bool(flags))

    for reminder in reminder_list:
        add(reminder_due[reminder.id], None, Slot.REMINDER, reminder.title, "Reminder", True)

    if bedtime:
        detail = _pretty(sleep) + " of sleep" if sleep is not None else ""
        if sleep_lost > timedelta(0):
            detail += f" · {_pretty(sleep_lost)} given up"
        add(bedtime, None, Slot.SLEEP, "Sleep", detail)

    rows.sort(key=lambda r: (r.start, r.slot is not Slot.WAKE))

    # ---- day bar
    segments: list[DayBarSegment] = []
    if wake and bedtime and bedtime > wake:
        segments.append(DayBarSegment(Span(wake, bedtime), "free"))
        for item in work:
            segments.append(DayBarSegment(Span(item.progress.start, item.progress.end), "work"))
        for pause in pauses:
            if pause.span.end > wake and pause.span.start < bedtime and not _is_sleep_like(pause, sleep_act):
                segments.append(DayBarSegment(pause.span, "pause"))
    marks = tuple(m for n in DAILY_PRAYERS if prayer_day and (m := prayer_day.at(n)))

    worked = state.worked if state else focus_worked(schedule, pauses, now) if schedule else timedelta(0)
    closing_at = None
    if not kind.no_work and work and any(w.progress.planned > timedelta(0) for w in work):
        closing_at = closing_moment(schedule, max(w.progress.end for w in work))
    if controlled:
        closing_at = fx.day.ended_at  # the check-in waits for the person to press End work
    flexview = (
        FlexView(fs, routine, state, nothing, nothing_note, waiting, never_started) if fx else None
    )

    return TodayView(
        now=now, day=day, kind=kind, plan=plan, wake=wake, bedtime=bedtime, sleep=sleep,
        sleep_lost=sleep_lost, work=tuple(work), work_remaining=remaining, focus=focus,
        timeline=tuple(rows), segments=tuple(segments), prayer_marks=marks,
        next_alarm=next_alarm, alarm_times=frozenset(alarm_moments), schedule=schedule,
        pauses=tuple(pauses), worked=worked, closing_at=closing_at, pomodoro_events=tuple(pomo_events),
        flexpack=flexview,
    )


def _is_sleep_like(pause: Pause, sleep_act: Activity | None) -> bool:
    return bool(sleep_act and pause.title == sleep_act.title)
