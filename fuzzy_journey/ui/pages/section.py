from __future__ import annotations

from ..gi_setup import Gtk


class Section(Gtk.Box):
    """One top-level destination that holds a few related pages behind a quiet sub-navigation.

    The app has five of them (Today, Plan, Mind, Track, Ideas) so the whole of it fits in the head at once.
    A section with only one visible page shows no sub-navigation at all.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        # Not homogeneous: the page you are on sets the width, not the widest page you are not on.
        self.inner = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True,
                               hhomogeneous=False)
        self.switcher = Gtk.StackSwitcher(stack=self.inner, halign=Gtk.Align.CENTER)
        self.switcher.add_css_class("fj-subnav")
        # Narrow windows scroll the sub-navigation sideways instead of squeezing the labels.
        self.bar = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER,
            child=self.switcher,
        )
        self.bar.set_margin_top(10)
        self.bar.set_margin_bottom(2)
        self.bar.set_margin_start(12)
        self.bar.set_margin_end(12)
        self.append(self.bar)
        self.append(self.inner)

    def add(self, name: str, title: str, page: Gtk.Widget) -> None:
        self.inner.add_titled(page, name, title)

    def visible_names(self) -> list[str]:
        out = []
        child = self.inner.get_first_child()
        while child:
            page = self.inner.get_page(child)
            if page.get_visible():
                out.append(page.get_name())
            child = child.get_next_sibling()
        return out

    def set_page_visible(self, page: Gtk.Widget, visible: bool) -> None:
        """Show or hide one page. Hiding the page you are on moves you to the first page that is left."""
        self.inner.get_page(page).set_visible(visible)
        if not visible and self.inner.get_visible_child() is page:
            names = self.visible_names()
            if names:
                self.inner.set_visible_child_name(names[0])
        self.bar.set_visible(len(self.visible_names()) > 1)
