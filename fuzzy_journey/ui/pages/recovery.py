from __future__ import annotations

from ...principles import RECOVERY_INTRO, SECTION_RECOVERY, Principle
from ..context import Context
from ..dialogs.principle_dialog import PrincipleDialog
from ..gi_setup import Adw, Gtk
from ..widgets import clear, label
from .base import Page


class RecoveryPage(Page):
    """The plan for when a day goes wrong. It is a backup of what the person already knows by heart.

    *Test myself* hides the steps so they can be said aloud from memory first, then checked one by one.
    """

    listens_to = frozenset({"principles"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.testing = False
        self._revealed: set[int] = set()

        self.column.append(label(RECOVERY_INTRO, "dim-label", wrap=True))

        bar = Gtk.Box(spacing=8)
        self.test = Gtk.ToggleButton(label="Test myself", valign=Gtk.Align.CENTER,
                                     tooltip_text="Hide the steps and say them from memory")
        self.test.connect("toggled", self._on_test)
        bar.append(Gtk.Box(hexpand=True))
        bar.append(self.test)
        self.column.append(bar)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.column.append(self.list)

        add = Gtk.Button(child=Adw.ButtonContent(label="Add a step", icon_name="list-add-symbolic"), halign=Gtk.Align.CENTER)
        add.add_css_class("pill")
        add.connect("clicked", lambda _b: self.edit(None))
        self.column.append(add)
        self.refresh()

    def edit(self, item: Principle | None) -> None:
        PrincipleDialog(self.get_root(), self.ctx, SECTION_RECOVERY, item).present()

    def _on_test(self, button: Gtk.ToggleButton) -> None:
        self.testing = button.get_active()
        self._revealed.clear()
        self.refresh()

    def _reveal(self, item: Principle) -> None:
        self._revealed.add(item.id)
        self.refresh()

    def refresh(self) -> None:
        clear(self.list)
        steps = self.ctx.db.list_principles(SECTION_RECOVERY)
        self.test.set_sensitive(bool(steps))
        if not steps:
            self.list.append(Adw.ActionRow(title="No steps yet", subtitle="Add the first step below.",
                                           activatable=False))
            return
        for number, step in enumerate(steps, start=1):
            self.list.append(self._row(number, step))

    def _row(self, number: int, step: Principle) -> Adw.ActionRow:
        hidden = self.testing and step.id not in self._revealed
        row = Adw.ActionRow(use_markup=False, subtitle_lines=0, activatable=hidden)
        number_label = label(str(number), "fj-idea-number", xalign=0.5)
        number_label.set_valign(Gtk.Align.CENTER)
        row.add_prefix(number_label)
        if hidden:
            row.set_title(f"Step {number}")
            row.set_subtitle("Say it aloud, then tap to check.")
            row.add_css_class("dim-label")
            row.connect("activated", lambda _r, s=step: self._reveal(s))
            return row
        row.set_title(step.title)
        row.set_subtitle("\n".join(step.lines))
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text=f"Edit “{step.title}”")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b, s=step: self.edit(s))
        row.add_suffix(edit)
        return row
