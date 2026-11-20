"""The Flexibility pack's card on Today: the routine, *Start work*, flexible blocks, *End work*, Do nothing.

It only ever appears when the pack is on (``view.flexpack`` is ``None`` otherwise, and the card hides
itself). Where the pack takes over the work clock it also asks the ordinary pomodoro card to step aside,
so the screen never shows two answers to "what do I do now?".
"""

from __future__ import annotations

from datetime import timedelta

from .. import planner
from ..flex import NOTHING_RULES, Phase
from ..pomodoro import SegmentKind
from ..timeutil import human_duration
from ..timeutil import now as clock_now
from .context import Context
from .focus import FocusCard
from .gi_setup import GLib, Gtk
from .widgets import label


def _clock(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    return f"{total // 60:02d}:{total % 60:02d}"


def _ago(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return "just now" if minutes < 1 else f"{human_duration(delta)} ago"


class FlexCard(Gtk.Box):
    def __init__(self, ctx: Context, static_card: FocusCard) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.ctx = ctx
        self.static_card = static_card
        self.add_css_class("fj-card")
        self._view = None
        self._action = None  # what the big button does right now

        self.overline = label("", "fj-overline")
        self.timer = label("", "fj-timer")
        self.detail = label("", "fj-hero-sub", wrap=True)
        for w in (self.overline, self.timer, self.detail):
            self.append(w)

        # The big button: Start work, or Start for the next block. Hard to miss, easy to hit.
        self.cta = Gtk.Button(hexpand=True, margin_top=10)
        self.cta.add_css_class("suggested-action")
        self.cta.add_css_class("pill")
        self.cta.add_css_class("fj-cta")
        self.cta.connect("clicked", self._on_cta)
        self.append(self.cta)

        self.buttons = Gtk.Box(spacing=8, margin_top=6)
        self.stop = self._button("Stop", self._on_stop)
        self.pause = self._button("Pause", self._on_pause)
        self.end = self._button("End work", self._on_end, tooltip="The day's work is over")
        self.settle = self._button("Settle today’s tasks", self._on_settle, suggested=True)
        self.plan = self._button("Plan tomorrow", lambda _b: ctx.show_page("tomorrow"))
        self.resume = self._button("Resume work", self._on_resume, flat=True, tooltip="Take back End work")
        for b in (self.stop, self.pause, self.end, self.settle, self.plan, self.resume):
            self.buttons.append(b)
        self.append(self.buttons)

        self.set_visible(False)
        GLib.timeout_add_seconds(1, self._tick)

    @staticmethod
    def _button(text, handler, *, suggested=False, flat=False, tooltip=None) -> Gtk.Button:
        button = Gtk.Button(label=text, halign=Gtk.Align.START)
        button.add_css_class("pill" if not flat else "flat")
        if suggested:
            button.add_css_class("suggested-action")
        if tooltip:
            button.set_tooltip_text(tooltip)
        button.connect("clicked", handler)
        return button

    # -- data ----------------------------------------------------------------

    def update(self, view) -> None:
        self._view = view
        self._render()

    def _tick(self) -> bool:
        if self._view is not None and self.get_mapped():
            self._render()
        return GLib.SOURCE_CONTINUE

    # -- drawing -------------------------------------------------------------

    def _show(self, *, overline="", timer="", detail="", cta=None, buttons=()) -> None:
        self.set_visible(True)
        self.overline.set_text(overline)
        self.timer.set_text(timer)
        self.timer.set_visible(bool(timer))
        self.detail.set_text(detail)
        self.detail.set_visible(bool(detail))
        self.cta.set_visible(cta is not None)
        if cta is not None:
            self.cta.set_label(cta[0])
            self._action = cta[1]
        for b in (self.stop, self.pause, self.end, self.settle, self.plan, self.resume):
            b.set_visible(b in buttons)
        self.buttons.set_visible(bool(buttons))

    def _render(self) -> None:
        view, now = self._view, clock_now()
        fx = view.flexpack if view is not None else None
        if fx is None:
            self.static_card.suppressed = False
            self.set_visible(False)
            return
        fs, state, routine, nothing = fx.settings, fx.state, fx.routine, fx.nothing

        in_routine = routine is not None and now < routine.end and (state is None or state.started_at is None)
        in_nothing = nothing is not None and fs.use_nothing and nothing.start <= now < nothing.end and not fx.nothing_note
        takes_over = state is not None and (fs.use_blocks or state.phase in (Phase.WAITING, Phase.ENDED))
        # Nothing else competes with Do nothing or the morning routine for the screen.
        self.static_card.suppressed = takes_over or in_nothing or in_routine

        if in_nothing:
            self._show(overline="DO NOTHING", timer=_clock(nothing.end - now),
                       detail=f"{NOTHING_RULES} Until {nothing.end:%H:%M}.")
            return

        if in_routine:
            step = routine.current(now)
            cta = None
            if state is not None and state.phase in (Phase.WAITING, Phase.READY):
                cta = ("Routine done, start work" if state.phase is Phase.WAITING else "Start work early",
                       self._start_work)
            if step is None:
                self._show(overline="MORNING ROUTINE", detail=f"Work starts at {routine.end:%H:%M}.", cta=cta)
                return
            following = routine.following(step)
            tail = f" · then {following.title.lower()}" if following else ""
            text = "Slack for a slow morning" if step.buffer else step.title
            self._show(overline="MORNING ROUTINE" if not step.buffer else "BUFFER", timer=_clock(step.span.end - now),
                       detail=f"{text} · until {step.span.end:%H:%M}{tail} · work starts {routine.end:%H:%M}", cta=cta)
            return

        if fx.never_started:
            self._show(overline="TODAY", detail="Work was not started today.")
            return

        if state is None:
            self.set_visible(False)
            return

        if state.phase is Phase.WAITING:
            when = f" · about {state.projected_end:%H:%M} if you start now" if state.projected_end else ""
            self._show(overline="READY WHEN YOU ARE",
                       detail=f"{human_duration(state.target)} of focus is waiting{when}.",
                       cta=("Start work", self._start_work))
            return

        if state.phase is Phase.ENDED:
            started = f"Started {state.started_at:%H:%M} · " if state.started_at else ""
            ended = f"ended {state.ended_at:%H:%M}" if state.ended_at else "ended at bedtime"
            self._show(overline="WORK ENDED", detail=f"{started}{ended} · {human_duration(state.worked)} of focus.",
                       buttons=(self.settle, self.plan, self.resume) if state.ended_at else ())
            return

        if not fs.use_blocks:  # the ordinary pomodoro card runs the blocks; this one only holds End work
            self._show(overline=f"WORK STARTED {state.started_at:%H:%M}",
                       detail=f"{human_duration(state.worked)} of {human_duration(state.target)} focused so far.",
                       buttons=(self.end,))
            return

        self._render_blocks(state, now)

    def _render_blocks(self, state, now) -> None:
        pausing = any(p.open for p in self._view.pauses)
        worked = f"{human_duration(state.worked)} of {human_duration(state.target)} focused"
        if state.phase is Phase.READY:
            kind = state.next_kind
            word = "focus block" if kind is SegmentKind.FOCUS else kind.label.lower()
            number = f" {state.focus_blocks + 1}" if kind is SegmentKind.FOCUS else ""
            since = f" · stopped {_ago(now - state.idle_since)}" if state.idle_since else ""
            done = " Today’s focus is done: end work, or keep going." if state.target_reached else ""
            self.end.remove_css_class("suggested-action")
            if state.target_reached:
                self.end.add_css_class("suggested-action")
            self._show(overline=f"NEXT: {kind.label.upper()}{number}", timer=f"{state.nominal:02d}:00",
                       detail=f"{worked}{since}.{done}", cta=(f"Start {word}{number}", self._start_block),
                       buttons=(self.end,))
            return

        current = state.current
        left = state.left
        over = state.over
        if pausing:
            head = "PAUSED"
        elif current.kind is SegmentKind.FOCUS:
            head = f"FOCUS {state.focus_blocks}" + (" · OVER" if over else "")
        else:
            head = current.kind.label.upper() + (" · OVER" if over else "")
        timer = ("+" + _clock(-left)) if over else _clock(left)
        extra = ""
        if over:
            extra = f" Past the planned {state.nominal} min: carry on, or stop when you are ready."
        pace = f" · about {state.projected_end:%H:%M} at this pace" if state.projected_end and current.kind is SegmentKind.FOCUS else ""
        self._show(overline=head, timer=timer,
                   detail=f"Started {current.start:%H:%M} · {worked}{pace}.{extra}",
                   buttons=(self.stop, self.pause, self.end))
        self.stop.set_label("Stop focus" if current.kind is SegmentKind.FOCUS else "Stop break")
        (self.stop.add_css_class if over else self.stop.remove_css_class)("suggested-action")
        self.pause.set_label("Resume" if pausing else "Pause")
        (self.pause.add_css_class if pausing else self.pause.remove_css_class)("suggested-action")

    # -- buttons ---------------------------------------------------------------

    def _done(self, ok: bool, problem: str = "") -> None:
        if not ok and problem:
            self.ctx.toast(problem)
        self.ctx.changed("pomodoro")

    def _on_cta(self, _button) -> None:
        if self._action:
            self._action()

    def _start_work(self) -> None:
        self._done(planner.start_work(self.ctx.db, self.ctx.library, clock_now()), "Work was already started or ended today.")

    def _start_block(self) -> None:
        self._done(planner.start_block(self.ctx.db, self.ctx.library, clock_now()), "Nothing to start right now.")

    def _on_stop(self, _button) -> None:
        self._done(planner.stop_block(self.ctx.db, clock_now()), "Nothing is running.")

    def _on_pause(self, _button) -> None:
        now = clock_now()
        day = self._view.day
        if any(p.open for p in self._view.pauses):
            self.ctx.db.resume_pomodoro(day, now)
        else:
            self.ctx.db.pause_pomodoro(day, now)
        self.ctx.changed("pomodoro")

    def _on_end(self, _button) -> None:
        self._done(planner.end_work(self.ctx.db, clock_now()), "Start work first.")

    def _on_resume(self, _button) -> None:
        self._done(planner.resume_work(self.ctx.db, clock_now()))

    def _on_settle(self, _button) -> None:
        self.get_root().settle_day(self._view.day)
