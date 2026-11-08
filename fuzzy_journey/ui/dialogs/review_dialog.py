from __future__ import annotations

from datetime import date, timedelta

from ... import tasks
from ...models import TaskStatus
from ...timeutil import now as clock_now
from ..context import Context
from ..focus import minutes_text
from ..gi_setup import Adw, Gdk, GLib, Gtk


class ReviewDialog(Adw.Window):
    """Settle every task that still has no status, up to and including ``through``."""

    def __init__(self, parent: Gtk.Window, ctx: Context, through: date) -> None:
        super().__init__(transient_for=parent, modal=True, title="Settle your tasks", default_width=480, default_height=560)
        self.ctx, self.through = ctx, through

        self.page = Adw.PreferencesPage()
        self.group = Adw.PreferencesGroup(
            description="Done: finished in time. Tomorrow or Today: it did not fit, so it moves on. "
            "Cancel: it never needs doing."
        )
        self.page.add(self.group)
        self.toasts = Adw.ToastOverlay(child=self.page)
        close = Gtk.Button(label="Close")
        close.add_css_class("suggested-action")
        close.connect("clicked", lambda _b: self.close())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_end(close)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, key, *_: self.close() or True if key == Gdk.KEY_Escape else False)
        self.add_controller(keys)
        self._rows: list[Adw.ActionRow] = []
        self.refresh()

    def refresh(self) -> None:
        for row in self._rows:
            self.group.remove(row)
        self._rows = []
        pending = self.ctx.db.unset_tasks_before(self.through + timedelta(days=1))
        if not pending:
            self.ctx.toast("All tasks settled")
            self.close()
            return
        today = clock_now().date()
        for task in pending:
            length = "" if task.is_prayer else f" · {minutes_text(task.minutes)}"
            row = Adw.ActionRow(title=GLib.markup_escape_text(task.title), subtitle=f"{task.day:%A %-d %B}{length}")
            buttons = Gtk.Box(valign=Gtk.Align.CENTER)
            buttons.add_css_class("linked")
            target = max(task.day + timedelta(days=1), today)
            choices = [("Done", TaskStatus.DONE)]
            if tasks.can_carry(task):
                choices.append(("Today" if target <= today else "Tomorrow", TaskStatus.CARRIED))
            if tasks.can_cancel(task):
                choices.append(("Cancel", TaskStatus.CANCELLED))
            for text, status in choices:
                button = Gtk.Button(label=text)
                button.connect("clicked", lambda _b, t=task, s=status: self._settle(t, s))
                buttons.append(button)
            row.add_suffix(buttons)
            self.group.add(row)
            self._rows.append(row)

    def _settle(self, task, status: TaskStatus) -> None:
        self.ctx.db.set_task_status(task.id, status, today=clock_now().date())
        self.ctx.changed("tasks")
        self.refresh()
