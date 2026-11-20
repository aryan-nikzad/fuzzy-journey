from __future__ import annotations

from ...goals import GOALS_INTRO, KIND_GREAT, KIND_HORIZON, Goal, next_horizon, reached_count
from ..context import Context
from ..dialogs.goal_dialog import GoalDialog
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page


class GoalsPage(Page):
    """One great goal, and the horizons that must be reached first, in order. Words only: nothing here changes the schedule."""

    listens_to = frozenset({"goals"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.column.append(label(GOALS_INTRO, "dim-label", wrap=True))

        self.great = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.great.add_css_class("fj-card")
        self.column.append(self.great)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head.append(label("HORIZONS", "fj-overline"))
        self.summary = label("", "caption", "dim-label", wrap=True)
        head.append(self.summary)
        self.column.append(head)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.column.append(self.list)

        add = Gtk.Button(child=Adw.ButtonContent(label="Add a horizon", icon_name="list-add-symbolic"),
                         halign=Gtk.Align.CENTER)
        add.add_css_class("pill")
        add.connect("clicked", lambda _b: self.edit(KIND_HORIZON, None))
        self.column.append(add)
        self.refresh()

    def edit(self, kind: str, item: Goal | None) -> None:
        GoalDialog(self.get_root(), self.ctx, kind, item).present()

    def refresh(self) -> None:
        self._refresh_great()
        self._refresh_horizons()

    # -- the great goal ------------------------------------------------------

    def _refresh_great(self) -> None:
        clear(self.great)
        goal = self.ctx.db.great_goal()
        self.great.append(label("THE GREAT GOAL", "fj-overline"))
        if goal is None:
            self.great.append(label("Name the one goal your life is aimed at.", "dim-label", wrap=True))
            button = Gtk.Button(child=Adw.ButtonContent(label="Set my great goal", icon_name="list-add-symbolic"),
                                halign=Gtk.Align.CENTER)
            button.add_css_class("pill")
            button.connect("clicked", lambda _b: self.edit(KIND_GREAT, None))
            self.great.append(button)
            return
        head = Gtk.Box(spacing=8)
        title = label(goal.title, "fj-idea-title", wrap=True)
        title.set_hexpand(True)
        head.append(title)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.START,
                          tooltip_text=f"Edit “{goal.title}”")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b, g=goal: self.edit(KIND_GREAT, g))
        head.append(edit)
        self.great.append(head)
        if goal.note:
            self.great.append(label(goal.note, wrap=True))

    # -- the horizons --------------------------------------------------------

    def _refresh_horizons(self) -> None:
        clear(self.list)
        horizons = self.ctx.db.horizons()
        reached, total = reached_count(horizons)
        if not horizons:
            self.summary.set_text("What must be true first, in the order you will reach them. None yet.")
            self.list.set_visible(False)
            return
        self.list.set_visible(True)
        self.summary.set_text(f"{reached} of {total} reached. The one marked is next.")
        upcoming = next_horizon(horizons)
        for number, horizon in enumerate(horizons, start=1):
            self.list.append(self._row(number, horizon, upcoming is not None and horizon.id == upcoming.id))

    def _row(self, number: int, horizon: Goal, is_next: bool) -> Gtk.Widget:
        row = Adw.ActionRow(title=horizon.title, subtitle=horizon.note, use_markup=False, subtitle_lines=0)
        row.set_title_lines(0)
        badge = label(str(number), "fj-idea-number", xalign=0.5)
        badge.set_valign(Gtk.Align.CENTER)
        row.add_prefix(badge)

        done = Gtk.CheckButton(active=horizon.reached, valign=Gtk.Align.CENTER, tooltip_text="Reached")
        done.connect("toggled", lambda b, h=horizon: self._reached(h, b.get_active()))
        row.add_suffix(done)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text=f"Edit “{horizon.title}”")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b, h=horizon: self.edit(KIND_HORIZON, h))
        row.add_suffix(edit)

        if horizon.reached:
            row.add_css_class("fj-settled")
            row.add_css_class("fj-keep")
        elif is_next:
            row.add_css_class("fj-now")
        return row

    def _reached(self, horizon: Goal, value: bool) -> None:
        self.ctx.db.set_horizon_reached(horizon.id, value)
        self.ctx.changed("goals")
