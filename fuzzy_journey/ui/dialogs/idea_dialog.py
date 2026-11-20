from __future__ import annotations

from ...ideas import Idea, check_idea
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import confirm, label
from .form import FormDialog, group


class IdeaDialog(FormDialog):
    """Fill in an idea when you have time: its wording and an optional note. Also move or delete it.

    Capturing an idea never needs this window (type it on the Ideas page and press Enter); it is only for
    when you want to say more.
    """

    def __init__(self, parent: Gtk.Window, ctx: Context, idea: Idea) -> None:
        self.ctx, self.idea = ctx, idea
        super().__init__(parent, "Edit idea", height=560)

    def build(self) -> None:
        box = group(description="Say more about it now or later. Only the idea itself is needed.")
        self.title_row = Adw.EntryRow(title="Idea")
        self.title_row.set_text(self.idea.title)
        box.add(self.title_row)
        self.body.append(box)

        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12, accepts_tab=False)
        self.text.get_buffer().set_text(self.idea.note)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=170,
                                      child=self.text)
        scroller.add_css_class("card")
        self.body.append(label("Note (optional)", "heading"))
        self.body.append(scroller)

        order = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        for text, icon, direction in (("Move up", "go-up-symbolic", -1), ("Move down", "go-down-symbolic", 1)):
            button = Gtk.Button(child=Adw.ButtonContent(label=text, icon_name=icon))
            button.add_css_class("flat")
            button.connect("clicked", lambda _b, d=direction: self._move(d))
            order.append(button)
        self.body.append(order)

        delete = Gtk.Button(label="Delete idea", halign=Gtk.Align.CENTER)
        delete.add_css_class("destructive-action")
        delete.add_css_class("pill")
        delete.connect("clicked", self._delete)
        self.body.append(delete)
        self.title_row.grab_focus()

    def _note(self) -> str:
        buffer = self.text.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _move(self, direction: int) -> None:
        if self.ctx.db.move_idea(self.idea, direction):
            self.ctx.changed("ideas")

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_idea(self.idea.id)
            self.ctx.changed("ideas")
            self.close()

        confirm(self, f"Delete “{self.idea.title}”?", "This idea will be removed. It cannot be undone.", "Delete", go)

    def save(self) -> bool:
        title, note = self.title_row.get_text().strip(), self._note().strip()
        problem = check_idea(title, note)
        if problem:
            self.error(problem)
            return False
        self.idea.title, self.idea.note = title, note
        try:
            self.ctx.db.save_idea(self.idea)
        except ValueError as error:
            self.error(str(error))
            return False
        self.ctx.changed("ideas")
        return True
