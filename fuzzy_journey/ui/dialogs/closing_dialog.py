from __future__ import annotations

from datetime import date, timedelta

from ... import planner, tasks
from ...models import TaskStatus
from ...rhythm import DayKind
from ...timeutil import now as clock_now
from ..context import Context
from ..focus import minutes_text
from ..gi_setup import Adw, GLib, Gtk


class ClosingDialog(Adw.Window):
    """The planning slot: say what happened to today's tasks, then look at tomorrow.

    It opens by itself when the day's work is over and tasks are still open (or from the
    planning card). Today's tasks are asked for firmly: each is Done, moved to tomorrow or
    cancelled. If the day simply went elsewhere, an evening block can give the focus time back.
    Leaving is always possible, but takes a second, deliberate click; escaping the window just
    asks again in half an hour.
    """

    def __init__(self, parent: Gtk.Window, ctx: Context, day: date) -> None:
        super().__init__(transient_for=parent, modal=True, title="Close today’s work", default_width=500, default_height=640)
        self.ctx, self.day = ctx, day
        self._resolved = False
        self._rows: list[Gtk.Widget] = []

        self.page = Adw.PreferencesPage()
        self.intro = Adw.PreferencesGroup()
        self.group = Adw.PreferencesGroup(
            description="Done: finished in time. Tomorrow: it did not fit, so it moves on. Cancel: it never needs doing."
        )
        self.evening_group = Adw.PreferencesGroup()
        self.evening_row = Adw.ActionRow(
            title="Work this evening instead",
            subtitle="Not recommended. Adds focus time at your evening start and costs sleep. Useful when the day went elsewhere.",
            subtitle_lines=3,
        )
        add = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        add.connect("clicked", self._on_evening)
        self.evening_row.add_suffix(add)
        self.evening_group.add(self.evening_row)
        self.tomorrow_group = Adw.PreferencesGroup(title="Tomorrow")
        self.tomorrow_row = Adw.ActionRow(subtitle_lines=3)
        plan = Gtk.Button(label="Plan tomorrow", valign=Gtk.Align.CENTER)
        plan.connect("clicked", self._on_plan)
        self.tomorrow_row.add_suffix(plan)
        self.tomorrow_group.add(self.tomorrow_row)
        for g in (self.intro, self.group, self.evening_group, self.tomorrow_group):
            self.page.add(g)

        self.status = Adw.ActionRow(activatable=False)
        self.intro.add(self.status)

        later = Gtk.Button(label="Ask me in 30 min")
        later.connect("clicked", self._on_later)
        self.close_button = Gtk.Button(label="Close the day")
        self.close_button.add_css_class("suggested-action")
        self.close_button.connect("clicked", self._on_close_day)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(later)
        header.pack_end(self.close_button)
        self.later = later
        later.set_label(f"Ask me in {self.ctx.settings.closing_snooze} min")
        self.toasts = Adw.ToastOverlay(child=self.page)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)
        self.connect("close-request", self._on_close_request)
        self.refresh()

    # -- content -----------------------------------------------------------

    def refresh(self) -> None:
        for row in self._rows:
            self.group.remove(row)
        self._rows = []
        pending = planner.open_tasks(self.ctx.db, self.day)
        total = sum(t.minutes for t in pending)
        for task in pending:
            row = Adw.ActionRow(title=GLib.markup_escape_text(task.title), subtitle=minutes_text(task.minutes))
            buttons = Gtk.Box(valign=Gtk.Align.CENTER)
            buttons.add_css_class("linked")
            choices = [("Done", TaskStatus.DONE)]
            if tasks.can_carry(task):
                choices.append(("Tomorrow", TaskStatus.CARRIED))
            if tasks.can_cancel(task):
                choices.append(("Cancel", TaskStatus.CANCELLED))
            for text, status in choices:
                button = Gtk.Button(label=text)
                button.connect("clicked", lambda _b, t=task, s=status: self._settle(t, s))
                buttons.append(button)
            row.add_suffix(buttons)
            self.group.add(row)
            self._rows.append(row)

        self.group.set_visible(bool(pending))
        kind = self.ctx.db.day_kind(self.day)
        self.evening_group.set_visible(
            bool(pending) and kind is not DayKind.REST and self.ctx.settings.evening_offer
        )
        if pending:
            n = len(pending)
            self.status.set_title("Your focus time for today is over")
            self.status.set_subtitle(
                f"{n} task{'s' if n != 1 else ''} still open ({minutes_text(total)}). "
                "Say what happened to each, so tomorrow starts clean."
            )
            self.close_button.set_label("Close the day")
            self.later.set_visible(True)
        else:
            self.status.set_title("Everything is settled")
            self.status.set_subtitle("Nothing left open for today.")
            self.close_button.set_label("Done")
            self.later.set_visible(False)

        # Tomorrow: the carried tasks are only part of it; new ones can be added too.
        nxt = self.day + timedelta(days=1)
        view = self.ctx.day_view(nxt)
        focus = view.schedule.focus_minutes if view.schedule else 0
        load = tasks.load(self.ctx.db.tasks_on(nxt, prayers=False), focus)
        count = len([t for t in self.ctx.db.tasks_on(nxt, prayers=False)])
        self.tomorrow_row.set_title(
            f"{count} task{'s' if count != 1 else ''} · {minutes_text(load.planned)} of {minutes_text(focus)}"
            if focus else f"{count} task{'s' if count != 1 else ''}"
        )
        sub = "You can add new tasks for tomorrow too, not only the ones you move from today."
        if focus and load.over:
            sub = f"Tomorrow is over by {minutes_text(load.planned - focus)}. " + sub
        self.tomorrow_row.set_subtitle(sub)

    # -- actions -----------------------------------------------------------

    def _settle(self, task, status: TaskStatus) -> None:
        self.ctx.db.set_task_status(task.id, status, today=clock_now().date())
        self.ctx.changed("tasks")
        self.refresh()

    def _finish(self) -> None:
        self._resolved = True
        self.close()

    def _on_evening(self, _button) -> None:
        from .evening_dialog import EveningDialog

        entry = self.ctx.db.day_entries(self.day, self.day).get(self.day)
        current = entry.evening if entry else 0
        open_minutes = sum(t.minutes for t in planner.open_tasks(self.ctx.db, self.day))
        steps = max(1, -(-open_minutes // 30))  # round up to whole half hours
        EveningDialog(self, self.ctx, self.day, current, suggested=current + steps * 30,
                      on_saved=self._after_evening).present()

    def _after_evening(self) -> None:
        # The day just got longer: planning moves to the end of the new block, and the check-in
        # comes back then. Nothing is snoozed or closed.
        self.ctx.toast("Evening work added. You will be asked again when it ends.")
        self._finish()

    def _on_plan(self, _button) -> None:
        self.ctx.show_page("tomorrow")
        self.close()  # leaves the check-in open: asks again later if tasks remain

    def _on_later(self, _button) -> None:
        self.ctx.db.snooze_closing(self.day, clock_now() + planner.snooze(self.ctx.db))
        self._finish()

    def _on_close_day(self, _button) -> None:
        pending = planner.open_tasks(self.ctx.db, self.day)
        if not pending or not self.ctx.settings.closing_confirm:
            self.ctx.db.close_day(self.day)
            self._finish()
            return
        n = len(pending)
        sure = Adw.MessageDialog(
            transient_for=self, modal=True,
            heading="Leave these for tomorrow’s review?",
            body=f"{n} task{'s' if n != 1 else ''} will stay open. Tomorrow begins by asking about "
                 f"{'them' if n != 1 else 'it'}. Settling them now takes a moment and keeps tomorrow clean.",
        )
        sure.add_response("back", "Settle them now")
        sure.add_response("leave", "Leave them")
        sure.set_default_response("back")
        sure.set_close_response("back")
        sure.connect("response", self._on_confirm)
        sure.present()

    def _on_confirm(self, _dialog, response: str) -> None:
        if response == "leave":
            self.ctx.db.close_day(self.day)
            self._finish()

    def _on_close_request(self, _window) -> bool:
        if not self._resolved:  # Escape or the window's own close: not "no", just "later"
            if planner.open_tasks(self.ctx.db, self.day):
                self.ctx.db.snooze_closing(self.day, clock_now() + planner.snooze(self.ctx.db))
            else:
                self.ctx.db.close_day(self.day)  # nothing left to ask about
            self._resolved = True
        return False
