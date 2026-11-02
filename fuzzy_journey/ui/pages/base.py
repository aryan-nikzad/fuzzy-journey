from __future__ import annotations

from ..context import Context
from ..gi_setup import Adw, Gtk


class Page(Gtk.ScrolledWindow):
    """A scrolling, centred column. Subclasses fill ``self.column`` and implement ``refresh``."""

    #: Scopes (see Context.changed) that make this page redraw. "all" always does; "tick" is the
    #: 15-second heartbeat, which only the Today screen needs.
    listens_to: frozenset[str] = frozenset()

    def __init__(self, ctx: Context) -> None:
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.ctx = ctx
        self.column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for side in ("top", "bottom"):
            getattr(self.column, f"set_margin_{side}")(24)
        clamp = Adw.Clamp(maximum_size=640, tightening_threshold=520, child=self.column)
        for side in ("start", "end"):
            getattr(clamp, f"set_margin_{side}")(16)
        self.set_child(clamp)

    def wants(self, scope: str) -> bool:
        return scope == "all" or scope in self.listens_to

    def refresh(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
