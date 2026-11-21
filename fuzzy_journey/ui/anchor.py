from __future__ import annotations

from datetime import date

from ..goals import ANCHOR_OFF, ANCHOR_SHOW, next_horizon, statement_of_the_day
from .context import Context
from .gi_setup import Gtk
from .widgets import label


class AnchorCard(Gtk.Box):
    """Your great goal and one self-image statement for the day, on Today.

    The plan should live in your head, not on a screen, so by default the card only *asks* you to say them
    aloud and shows them when you tap (the practice Recall is built on). Preferences can show them outright
    or hide the card. It is only a reading of your own words: it never changes the day.
    """

    def __init__(self, ctx: Context) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, visible=False)
        self.ctx = ctx
        self.add_css_class("fj-card")
        self.add_css_class("fj-compact")
        self._revealed_on: date | None = None
        self._tappable = False
        self.title = label("", "heading", wrap=True)
        self.sub = label("", "caption", "dim-label", wrap=True)
        self.goal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.goal_line = label("", "title-4", wrap=True)
        self.next_line = label("", "caption", "dim-label", wrap=True)
        self.goal_box.append(label("MY GOAL", "fj-overline"))
        self.goal_box.append(self.goal_line)
        self.goal_box.append(self.next_line)
        self.self_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=8)
        self.self_line = label("", "title-4", wrap=True)
        self.self_box.append(label("WHO I AM", "fj-overline"))
        self.self_box.append(self.self_line)
        for widget in (self.title, self.sub, self.goal_box, self.self_box):
            self.append(widget)
        tap = Gtk.GestureClick()
        tap.connect("released", self._on_tap)
        self.add_controller(tap)

    # -- state ---------------------------------------------------------------

    @property
    def revealed(self) -> bool:
        return self._revealed_on is not None

    def _on_tap(self, *_args) -> None:
        if not self._tappable:
            return
        self._revealed_on = None if self.revealed else self._day
        self.update(self._day)

    # -- rendering -----------------------------------------------------------

    def update(self, day: date) -> None:
        self._day = day
        mode = self.ctx.settings.anchor_mode
        great = self.ctx.db.great_goal()
        statement = statement_of_the_day(self.ctx.db.list_self_image(), day)
        if mode == ANCHOR_OFF or (great is None and statement is None):
            self.set_visible(False)  # nothing is invented: with no words of yours there is no card
            self._tappable = False
            return
        self.set_visible(True)
        if self._revealed_on != day:
            self._revealed_on = None  # a new day asks again
        show = mode == ANCHOR_SHOW or self.revealed
        self._tappable = mode != ANCHOR_SHOW
        self.set_cursor_from_name("pointer" if self._tappable else None)

        self.title.set_visible(not show)
        self.sub.set_visible(not show)
        self.goal_box.set_visible(show and great is not None)
        self.self_box.set_visible(show and statement is not None)
        if show:
            if great:
                self.goal_line.set_text(great.title)
                upcoming = next_horizon(self.ctx.db.horizons())
                self.next_line.set_text(f"Next: {upcoming.title}" if upcoming else "")
                self.next_line.set_visible(upcoming is not None)
            if statement:
                self.self_line.set_text(statement.statement)
            if self._tappable:
                self.sub.set_visible(True)
                self.sub.set_text("Tap to hide.")
                # keep the hint below the words
                self.reorder_child_after(self.sub, self.self_box if statement else self.goal_box)
        else:
            if great and statement:
                self.title.set_text("Your goal, and who you are")
            else:
                self.title.set_text("Your goal" if great else "Who you are")
            self.sub.set_text("Say it aloud from memory, then tap to check.")
