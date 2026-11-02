"""Pin GI versions once, before any other ui module imports gi.repository."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk  # noqa: E402,F401
