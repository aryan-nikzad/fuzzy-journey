from __future__ import annotations

from ..gi_setup import Adw, Gdk, Gtk


class FormDialog(Adw.Window):
    """A modal editor: Cancel on the left, Save on the right, groups in the middle.

    Subclasses implement :meth:`build` (add groups to ``self.body``) and
    :meth:`save` (return True to close, or call :meth:`error`).
    """

    def __init__(self, parent: Gtk.Window, title: str, *, save_label: str = "Save", height: int = 640) -> None:
        super().__init__(transient_for=parent, modal=True, title=title, default_width=480, default_height=height)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom"):
            getattr(self.body, f"set_margin_{side}")(18)
        for side in ("start", "end"):
            getattr(self.body, f"set_margin_{side}")(12)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
                                      child=Adw.Clamp(maximum_size=520, child=self.body))
        self.toasts = Adw.ToastOverlay(child=scroller)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        self.save_button = Gtk.Button(label=save_label)
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", self._on_save)

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.save_button)
        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.build()

    def _on_key(self, _ctl, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_save(self, _button) -> None:
        if self.save():
            self.close()

    def error(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(message))

    def build(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def save(self) -> bool:  # pragma: no cover
        raise NotImplementedError


def group(title: str = "", description: str = "") -> Adw.PreferencesGroup:
    return Adw.PreferencesGroup(title=title, description=description)
