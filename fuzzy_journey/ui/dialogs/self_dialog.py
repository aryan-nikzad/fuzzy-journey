from __future__ import annotations

from ...goals import SELF_EXAMPLES, SelfStatement, check_self
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import confirm, label
from .form import FormDialog, group


class SelfDialog(FormDialog):
    """Add or edit one statement of who you are, said in the present tense. An existing one can be moved or deleted."""

    def __init__(self, parent: Gtk.Window, ctx: Context, item: SelfStatement | None = None) -> None:
        self.ctx, self.item = ctx, item
        super().__init__(parent, "Edit statement" if item else "New statement", height=560)

    def build(self) -> None:
        box = group(description="Say it as if it is already true: “I am…”, “I have…”. " + SELF_EXAMPLES)
        self.statement_row = Adw.EntryRow(title="I…")
        self.statement_row.set_text(self.item.statement if self.item else "")
        box.add(self.statement_row)
        self.body.append(box)

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12, accepts_tab=False)
        self.text.get_buffer().set_text(self.item.feeling if self.item else "")
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=130,
                                      child=self.text)
        scroller.add_css_class("card")
        self.body.append(label("How it feels (optional)", "heading"))
        self.body.append(label("What you see, do and feel when this is true.", "dim-label", wrap=True))
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

            delete = Gtk.Button(label="Delete statement", halign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.add_css_class("pill")
            delete.connect("clicked", self._delete)
            self.body.append(delete)
        self.statement_row.grab_focus()

    def _feeling(self) -> str:
        buffer = self.text.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _move(self, direction: int) -> None:
        if self.ctx.db.move_self_statement(self.item, direction):
            self.ctx.changed("self")

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_self_statement(self.item.id)
            self.ctx.changed("self")
            self.close()

        confirm(self, "Delete this statement?", f"“{self.item.statement}” will be removed. It cannot be undone.",
                "Delete", go)

    def save(self) -> bool:
        statement, feeling = self.statement_row.get_text().strip(), self._feeling().strip()
        problem = check_self(statement, feeling)
        if problem:
            self.error(problem)
            return False
        item = self.item or SelfStatement(statement, feeling)
        item.statement, item.feeling = statement, feeling
        try:
            self.ctx.db.save_self_statement(item)
        except ValueError as error:
            self.error(str(error))
            return False
        self.ctx.changed("self")
        return True
