from __future__ import annotations

from ...ideas import IDEAS_INTRO, MAX_TITLE, Idea
from ..context import Context
from ..dialogs.idea_dialog import IdeaDialog
from ..gi_setup import Adw, Gdk, GLib, GObject, Graphene, Gtk
from ..widgets import clear, label
from .base import Page

DRAG_PREFIX = "fuzzy-journey-idea:"
EDGE = 56  # px from the top or bottom of the page where dragging starts to scroll it
STEP = 14  # px scrolled every 30 ms


class IdeasPage(Page):
    """A bank of ideas: type one and press Enter to save it, drag them into the order to follow up.

    The top idea is the one to follow up first. A new idea goes to the bottom, so capturing never forces a
    decision about where it belongs; sorting happens later, by dragging. Rows can also be moved with the
    edit window's Move up / Move down, for anyone who cannot or would rather not drag.
    """

    listens_to = frozenset({"ideas"})

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self._ideas: list[Idea] = []
        self._marked: Gtk.Widget | None = None  # the row currently showing a drop line
        self._dragging = False
        self._pointer_y: float | None = None  # last drag position, in this page's coordinates
        self._scroll_id = 0

        self.column.append(label(IDEAS_INTRO, "dim-label", wrap=True))

        # -- quick capture: one line, Enter, done
        capture = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        capture.add_css_class("boxed-list")
        self.entry = Adw.EntryRow(title="New idea: type it and press Enter")
        self.entry.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        self.entry.connect("entry-activated", lambda _r: self._capture())
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Save idea")
        add.add_css_class("flat")
        add.connect("clicked", lambda _b: self._capture())
        self.entry.add_suffix(add)
        capture.append(self.entry)
        self.column.append(capture)

        self.summary = label("", "caption", "dim-label")
        self.column.append(self.summary)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.column.append(self.list)

        # Tracking the pointer over the page (not only over rows) lets a drag scroll near the edges.
        track = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        track.connect("motion", self._track)
        track.connect("drop", lambda *_a: False)
        self.add_controller(track)
        self.refresh()

    # -- capture -----------------------------------------------------------------

    def focus_entry(self) -> None:
        self.entry.grab_focus()

    def _capture(self) -> None:
        text = " ".join(self.entry.get_text().split())
        if not text:
            return
        try:
            self.ctx.db.save_idea(Idea(text[:MAX_TITLE]))
        except ValueError as error:
            self.ctx.toast(str(error))
            return
        self.entry.set_text("")
        self.ctx.changed("ideas")
        self.entry.grab_focus()  # ready for the next one

    def edit(self, idea: Idea) -> None:
        IdeaDialog(self.get_root(), self.ctx, idea).present()

    # -- rendering ---------------------------------------------------------------

    def refresh(self) -> None:
        adjustment = self.get_vadjustment()
        keep = adjustment.get_value()
        self._unmark()
        clear(self.list)
        self._ideas = self.ctx.db.list_ideas()
        n = len(self._ideas)
        self.summary.set_visible(n > 0)
        self.summary.set_text(f"{n} idea{'s' if n != 1 else ''}. The top one is the one to follow up first; "
                              "drag the handle on the left to reorder.")
        if not self._ideas:
            self.list.append(Adw.ActionRow(title="No ideas yet", subtitle="Type the first one above.",
                                           activatable=False))
            return
        for number, idea in enumerate(self._ideas, start=1):
            self.list.append(self._row(number, idea))
        # Rebuilding the list resets the scroll; put it back once the new rows have a size.
        GLib.idle_add(lambda: (adjustment.set_value(keep), GLib.SOURCE_REMOVE)[1])

    def _row(self, number: int, idea: Idea) -> Adw.ActionRow:
        first_line = next((line.strip() for line in idea.note.splitlines() if line.strip()), "")
        row = Adw.ActionRow(title=idea.title, subtitle=first_line, use_markup=False, title_lines=0,
                            subtitle_lines=2, activatable=True)
        row.connect("activated", lambda _r, i=idea: self.edit(i))

        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.set_tooltip_text("Drag to change the order")
        handle.add_css_class("dim-label")
        handle.set_cursor(Gdk.Cursor.new_from_name("grab"))
        row.add_prefix(handle)
        rank = label(str(number), "fj-idea-number", xalign=0.5)
        rank.set_valign(Gtk.Align.CENTER)
        if number == 1:
            rank.add_css_class("fj-rank-first")
            rank.set_tooltip_text("Follow up this one first")
        row.add_prefix(rank)

        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text=f"Edit “{idea.title}”")
        edit.add_css_class("flat")
        edit.connect("clicked", lambda _b, i=idea: self.edit(i))
        row.add_suffix(edit)

        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", lambda _s, _x, _y, i=idea: Gdk.ContentProvider.new_for_value(f"{DRAG_PREFIX}{i.id}"))
        source.connect("drag-begin", self._drag_begin, row)
        source.connect("drag-end", self._drag_end, row)
        handle.add_controller(source)

        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect("motion", self._over, row)
        target.connect("leave", lambda _t: self._unmark())
        target.connect("drop", self._drop, row, idea)
        row.add_controller(target)
        return row

    # -- drag and drop -----------------------------------------------------------

    def _drag_begin(self, source: Gtk.DragSource, _drag, row: Gtk.Widget) -> None:
        source.set_icon(Gtk.WidgetPaintable.new(row), 0, 0)
        row.add_css_class("fj-dragging")
        self._dragging = True
        if not self._scroll_id:
            self._scroll_id = GLib.timeout_add(30, self._autoscroll)

    def _drag_end(self, _source, _drag, _delete, row: Gtk.Widget | None = None) -> None:
        # Gtk.DragSource's drag-end gives (drag, delete_data); the row was bound as the last argument.
        self._finish_drag()

    def _finish_drag(self) -> None:
        self._dragging = False
        self._pointer_y = None
        self._unmark()
        for row in self._rows():
            row.remove_css_class("fj-dragging")

    def _rows(self) -> list[Gtk.Widget]:
        out, child = [], self.list.get_first_child()
        while child is not None:
            out.append(child)
            child = child.get_next_sibling()
        return out

    def _track(self, _target, _x: float, y: float) -> Gdk.DragAction:
        self._pointer_y = y
        return Gdk.DragAction.MOVE

    def _over(self, _target, x: float, y: float, row: Gtk.Widget) -> Gdk.DragAction:
        found, point = row.compute_point(self, Graphene.Point().init(x, y))
        if found:
            self._pointer_y = point.y
        self._mark(row, y > row.get_height() / 2)
        return Gdk.DragAction.MOVE

    def _mark(self, row: Gtk.Widget, after: bool) -> None:
        if self._marked is not None and self._marked is not row:
            self._unmark()
        self._marked = row
        row.remove_css_class("fj-drop-before")
        row.remove_css_class("fj-drop-after")
        row.add_css_class("fj-drop-after" if after else "fj-drop-before")

    def _unmark(self) -> None:
        if self._marked is not None:
            self._marked.remove_css_class("fj-drop-before")
            self._marked.remove_css_class("fj-drop-after")
            self._marked = None

    def _drop(self, _target, value, _x: float, y: float, row: Gtk.Widget, idea: Idea) -> bool:
        after = y > row.get_height() / 2
        self._finish_drag()
        if not isinstance(value, str) or not value.startswith(DRAG_PREFIX):
            return False
        try:
            moving = int(value[len(DRAG_PREFIX):])
        except ValueError:
            return False
        if self.ctx.db.drop_idea(moving, idea.id, after):
            # Redraw after the drag has fully ended, not from inside the drop that is still finishing.
            GLib.idle_add(lambda: (self.ctx.changed("ideas"), GLib.SOURCE_REMOVE)[1])
        return True

    def _autoscroll(self) -> bool:
        if not self._dragging:
            self._scroll_id = 0
            return GLib.SOURCE_REMOVE
        y = self._pointer_y
        if y is not None:
            adjustment, height = self.get_vadjustment(), self.get_height()
            if y < EDGE:
                adjustment.set_value(max(adjustment.get_lower(), adjustment.get_value() - STEP))
            elif y > height - EDGE:
                top = adjustment.get_upper() - adjustment.get_page_size()
                adjustment.set_value(min(top, adjustment.get_value() + STEP))
        return GLib.SOURCE_CONTINUE
