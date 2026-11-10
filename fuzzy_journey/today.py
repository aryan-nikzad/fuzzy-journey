"""Everything the Today screen shows, computed in one pure function.

:func:`build_today` takes the facts (prayer times, the chosen day kind, the
user's activities and alarms) and returns a :class:`TodayView`. The GUI only
renders it, so every rule here is covered by plain unit tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum

from . import alarms as alarm_rules
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
    plan_day,
    with_manual_pauses,
    work_progress,
)
from .timeutil import mask_includes, span_after

DAILY_PRAYERS = ("Dhuhr", "Asr", "Maghrib", "Isha")


class Slot(Enum):
    WAKE = "wake"
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
) -> TodayView:
    day = now.date()
    activities = [a for a in activities]
    todays = [a for a in activities if a.enabled and mask_includes(a.days_mask, day)]
    wake_act = next((a for a in todays if a.category == "wake"), None)
    sleep_act = next((a for a in todays if a.category == "sleep"), None)

    plan = (
        plan_day(
            day, kind, fajr=prayer_day.fajr, isha=prayer_day.isha, next_fajr=next_fajr,
            evening_start=evening_start, flex=flex, start=start,
            overtime=timedelta(minutes=overtime), evening_extra=timedelta(minutes=evening),
        )
        if prayer_day
        else None
    )

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
    if kind is not DayKind.REST:
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
    if pomodoro is not None:
        schedule = build_schedule(
            [(w.progress.start, w.progress.planned) for w in work], pauses, pomodoro, deadline
        )
        held = next((p.span.start for p in pauses if p.open), None)  # nothing rings until resumed
        pomo_events = schedule_events(schedule, day, pomodoro_sound or Sound(), hold_after=held)

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

    if plan and kind is DayKind.REST:
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

    worked = focus_worked(schedule, pauses, now) if schedule else timedelta(0)
    closing_at = None
    if kind is not DayKind.REST and work and any(w.progress.planned > timedelta(0) for w in work):
        closing_at = closing_moment(schedule, max(w.progress.end for w in work))

    return TodayView(
        now=now, day=day, kind=kind, plan=plan, wake=wake, bedtime=bedtime, sleep=sleep,
        sleep_lost=sleep_lost, work=tuple(work), work_remaining=remaining, focus=focus,
        timeline=tuple(rows), segments=tuple(segments), prayer_marks=marks,
        next_alarm=next_alarm, alarm_times=frozenset(alarm_moments), schedule=schedule,
        pauses=tuple(pauses), worked=worked, closing_at=closing_at, pomodoro_events=tuple(pomo_events),
    )


def _is_sleep_like(pause: Pause, sleep_act: Activity | None) -> bool:
    return bool(sleep_act and pause.title == sleep_act.title)
