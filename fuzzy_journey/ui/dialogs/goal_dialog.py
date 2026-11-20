from __future__ import annotations

from ...goals import KIND_GREAT, KIND_HORIZON, Goal, check_goal
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import confirm, label
from .form import FormDialog, group

WORDS = {
    KIND_GREAT: {
        "new": "Great goal", "edit": "Great goal", "title": "My great goal", "delete": "Remove great goal",
        "hint": "The one goal your whole life is aimed at. Say it in your own words.",
        "note": "Why it matters",
    },
    KIND_HORIZON: {
        "new": "New horizon", "edit": "Edit horizon", "title": "Horizon", "delete": "Delete horizon",
        "hint": "Something that must be true before the great goal is possible.",
        "note": "What it means, and how I will know it is reached",
    },
}


class GoalDialog(FormDialog):
    """Add or edit the great goal or a horizon; a horizon can also be marked reached, moved or deleted."""

    def __init__(self, parent: Gtk.Window, ctx: Context, kind: str, item: Goal | None = None) -> None:
        self.ctx, self.kind, self.item = ctx, kind, item
        self.words = WORDS[kind]
        super().__init__(parent, self.words["edit"] if item else self.words["new"], height=600)

    def build(self) -> None:
        box = group(description=self.words["hint"])
        self.title_row = Adw.EntryRow(title=self.words["title"])
        self.title_row.set_text(self.item.title if self.item else "")
        box.add(self.title_row)
        self.body.append(box)

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12, accepts_tab=False)
        self.text.get_buffer().set_text(self.item.note if self.item else "")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=150,
                                      child=self.text)
        scroller.add_css_class("card")
        self.body.append(label(self.words["note"], "heading"))
        self.body.append(scroller)

        self.reached = None
        if self.kind == KIND_HORIZON:
            switches = group()
            self.reached = Adw.SwitchRow(title="Reached")
            self.reached.set_active(bool(self.item and self.item.reached))
            switches.add(self.reached)
            self.body.append(switches)

        if self.item:
            if self.kind == KIND_HORIZON:
                order = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
                up = Gtk.Button(label="Reached earlier", icon_name="go-up-symbolic")
                down = Gtk.Button(label="Reached later", icon_name="go-down-symbolic")
                up.connect("clicked", lambda _b: self._move(-1))
                down.connect("clicked", lambda _b: self._move(1))
                for button in (up, down):
                    button.add_css_class("flat")
                    order.append(button)
                self.body.append(order)

            delete = Gtk.Button(label=self.words["delete"], halign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.add_css_class("pill")
            delete.connect("clicked", self._delete)
            self.body.append(delete)
        self.title_row.grab_focus()

    def _note(self) -> str:
        buffer = self.text.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _move(self, direction: int) -> None:
        if self.ctx.db.move_horizon(self.item, direction):
            self.ctx.changed("goals")

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_goal(self.item.id)
            self.ctx.changed("goals")
            self.close()

        confirm(self, f"Delete “{self.item.title}”?", "These words will be removed. It cannot be undone.", "Delete", go)

    def save(self) -> bool:
        title, note = self.title_row.get_text().strip(), self._note().strip()
        problem = check_goal(self.kind, title, note)
        if problem:
            self.error(problem)
            return False
        goal = self.item or Goal(self.kind, title, note)
        goal.title, goal.note = title, note
        if self.reached is not None:
            goal.reached = self.reached.get_active()
        try:
            self.ctx.db.save_goal(goal)
        except ValueError as error:
            self.error(str(error))
            return False
        self.ctx.changed("goals")
        return True
