from __future__ import annotations

from ...habits import BUILD, KIND_LABELS, KINDS, QUIT, SUGGESTIONS, Habit, check_habit
from ...timeutil import now as clock_now
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import DateButton, confirm, label
from .form import FormDialog, group


class HabitDialog(FormDialog):
    """Add a habit, or change one: its name, whether you want to quit or build it, and when counting starts.

    An existing habit can also be moved in the list or deleted (which removes its marked days too).
    Changing the *Counting from* date never erases a day: it only changes what the figures include.
    """

    def __init__(self, parent: Gtk.Window, ctx: Context, habit: Habit | None = None) -> None:
        self.ctx, self.habit = ctx, habit
        super().__init__(parent, "Edit habit" if habit else "New habit", height=640)

    def build(self) -> None:
        box = group(description="Name it in your own words. Quit: something you want to do less. "
                                "Build: something you want to do more.")
        self.name_row = Adw.EntryRow(title="Habit")
        self.name_row.set_text(self.habit.name if self.habit else "")
        box.add(self.name_row)

        self.kind_row = Adw.ComboRow(title="I want to")
        self.kind_row.set_model(Gtk.StringList.new([KIND_LABELS[k] for k in KINDS]))
        self.kind_row.set_selected(KINDS.index(self.habit.kind) if self.habit else KINDS.index(QUIT))
        box.add(self.kind_row)

        start_row = Adw.ActionRow(
            title="Counting from",
            subtitle="Only changes what the figures include. Earlier days keep their marks.",
            subtitle_lines=0,
        )
        self.start = DateButton(self.habit.start if self.habit else clock_now().date())
        start_row.add_suffix(self.start)
        box.add(start_row)
        self.body.append(box)

        if not self.habit:
            self.body.append(label("Ideas", "heading"))
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                               column_spacing=6, row_spacing=6, homogeneous=False)
            for name, kind in SUGGESTIONS:
                button = Gtk.Button(label=f"{name} ({'build' if kind == BUILD else 'quit'})")
                button.add_css_class("pill")
                button.connect("clicked", lambda _b, n=name, k=kind: self._suggest(n, k))
                flow.append(button)
            self.body.append(flow)
        else:
            order = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            for text, icon, direction in (("Move up", "go-up-symbolic", -1), ("Move down", "go-down-symbolic", 1)):
                button = Gtk.Button(child=Adw.ButtonContent(label=text, icon_name=icon))
                button.add_css_class("flat")
                button.connect("clicked", lambda _b, d=direction: self._move(d))
                order.append(button)
            self.body.append(order)
            delete = Gtk.Button(label="Delete habit", halign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.add_css_class("pill")
            delete.connect("clicked", self._delete)
            self.body.append(delete)
        self.name_row.grab_focus()

    def _suggest(self, name: str, kind: str) -> None:
        self.name_row.set_text(name)
        self.kind_row.set_selected(KINDS.index(kind))

    def _move(self, direction: int) -> None:
        if self.ctx.db.move_habit(self.habit, direction):
            self.ctx.changed("habits")

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_habit(self.habit.id)
            self.ctx.changed("habits")
            self.close()

        confirm(self, f"Delete “{self.habit.name}”?",
                "The habit and every day you marked for it are removed. This cannot be undone.", "Delete", go)

    def save(self) -> bool:
        name, kind = self.name_row.get_text().strip(), KINDS[self.kind_row.get_selected()]
        problem = check_habit(name, kind)
        if problem:
            self.error(problem)
            return False
        habit = self.habit or Habit(name, kind, self.start.date)
        habit.name, habit.kind, habit.start = name, kind, self.start.date
        try:
            self.ctx.db.save_habit(habit)
        except ValueError as error:
            self.error(str(error))
            return False
        self.ctx.changed("habits")
        return True
