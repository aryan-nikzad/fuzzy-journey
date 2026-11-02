"""Everything the Today screen shows, computed in one pure function.

:func:`build_today` takes the facts (prayer times, the chosen day kind, the
user's activities and alarms) and returns a :class:`TodayView`. The GUI only
renders it, so every rule here is covered by plain unit tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum

from . import alarms as alarm_rules
from .models import Activity, Alarm, PrayerAlarm
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
) -> TodayView:
    day = now.date()
    activities = [a for a in activities]
    todays = [a for a in activities if a.enabled and mask_includes(a.days_mask, day)]
    wake_act = next((a for a in todays if a.category == "wake"), None)
    sleep_act = next((a for a in todays if a.category == "sleep"), None)

    plan = (
        plan_day(
            day, kind, fajr=prayer_day.fajr, isha=prayer_day.isha, next_fajr=next_fajr,
            evening_start=evening_start, flex=flex,
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
    pauses = collect_pauses(activities, day)
    work: list[WorkItem] = []
    if plan:
        for title, span in (("Morning work", plan.morning), ("Evening work", plan.evening)):
            if span:
                work.append(WorkItem(title, work_progress(span.start, span.duration, pauses, now)))
    if kind is not DayKind.REST:
        for act in todays:
            if act.is_work:
                start, end = span_after(day, act.start_clock, act.end_clock)
                work.append(WorkItem(act.title, work_progress(start, end - start, pauses, now), act))
    work.sort(key=lambda w: w.progress.start)

    focus = (
        next((w for w in work if w.progress.status in (WorkStatus.ACTIVE, WorkStatus.PAUSED)), None)
        or next((w for w in work if w.progress.status is WorkStatus.UPCOMING), None)
        or (work[-1] if work else None)
    )
    remaining = sum((w.progress.remaining for w in work), timedelta(0))

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
        label = "Wake" if not plan else "Wake · Fajr"
        add(wake, None, Slot.WAKE, label, "", "Fajr" in prayer_alarm_names and not wake_act)

    for item in work:
        p = item.progress
        if p.status is WorkStatus.UPCOMING:
            detail = f"{_hm(p.start)}–{_hm(p.end)} · {_pretty(p.planned)}"
        elif p.status is WorkStatus.DONE:
            detail = f"{_hm(p.start)}–{_hm(p.end)} · done"
        elif p.status is WorkStatus.PAUSED and p.pause:
            detail = f"Paused for {p.pause.title} · {_pretty(p.remaining)} left"
        else:
            detail = f"{_hm(p.start)}–{_hm(p.end)} · {_pretty(p.remaining)} left"
        has_alarm = bool(item.activity and (item.activity.alarm_at_start or item.activity.alarm_at_end))
        add(p.start, p.end, Slot.WORK, item.title, detail, has_alarm)

    if plan and kind is DayKind.REST:
        add(plan.wake, plan.bedtime, Slot.FREE, "Rest day", "No work today")
    elif plan and plan.free:
        # Free time begins when the morning work really finishes (an interruption may delay it).
        free_start = plan.free.start
        morning = next((w for w in work if w.activity is None and w.title == "Morning work"), None)
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

    return TodayView(
        now=now, day=day, kind=kind, plan=plan, wake=wake, bedtime=bedtime, sleep=sleep,
        sleep_lost=sleep_lost, work=tuple(work), work_remaining=remaining, focus=focus,
        timeline=tuple(rows), segments=tuple(segments), prayer_marks=marks,
        next_alarm=next_alarm, alarm_times=frozenset(alarm_moments),
    )


def _is_sleep_like(pause: Pause, sleep_act: Activity | None) -> bool:
    return bool(sleep_act and pause.title == sleep_act.title)
