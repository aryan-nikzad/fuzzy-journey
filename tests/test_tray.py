"""The tray icon speaks StatusNotifierItem and dbusmenu. Tested against a private bus with a fake watcher.

Skipped without GLib, or without ``dbus-daemon`` to make a private session bus. Nothing here touches the
real session bus.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import unittest

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    from fuzzy_journey.ui import tray as _tray  # noqa: F401  (needs GTK 4 too, through gi_setup)

    HAVE_GIO = True
except (ImportError, ValueError):
    HAVE_GIO = False

HAVE_BUS = HAVE_GIO and shutil.which("dbus-daemon") is not None

WATCHER_XML = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method></interface></node>"""


def pump(until, seconds=5.0):
    """Run the main loop until ``until()`` is true (the services under test live in this process)."""
    context, end = GLib.MainContext.default(), time.time() + seconds
    while not until() and time.time() < end:
        context.iteration(False)
        time.sleep(0.005)
    return until()


@unittest.skipUnless(HAVE_BUS, "GLib / dbus-daemon not available")
class TrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = subprocess.Popen(
            ["dbus-daemon", "--session", "--print-address", "--nofork"], stdout=subprocess.PIPE, text=True
        )
        cls.address = cls.daemon.stdout.readline().strip()

    @classmethod
    def tearDownClass(cls):
        cls.daemon.terminate()
        cls.daemon.wait()

    def connect(self):
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
        conn = Gio.DBusConnection.new_for_address_sync(self.address, flags, None, None)
        self.addCleanup(conn.close_sync, None)
        return conn

    def call(self, conn, name, path, iface, method, params=None):
        out = {}
        conn.call(name, path, iface, method, params, None, Gio.DBusCallFlags.NONE, 3000, None,
                  lambda s, r: out.setdefault("r", s.call_finish(r)))
        self.assertTrue(pump(lambda: "r" in out), f"{method} never answered")
        return out["r"].unpack()

    def start_watcher(self):
        seen = []
        conn = self.connect()
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]

        def method_call(_c, _s, _p, _i, method, params, invocation):
            seen.append(params.unpack()[0])
            invocation.return_value(None)

        conn.register_object("/StatusNotifierWatcher", info, method_call, None, None)
        owned = []
        Gio.bus_own_name_on_connection(conn, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE,
                                       lambda *_: owned.append(1), None)
        self.assertTrue(pump(lambda: owned))
        return seen

    def make_tray(self):
        from fuzzy_journey.ui.tray import Tray

        clicks = []
        tray = Tray("Fuzzy Journey", "icon", lambda: clicks.append("activate"),
                    [("Show", lambda: clicks.append("show")), (None, None), ("Quit", lambda: clicks.append("quit"))])
        self.addCleanup(tray.stop)
        return tray, clicks

    def test_it_registers_with_the_watcher_and_becomes_active(self):
        seen = self.start_watcher()
        tray, _ = self.make_tray()
        self.assertFalse(tray.active)
        tray.start(self.connect())
        self.assertTrue(pump(lambda: tray.active), "never became active")
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("org.kde.StatusNotifierItem-"))

    def test_without_a_watcher_it_is_never_active_so_the_window_still_closes(self):
        tray, _ = self.make_tray()
        tray.start(self.connect())
        pump(lambda: False, 0.5)
        self.assertFalse(tray.active)

    def test_clicking_the_icon_activates_and_the_properties_are_readable(self):
        self.start_watcher()
        tray, clicks = self.make_tray()
        mine = self.connect()
        tray.start(mine)
        self.assertTrue(pump(lambda: tray.active))
        client = self.connect()
        props = self.call(client, tray._name, "/StatusNotifierItem", "org.freedesktop.DBus.Properties", "GetAll",
                          GLib.Variant("(s)", ("org.kde.StatusNotifierItem",)))[0]
        self.assertEqual((props["Title"], props["IconName"], props["Menu"], props["Status"]),
                         ("Fuzzy Journey", "icon", "/MenuBar", "Active"))
        self.call(client, tray._name, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "Activate",
                  GLib.Variant("(ii)", (0, 0)))
        self.assertTrue(pump(lambda: "activate" in clicks))

    def test_the_menu_lists_its_entries_and_runs_the_one_clicked(self):
        self.start_watcher()
        tray, clicks = self.make_tray()
        tray.start(self.connect())
        self.assertTrue(pump(lambda: tray.active))
        client = self.connect()
        revision, (root, _props, children) = self.call(
            client, tray._name, "/MenuBar", "com.canonical.dbusmenu", "GetLayout",
            GLib.Variant("(iias)", (0, -1, [])))
        self.assertEqual(root, 0)
        entries = [(child[0], child[1].get("label") or child[1].get("type")) for child in children]
        self.assertEqual(entries, [(1, "Show"), (2, "separator"), (3, "Quit")])
        self.call(client, tray._name, "/MenuBar", "com.canonical.dbusmenu", "Event",
                  GLib.Variant("(isvu)", (3, "clicked", GLib.Variant("i", 0), 0)))
        self.assertTrue(pump(lambda: "quit" in clicks))
        self.assertNotIn("show", clicks)

    def test_stopping_removes_the_icon(self):
        self.start_watcher()
        tray, _ = self.make_tray()
        tray.start(self.connect())
        self.assertTrue(pump(lambda: tray.active))
        tray.stop()
        self.assertFalse(tray.active)
        tray.stop()  # twice is fine


if __name__ == "__main__":
    unittest.main()
