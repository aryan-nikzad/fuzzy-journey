from __future__ import annotations

from datetime import date

from ... import tasks
from ...models import TASK_LEVELS, Task
from ...pomodoro import recommended
from ..context import Context
from ..focus import minutes_text
from ..gi_setup import Adw, Gtk
from ..widgets import label
from .form import FormDialog, group


class TaskDialog(FormDialog):
    """Add or edit a task. A day's tasks may never add up to more than its focus time."""

    def __init__(self, parent: Gtk.Window, ctx: Context, day: date, focus_minutes: int, task: Task | None = None) -> None:
        self.ctx, self.day, self.focus, self.task = ctx, day, focus_minutes, task
        self.others = [t for t in ctx.db.tasks_on(day) if not task or t.id != task.id]
        super().__init__(parent, "Edit task" if task else "New task", height=420)

    def build(self) -> None:
        box = group()
        self.title_row = Adw.EntryRow(title="Task")
        self.title_row.set_text(self.task.title if self.task else "")
        self.title_row.connect("entry-activated", lambda *_: self._on_save(None))
        box.add(self.title_row)

        self.length = Adw.SpinRow.new_with_range(tasks.MIN_MINUTES, tasks.MAX_MINUTES, tasks.STEP_MINUTES)
        self.length.set_title("Length in minutes")
        self.length.set_snap_to_ticks(True)
        self.length.set_value(self.task.minutes if self.task else 30)
        self.length.connect("notify::value", self._on_length)
        box.add(self.length)

        self.level = None
        if self.ctx.settings.task_order == tasks.ORDER_LEVEL:
            self.level = Adw.ComboRow(title="Importance")
            self.level.set_model(Gtk.StringList.new(list(TASK_LEVELS.values())))
            self.level.set_selected((self.task.level if self.task else 2) - 1)
            box.add(self.level)
        self.body.append(box)

        self.note = label("", "caption", "dim-label", wrap=True)
        self.body.append(self.note)
        self._on_length()
        self.title_row.grab_focus()

    def _minutes(self) -> int:
        return int(round(self.length.get_value() / tasks.STEP_MINUTES)) * tasks.STEP_MINUTES

    def _on_length(self, *_args) -> None:
        minutes = self._minutes()
        self.length.set_subtitle(minutes_text(minutes))
        used = tasks.load(self.others, self.focus).planned
        left = max(0, self.focus - used)
        text = f"{minutes_text(left)} of focus time left on this day."
        if self.focus and used + minutes > recommended(self.focus):
            text += " Above the recommended 90%: if a task runs long, there is no room to absorb it."
        self.note.set_text(text if self.focus else "This day has no focus time to plan.")

    def save(self) -> bool:
        minutes, title = self._minutes(), self.title_row.get_text().strip()
        # Editing a task without making it longer is always allowed, even on a day that is already full.
        limit = self.focus if not self.task or minutes > self.task.minutes else 10**6
        problem = tasks.check_task(title, minutes, self.others, limit)
        if problem:
            self.error(problem)
            return False
        task = self.task or Task(title, minutes, self.day)
        task.title, task.minutes = title, minutes
        if self.level is not None:
            task.level = int(self.level.get_selected()) + 1
        self.ctx.db.save_task(task)
        self.ctx.changed("tasks")
        return True
