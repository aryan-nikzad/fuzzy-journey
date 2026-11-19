from __future__ import annotations

from ...principles import RULES_INTRO, SECTION_RULES, Principle
from ..context import Context
from ..dialogs.principle_dialog import PrincipleDialog
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page


class RulesPage(Page):
    """The must-do rules of a life, written by the person. Words only: nothing here changes the schedule."""

    listens_to = frozenset({"principles"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.intro = label(RULES_INTRO, "dim-label", wrap=True)
        self.column.append(self.intro)

        self.cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.column.append(self.cards)

        add = Gtk.Button(child=Adw.ButtonContent(label="Add a rule", icon_name="list-add-symbolic"), halign=Gtk.Align.CENTER)
        add.add_css_class("pill")
        add.connect("clicked", lambda _b: self.edit(None))
        self.column.append(add)
        self.refresh()

    def edit(self, item: Principle | None) -> None:
        PrincipleDialog(self.get_root(), self.ctx, SECTION_RULES, item).present()

    def refresh(self) -> None:
        clear(self.cards)
        rules = self.ctx.db.list_principles(SECTION_RULES)
        if not rules:
            self.cards.append(label("No rules yet. Add the first one below.", "dim-label", xalign=0.5))
            return
        for rule in rules:
            self.cards.append(self._card(rule))

    def _card(self, rule: Principle) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("fj-card")

        head = Gtk.Box(spacing=8)
        title = label(rule.title, "title-4", wrap=True)
        title.set_hexpand(True)
        head.append(title)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text=f"Edit “{rule.title}”")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b, r=rule: self.edit(r))
        head.append(edit)
        card.append(head)

        for line in rule.lines:
            row = Gtk.Box(spacing=8, valign=Gtk.Align.START)
            bullet = label("•", "dim-label")
            bullet.set_valign(Gtk.Align.START)
            row.append(bullet)
            text = label(line, wrap=True)
            text.set_hexpand(True)
            row.append(text)
            card.append(row)
        return card
