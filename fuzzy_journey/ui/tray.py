"""A system tray icon, with no extra libraries.

GTK 4 has no tray API. Desktops read one from the *StatusNotifierItem* D-Bus protocol: KDE Plasma, XFCE,
Cinnamon, MATE, and GNOME with the AppIndicator extension. This registers one icon with the desktop's
``StatusNotifierWatcher`` and offers a small ``dbusmenu`` for the right click.

It is honest about failure: :attr:`Tray.active` is true only while a watcher exists and has accepted the
icon. The window hides into the tray only while that is true, so a desktop without a tray never leaves
you with an app you cannot reach.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from .gi_setup import Gio, GLib

log = logging.getLogger(__name__)

WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

ITEM_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus"><arg type="s"/></signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  </interface>
</node>
"""

SEPARATOR = None  # a menu entry that is a line, not an action


class Tray:
    """One tray icon. ``menu`` is a list of ``(label, callback)``; a label of ``None`` draws a separator."""

    def __init__(
        self, title: str, icon: str, on_activate: Callable[[], None],
        menu: list[tuple[str | None, Callable[[], None] | None]],
    ) -> None:
        self.title, self.icon, self.on_activate = title, icon, on_activate
        self.menu = menu
        self.active = False  # a watcher exists and has accepted the icon
        self._connection: Gio.DBusConnection | None = None
        self._own = 0
        self._watch = 0
        self._registrations: list[int] = []
        self._name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._started = False

    # -- life cycle --------------------------------------------------------------

    def start(self, connection: Gio.DBusConnection | None = None) -> None:
        """Show the icon. Safe to call twice. ``connection`` is only for tests."""
        if self._started:
            return
        try:
            self._connection = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as error:
            log.info("No session bus; no tray icon: %s", error.message)
            return
        self._started = True
        item = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self._registrations = [
            self._connection.register_object(ITEM_PATH, item, self._item_call, self._item_get, None),
            self._connection.register_object(MENU_PATH, menu, self._menu_call, self._menu_get, None),
        ]
        self._own = Gio.bus_own_name_on_connection(
            self._connection, self._name, Gio.BusNameOwnerFlags.NONE, self._on_name, self._on_lost
        )

    def stop(self) -> None:
        if not self._started:
            return
        self._started, self.active = False, False
        if self._watch:
            Gio.bus_unwatch_name(self._watch)
        if self._own:
            Gio.bus_unown_name(self._own)
        for registration in self._registrations:
            self._connection.unregister_object(registration)
        self._registrations, self._watch, self._own = [], 0, 0

    def _on_name(self, connection, _name) -> None:
        # Our own name is ours; now find a watcher, now or whenever one appears.
        self._watch = Gio.bus_watch_name_on_connection(
            connection, WATCHER, Gio.BusNameWatcherFlags.NONE, self._on_watcher, self._on_watcher_gone
        )

    def _on_lost(self, _connection, _name) -> None:
        self.active = False

    def _on_watcher(self, connection, _name, _owner) -> None:
        def done(source, result) -> None:
            try:
                source.call_finish(result)
                self.active = True
            except GLib.Error as error:
                log.info("The tray watcher refused the icon: %s", error.message)
                self.active = False

        connection.call(
            WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self._name,)), None, Gio.DBusCallFlags.NONE, 2000, None, done,
        )

    def _on_watcher_gone(self, _connection, _name) -> None:
        self.active = False  # the desktop's tray went away: the window must close normally again

    # -- the item ----------------------------------------------------------------

    def _item_get(self, _conn, _sender, _path, _iface, prop):
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "fuzzy-journey"),
            "Title": GLib.Variant("s", self.title),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", self.icon),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(prop)

    def _item_call(self, _conn, _sender, _path, _iface, method, _params, invocation) -> None:
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(self._run, self.on_activate)
        invocation.return_value(None)  # ContextMenu and Scroll: the desktop draws the menu from /MenuBar

    # -- the menu ----------------------------------------------------------------

    def _entry(self, index: int) -> dict[str, GLib.Variant]:
        label = self.menu[index][0]
        if label is SEPARATOR:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", True)}

    def layout(self):
        """The whole menu as dbusmenu wants it: a root, then one child per entry (ids start at 1)."""
        children = [GLib.Variant("(ia{sv}av)", (i + 1, self._entry(i), [])) for i in range(len(self.menu))]
        return (0, {"children-display": GLib.Variant("s", "submenu")}, children)

    def _menu_get(self, _conn, _sender, _path, _iface, prop):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(prop)

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        if method == "GetLayout":
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, self.layout())))
        elif method == "GetGroupProperties":
            ids = params.unpack()[0] or range(len(self.menu) + 1)
            rows = [(i, self._entry(i - 1)) for i in ids if 1 <= i <= len(self.menu)]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (rows,)))
        elif method == "GetProperty":
            item, name = params.unpack()
            invocation.return_value(GLib.Variant("(v)", (self._entry(item - 1).get(name, GLib.Variant("s", "")),)))
        elif method == "Event":
            item, event, _data, _stamp = params.unpack()
            if event == "clicked":
                self._click(item)
            invocation.return_value(None)
        elif method == "EventGroup":
            for item, event, _data, _stamp in params.unpack()[0]:
                if event == "clicked":
                    self._click(item)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            invocation.return_value(None)

    def _click(self, item: int) -> None:
        if 1 <= item <= len(self.menu) and self.menu[item - 1][1]:
            GLib.idle_add(self._run, self.menu[item - 1][1])

    @staticmethod
    def _run(callback: Callable[[], None]) -> bool:
        callback()
        return GLib.SOURCE_REMOVE
