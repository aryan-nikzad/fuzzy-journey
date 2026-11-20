from __future__ import annotations

from ...flex import ITEM_MINUTES_RANGE, RoutineItem, check_routine_item
from ..context import Context
from ..gi_setup import Adw, Gtk
from ..widgets import confirm
from .form import FormDialog

IDEAS = (("Wash and dress", 20), ("Breakfast", 25), ("Exercise", 30), ("Read the plan for today", 10))


class RoutineItemDialog(FormDialog):
    """Add or change one step of the morning: a name and roughly how long it takes."""

    def __init__(self, parent: Gtk.Window, ctx: Context, item: RoutineItem | None = None) -> None:
        self.ctx, self.item = ctx, item
        super().__init__(parent, "Edit step" if item else "New step", height=520)

    def build(self) -> None:
        box = Adw.PreferencesGroup(description="Roughly how long it takes is enough. The buffer covers slow mornings.")
        self.name_row = Adw.EntryRow(title="Step")
        self.name_row.set_text(self.item.title if self.item else "")
        box.add(self.name_row)
        self.minutes_row = Adw.SpinRow.new_with_range(*ITEM_MINUTES_RANGE, 5)
        self.minutes_row.set_title("Takes about (minutes)")
        self.minutes_row.set_value(self.item.minutes if self.item else 15)
        box.add(self.minutes_row)
        self.enabled_row = Adw.SwitchRow(title="Include it", subtitle="Switch off to skip it without deleting it.")
        self.enabled_row.set_active(self.item.enabled if self.item else True)
        box.add(self.enabled_row)
        self.body.append(box)
        if not self.item:
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2,
                               column_spacing=6, row_spacing=6)
            for name, minutes in IDEAS:
                button = Gtk.Button(label=f"{name} · {minutes} min")
                button.add_css_class("pill")
                button.connect("clicked", lambda _b, n=name, m=minutes: self._suggest(n, m))
                flow.append(button)
            self.body.append(flow)
        else:
            delete = Gtk.Button(label="Delete step", halign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.add_css_class("pill")
            delete.connect("clicked", self._delete)
            self.body.append(delete)
        self.name_row.grab_focus()

    def _suggest(self, name: str, minutes: int) -> None:
        self.name_row.set_text(name)
        self.minutes_row.set_value(minutes)

    def _delete(self, _button) -> None:
        def go() -> None:
            self.ctx.db.delete_routine_item(self.item.id)
            self.ctx.changed("flex")
            self.close()

        confirm(self, f"Delete “{self.item.title}”?", "The step is removed from your morning.", "Delete", go)

    def save(self) -> bool:
        title, minutes = self.name_row.get_text().strip(), int(self.minutes_row.get_value())
        problem = check_routine_item(title, minutes)
        if problem:
            self.error(problem)
            return False
        item = self.item or RoutineItem(title, minutes)
        item.title, item.minutes, item.enabled = title, minutes, self.enabled_row.get_active()
        try:
            self.ctx.db.save_routine_item(item)
        except ValueError as error:
            self.error(str(error))
            return False
        self.ctx.changed("flex")
        return True
