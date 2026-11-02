from __future__ import annotations

from collections.abc import Callable

from ...meta import APP_NAME, TAGLINE
from ...philosophy import IDEAS, PRACTICES, Idea
from ..gi_setup import Adw, Gtk
from ..widgets import label


class PhilosophyDialog(Adw.Window):
    """The four ideas. Shown once on first run, and from the main menu any time."""

    def __init__(self, parent: Gtk.Window, *, first_run: bool = False, on_done: Callable[[], None] | None = None):
        super().__init__(transient_for=parent, modal=True, title="Philosophy", default_width=520, default_height=720)
        self._on_done = on_done

        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28, margin_top=24, margin_bottom=24,
                         margin_start=20, margin_end=20)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        head.append(label(f"{APP_NAME}  ·  {TAGLINE}".upper(), "fj-overline"))
        head.append(label("Four ideas, one rhythm.", "title-2"))
        column.append(head)

        ideas = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        for idea in IDEAS:
            ideas.append(self._idea(idea))
        column.append(ideas)

        practices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        practices.append(label("TWO PRACTICES", "fj-overline"))
        for idea in PRACTICES:
            practices.append(self._idea(idea))
        column.append(practices)

        if first_run:
            begin = Gtk.Button(label="Begin", halign=Gtk.Align.CENTER)
            begin.add_css_class("suggested-action")
            begin.add_css_class("pill")
            begin.connect("clicked", lambda _b: self.close())
            column.append(begin)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=460, child=column))
        header = Adw.HeaderBar(show_end_title_buttons=not first_run, show_start_title_buttons=False)
        view = Adw.ToolbarView(content=scroller)
        view.add_top_bar(header)
        self.set_content(view)
        self.connect("close-request", self._closing)

    @staticmethod
    def _idea(idea: Idea) -> Gtk.Widget:
        row = Gtk.Box(spacing=14, valign=Gtk.Align.START)
        number = label(str(idea.number), "fj-idea-number", xalign=0.5)
        number.set_valign(Gtk.Align.START)
        row.append(number)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        text.append(label(idea.title, "fj-idea-title"))
        text.append(label(idea.summary, "heading", wrap=True))
        text.append(label(idea.detail, "dim-label", wrap=True))
        row.append(text)
        return row

    def _closing(self, _window) -> bool:
        if self._on_done:
            self._on_done()
            self._on_done = None
        return False
