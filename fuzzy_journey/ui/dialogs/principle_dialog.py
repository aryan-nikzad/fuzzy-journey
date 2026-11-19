from __future__ import annotations

from ...principles import SECTION_RECOVERY, Principle, check_principle
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import confirm, label
from .form import FormDialog, group

WORDS = {
    SECTION_RECOVERY: {
        "new": "New step", "edit": "Edit step", "title": "Step", "delete": "Delete step",
        "hint": "A short name for the step you can remember, and what to do in it.",
    },
}
DEFAULT_WORDS = {
    "new": "New rule", "edit": "Edit rule", "title": "Rule", "delete": "Delete rule",
    "hint": "A short name, then one line for each point. Each line is shown as a bullet.",
}


class PrincipleDialog(FormDialog):
    """Add or edit a rule or a recovery step; an existing one can also be moved or deleted."""

    def __init__(self, parent: Gtk.Window, ctx: Context, section: str, item: Principle | None = None) -> None:
        self.ctx, self.section, self.item = ctx, section, item
        self.words = WORDS.get(section, DEFAULT_WORDS)
        super().__init__(parent, self.words["edit"] if item else self.words["new"], height=560)

    def build(self) -> None:
        box = group(description=self.words["hint"])
        self.title_row = Adw.EntryRow(title=self.words["title"])
        self.title_row.set_text(self.item.title if self.item else "")
        box.add(self.title_row)
        self.body.append(box)

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12, accepts_tab=False)
        self.text.get_buffer().set_text(self.item.body if self.item else "")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=170,
                                      child=self.text)
        scroller.add_css_class("card")
        self.body.append(label("Text", "heading"))
        self.body.append(scroller)

        if self.item:
            order = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            up = Gtk.Button(label="Move up", icon_name="go-up-symbolic")
            down = Gtk.Button(label="Move down", icon_name="go-down-symbolic")
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

    def _text(self) -> str:
        buffer = self.text.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _move(self, direction: int) -> None:
        if self.ctx.db.move_principle(self.item, direction):
            self.ctx.changed("principles")

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_principle(self.item.id)
            self.ctx.changed("principles")
            self.close()

        confirm(self, f"Delete “{self.item.title}”?", "This text will be removed. It cannot be undone.", "Delete", go)

    def save(self) -> bool:
        title, body = self.title_row.get_text().strip(), self._text().strip()
        problem = check_principle(self.section, title, body)
        if problem:
            self.error(problem)
            return False
        item = self.item or Principle(self.section, title, body)
        item.title, item.body = title, body
        self.ctx.db.save_principle(item)
        self.ctx.changed("principles")
        return True
