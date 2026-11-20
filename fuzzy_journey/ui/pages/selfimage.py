from __future__ import annotations

from ...goals import SELF_EXAMPLES, SELF_INTRO, SelfStatement
from ..context import Context
from ..dialogs.self_dialog import SelfDialog
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page


class SelfImagePage(Page):
    """Who you are, said in the present tense so it can be felt. Words only: nothing here changes the schedule."""

    listens_to = frozenset({"self"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.column.append(label(SELF_INTRO, "dim-label", wrap=True))

        self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.column.append(self.cards)

        add = Gtk.Button(child=Adw.ButtonContent(label="Add a statement", icon_name="list-add-symbolic"),
                         halign=Gtk.Align.CENTER)
        add.add_css_class("pill")
        add.connect("clicked", lambda _b: self.edit(None))
        self.column.append(add)
        self.refresh()

    def edit(self, item: SelfStatement | None) -> None:
        SelfDialog(self.get_root(), self.ctx, item).present()

    def refresh(self) -> None:
        clear(self.cards)
        items = self.ctx.db.list_self_image()
        if not items:
            self.cards.append(label("Nothing here yet. Think about who you want to be, then say it as if you already are.",
                                    "dim-label", xalign=0.5, wrap=True))
            self.cards.append(label(SELF_EXAMPLES, "caption", "dim-label", xalign=0.5, wrap=True))
            return
        for item in items:
            self.cards.append(self._card(item))

    def _card(self, item: SelfStatement) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("fj-card")
        head = Gtk.Box(spacing=8)
        text = label(item.statement, "title-3", wrap=True)
        text.set_hexpand(True)
        head.append(text)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.START,
                          tooltip_text="Edit this statement")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b, i=item: self.edit(i))
        head.append(edit)
        card.append(head)
        if item.feeling:
            card.append(label(item.feeling, "dim-label", wrap=True))
        return card
