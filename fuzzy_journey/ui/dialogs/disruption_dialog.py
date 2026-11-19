from __future__ import annotations

from datetime import date

from ...rhythm import DayKind, plan_day
from ...timeutil import human_duration
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import label
from .form import FormDialog, group


class DisruptionDialog(FormDialog):
    """Switch a day to Disruption mode: for the bad, unpredictable days (a cold, a death in the family).

    The first choice keeps a quarter of a normal day's work and leaves the rest empty. Prayers, exercise,
    reading and the rest of the routine carry on as planned. The second is the fuller fallback: no work,
    stay home, computer off. Either can be undone from Today with *Back to normal*.
    """

    def __init__(self, parent: Gtk.Window, ctx: Context, day: date, current: DayKind | None = None) -> None:
        self.ctx, self.day = ctx, day
        self.current = current if current and current.is_disruption else DayKind.DISRUPTION
        self.prayer = ctx.library.day(ctx.location.slug, day)
        super().__init__(parent, "A hard day", save_label="Switch", height=560)

    def build(self) -> None:
        self.body.append(label(
            "For a day when something bad and unpredictable happens, such as an illness or losing someone you love. "
            "You do not have to work at full strength. You choose how much of the day to keep.",
            "dim-label", wrap=True,
        ))

        choices = group()
        self.quarter = Gtk.CheckButton()
        self.offline = Gtk.CheckButton(group=self.quarter)
        self.quarter_row = Adw.ActionRow(title="Work 25%", subtitle_lines=0, activatable_widget=self.quarter)
        self.quarter_row.add_prefix(self.quarter)
        self.quarter_row.set_subtitle(
            "A quarter of a normal day's work; the other three quarters stay empty. Prayers, exercise, reading "
            "and the rest of your routine carry on as planned."
        )
        offline_row = Adw.ActionRow(title="Stay home, computer off", subtitle_lines=0, activatable_widget=self.offline)
        offline_row.add_prefix(self.offline)
        offline_row.set_subtitle(
            "No work at all. Rest, sleep, or stay awake, with the computer off. "
            "If you do not want to do the gym or anything else today, you may skip it."
        )
        for row in (self.quarter_row, offline_row):
            choices.add(row)
        self.body.append(choices)
        (self.offline if self.current is DayKind.OFFLINE else self.quarter).set_active(True)
        self.quarter.connect("toggled", self._preview)

        self.note = label("", "caption", "dim-label", wrap=True)
        self.body.append(self.note)
        self.body.append(label(
            "Neutral for the bank. Tasks that no longer fit are not pushed into tomorrow automatically: "
            "you settle them yourself. Back to normal is one click on Today.",
            "caption", "dim-label", wrap=True,
        ))
        self._preview()

    @property
    def chosen(self) -> DayKind:
        return DayKind.DISRUPTION if self.quarter.get_active() else DayKind.OFFLINE

    def _preview(self, *_args) -> None:
        if not self.quarter.get_active():
            self.note.set_text("Nothing is planned for work. The day's prayer times still shape it.")
            return
        if not self.prayer:
            self.note.set_text("")
            return
        plan = plan_day(self.day, DayKind.DISRUPTION, fajr=self.prayer.fajr, isha=self.prayer.isha,
                        evening_start=self.ctx.settings.evening_start, flex=self.ctx.settings.flex)
        text = f"{human_duration(plan.target)} of work"
        if plan.morning:
            text += f", {plan.morning.start:%H:%M} to {plan.morning.end:%H:%M}"
        self.note.set_text(text + ".")

    def save(self) -> bool:
        existing = self.ctx.db.day_entries(self.day, self.day).get(self.day)
        self.ctx.db.set_day_kind(self.day, self.chosen, existing.note if existing else "")
        self.ctx.changed("day")
        return True
