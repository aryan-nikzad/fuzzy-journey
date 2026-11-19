from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ...principles import SECTION_RECOVERY, SECTION_RULES
from ...tasks import PRAYERS
from ...timeutil import mask_label
from ...timeutil import now as clock_now
from ..context import Context
from ..focus import minutes_text
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page

HINT = "Say it aloud, then tap to check."


@dataclass
class Item:
    """One thing to remember: what the cue says while hidden, and what it really is."""

    key: str
    cue: str
    title: str
    detail: str = ""
    hint: str = HINT


class RecallRow(Adw.ActionRow):
    def __init__(self, item: Item, shown: set[str], section: str) -> None:
        super().__init__(use_markup=False, subtitle_lines=0, activatable=True)
        self.item, self.shown, self.token = item, shown, f"{section}:{item.key}"
        self.connect("activated", lambda _r: self.set_revealed(self.token not in self.shown))
        self.set_revealed(self.token in self.shown)

    @property
    def revealed(self) -> bool:
        return self.token in self.shown

    def set_revealed(self, value: bool) -> None:
        (self.shown.add if value else self.shown.discard)(self.token)
        if value:
            self.set_title(self.item.title)
            self.set_subtitle(self.item.detail)
            self.remove_css_class("dim-label")
        else:
            self.set_title(self.item.cue)
            self.set_subtitle(self.item.hint)
            self.add_css_class("dim-label")


class RecallPage(Page):
    """Test myself on everything the app knows about the day and the life that you must know yourself.

    Nothing is graded and nothing is stored: each thing is hidden, you say it aloud, then tap to check.
    The plan lives in your head; this page is how you keep it there.
    """

    listens_to = frozenset({"principles", "tasks", "alarms", "rhythm", "day", "data", "location"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._shown: set[str] = set()
        self.column.append(label(
            "Everything here is hidden. Say each one aloud from memory, then tap it to check. "
            "Nothing is graded: you are the judge. Your plan should live in your head, not on a screen.",
            "dim-label", wrap=True,
        ))
        bar = Gtk.Box(halign=Gtk.Align.END)
        self.hide_all = Gtk.Button(label="Hide everything")
        self.hide_all.add_css_class("flat")
        self.hide_all.connect("clicked", self._hide_all)
        bar.append(self.hide_all)
        self.column.append(bar)
        self.groups = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.column.append(self.groups)
        self._rows: list[RecallRow] = []
        self.refresh()

    def _hide_all(self, _button) -> None:
        for row in self._rows:
            row.set_revealed(False)

    # -- what there is to remember -------------------------------------------

    def sections(self) -> list[tuple[str, list[Item]]]:
        db, ctx = self.ctx.db, self.ctx
        today = clock_now().date()
        tomorrow = today + timedelta(days=1)
        out: list[tuple[str, list[Item]]] = []

        rules = db.list_principles(SECTION_RULES)
        out.append(("My rules", [Item(str(r.id), f"Rule {n}", r.title, "\n".join(r.lines))
                                 for n, r in enumerate(rules, start=1)]))
        steps = db.list_principles(SECTION_RECOVERY)
        out.append(("Recovery plan", [Item(str(s.id), f"Step {n}", s.title, "\n".join(s.lines))
                                      for n, s in enumerate(steps, start=1)]))

        view = ctx.today_view()
        shape: list[Item] = []
        if view.wake:
            shape.append(Item("wake", "Wake", f"Wake {view.wake:%H:%M}", hint="What time?"))
        for number, work in enumerate(view.work, start=1):
            start, end = work.progress.start, work.progress.end
            shape.append(Item(f"work{number}", f"Work {number}", f"{work.title} {start:%H:%M}–{end:%H:%M}",
                              hint="When?"))
        if view.bedtime:
            shape.append(Item("bed", "Bedtime", f"Bed {view.bedtime:%H:%M}", hint="What time?"))
        out.append(("Today’s shape", shape))

        for title, day in (("Today’s tasks", today), ("Tomorrow’s tasks", tomorrow)):
            items = [t for t in db.tasks_on(day, prayers=False) if t.status.value != "cancelled"]
            out.append((title, [Item(str(t.id), f"Task {n}", t.title, minutes_text(t.minutes))
                                for n, t in enumerate(items, start=1)]))

        if ctx.settings.show_prayers:
            prayer_day = ctx.library.day(ctx.location.slug, today)
            times = prayer_day.times if prayer_day else {}
            out.append(("Prayers today", [
                Item(name, name, f"{name} {times[name]:%H:%M}", hint="What time today?")
                for name in PRAYERS if times.get(name)
            ]))

        reminders = [a for a in db.list_alarms() if a.enabled]
        out.append(("Reminders", [
            Item(str(a.id), f"Reminder {n}", a.title,
                 f"{a.clock:%H:%M} · " + (f"once, {a.one_shot_date}" if a.one_shot_date else mask_label(a.days_mask)))
            for n, a in enumerate(reminders, start=1)
        ]))
        routine = [a for a in db.list_activities() if a.enabled]
        out.append(("Routine", [
            Item(str(a.id), f"Activity {n}", a.title, f"{a.start}–{a.end} · {mask_label(a.days_mask)}")
            for n, a in enumerate(routine, start=1)
        ]))
        return [(name, items) for name, items in out if items]

    # -- rendering ------------------------------------------------------------

    def refresh(self) -> None:
        clear(self.groups)
        self._rows = []
        sections = self.sections()
        self.hide_all.set_sensitive(bool(sections))
        for name, items in sections:
            group = Adw.PreferencesGroup(title=name)
            rows = [RecallRow(item, self._shown, name) for item in items]
            toggle = Gtk.Button(label="Show all", valign=Gtk.Align.CENTER)
            toggle.add_css_class("flat")
            toggle.connect("clicked", lambda _b, rs=rows: self._flip(rs))
            group.set_header_suffix(toggle)
            for row in rows:
                group.add(row)
            self._rows += rows
            self.groups.append(group)

    @staticmethod
    def _flip(rows: list[RecallRow]) -> None:
        reveal = not all(r.revealed for r in rows)
        for row in rows:
            row.set_revealed(reveal)
