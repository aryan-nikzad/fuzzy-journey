"""Ask systemd about the alarm service without ever blocking the interface."""

from __future__ import annotations

from collections.abc import Callable

from ..meta import SERVICE_NAME
from .gi_setup import Gio, GLib


def _run(argv: list[str], callback: Callable[[int, str], None]) -> None:
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error:
        callback(-1, "")
        return

    def done(source, result):
        try:
            _ok, out, _err = source.communicate_utf8_finish(result)
            callback(source.get_exit_status(), (out or "").strip())
        except GLib.Error:
            callback(-1, "")

    proc.communicate_utf8_async(None, None, done)


def is_active(callback: Callable[[bool | None], None]) -> None:
    """callback(True/False), or callback(None) when systemd is unavailable."""

    def done(code: int, out: str) -> None:
        callback(None if code == -1 else out == "active")

    _run(["systemctl", "--user", "is-active", SERVICE_NAME], done)


def start(callback: Callable[[bool], None]) -> None:
    _run(["systemctl", "--user", "restart", SERVICE_NAME], lambda code, _out: callback(code == 0))
