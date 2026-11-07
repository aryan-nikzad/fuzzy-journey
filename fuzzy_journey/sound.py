"""Alarm tones, desktop notifications and playback.

Uses only the standard library plus whatever players the desktop provides.
This module must stay importable without GTK: the alarm service uses it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import signal
import struct
import subprocess
import threading
import wave
from pathlib import Path

from .meta import APP_NAME
from .models import SOUND_PRESETS, Sound
from .paths import APP_DATA_DIR, CUSTOM_SOUND_DIR, ensure_data_dir

log = logging.getLogger(__name__)

AUDIO_SUFFIXES = {".mp3", ".wav", ".wave", ".ogg", ".flac", ".m4a", ".aac"}

MELODIES = {
    "classic": [(880, 0.42), (0, 0.16), (1175, 0.42), (0, 0.16), (880, 0.42), (0, 0.16), (1175, 0.75)],
    "gentle": [(523, 0.45), (659, 0.45), (784, 0.70), (0, 0.15), (659, 0.7)],
    "urgent": [(1046, 0.22), (0, 0.08), (1318, 0.22), (0, 0.08), (1568, 0.35)],
    "digital": [(1200, 0.12), (0, 0.08), (1200, 0.12), (0, 0.08), (1600, 0.28)],
}
MELODY_REPEATS = 4
SAMPLE_RATE = 22050


def sound_path(key: str = "classic") -> Path:
    key = key if key in SOUND_PRESETS else "classic"
    return APP_DATA_DIR / ("alarm.wav" if key == "classic" else f"alarm-{key}.wav")


def ensure_tone(key: str = "classic") -> Path:
    """Synthesize a built-in tone once and cache it in the data folder."""
    ensure_data_dir()
    path = sound_path(key)
    if path.is_file():
        return path

    notes = MELODIES.get(key, MELODIES["classic"]) * MELODY_REPEATS
    samples = bytearray()
    for frequency, duration in notes:
        count = int(SAMPLE_RATE * duration)
        for index in range(count):
            if frequency == 0:
                value = 0
            else:
                attack = min(1.0, index / (SAMPLE_RATE * 0.02))
                release = min(1.0, (count - index) / (SAMPLE_RATE * 0.05))
                envelope = min(attack, release)
                value = int(10500 * envelope * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
            samples.extend(struct.pack("<h", value))

    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(bytes(samples))
    tmp.replace(path)
    return path


def import_custom_audio(source_path: str | Path) -> str:
    """Copy a personal audio file into the data folder so moving the original never breaks an alarm."""
    source = Path(source_path).expanduser()
    if source.suffix.lower() not in AUDIO_SUFFIXES or not source.is_file():
        raise ValueError("Choose an MP3, WAV, OGG, FLAC, M4A or AAC audio file.")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-")[:48] or "alarm"
    CUSTOM_SOUND_DIR.mkdir(parents=True, exist_ok=True)
    destination = CUSTOM_SOUND_DIR / f"{digest.hexdigest()[:12]}-{safe}{source.suffix.lower()}"
    if not destination.exists():
        shutil.copy2(source, destination)
    return str(destination)


def _player_command(path: Path) -> list[str] | None:
    """Pick a player. Compressed formats need a full media player; WAV works with simple ones."""
    for name in ("mpv", "ffplay", "mpg123", "cvlc"):
        exe = shutil.which(name)
        if not exe:
            continue
        if name == "mpv":
            return [exe, "--no-video", "--really-quiet", str(path)]
        if name == "ffplay":
            return [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        if name == "mpg123":
            return [exe, "-q", str(path)]
        return [exe, "--play-and-exit", "--quiet", str(path)]
    if path.suffix.lower() in {".wav", ".wave"}:
        for name in ("paplay", "pw-play", "aplay"):
            exe = shutil.which(name)
            if exe:
                return [exe, str(path)]
    return None


def has_player_for(path: str | Path | None) -> bool:
    return _player_command(Path(path) if path else ensure_tone()) is not None


# --------------------------------------------------------------------------
# Stopping a ringing alarm
#
# The alarm service plays sounds in its own process, but the app (a button) and
# a notification action must be able to stop them. Every player's pid and file
# is recorded in a small file in the data folder; anyone can read it and stop them.
# --------------------------------------------------------------------------

RINGING_FILE = APP_DATA_DIR / "ringing.json"
_children: list[subprocess.Popen] = []


def _read_ringing() -> list[dict]:
    try:
        data = json.loads(RINGING_FILE.read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict) and isinstance(d.get("pid"), int)]
    except (OSError, ValueError):
        return []


def _write_ringing(entries: list[dict]) -> None:
    try:
        ensure_data_dir()
        tmp = RINGING_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries), encoding="utf-8")
        tmp.replace(RINGING_FILE)
    except OSError as exc:
        log.warning("Could not record the playing alarm: %s", exc)


def _is_ours(entry: dict) -> bool:
    """True while that pid is still the player we started (guards against pid reuse and zombies)."""
    try:
        cmdline = Path(f"/proc/{entry['pid']}/cmdline").read_bytes().decode(errors="replace")
    except OSError:
        return False
    return bool(cmdline) and str(entry.get("file", "")) in cmdline


def is_ringing() -> bool:
    """Is an alarm sound playing right now? Cheap enough to poll every second or two."""
    for child in _children[:]:  # reap finished players so they do not linger as zombies
        if child.poll() is not None:
            _children.remove(child)
    entries = _read_ringing()
    alive = [e for e in entries if _is_ours(e)]
    if len(alive) != len(entries):
        _write_ringing(alive)
    return bool(alive)


def stop_all() -> bool:
    """Silence every alarm sound. Safe to call from the app, the service or a notification."""
    stopped = False
    for entry in _read_ringing():
        if not _is_ours(entry):
            continue
        try:
            os.killpg(entry["pid"], signal.SIGTERM)  # players run in their own session
            stopped = True
        except (ProcessLookupError, PermissionError):
            pass
    _write_ringing([])
    return stopped


def play(sound: Sound) -> bool:
    """Start playing ``sound`` in the background. Returns False if nothing could play."""
    if not sound.enabled:
        return False
    target = Path(sound.custom_path).expanduser() if sound.custom_path else None
    if target is None or not target.is_file():
        target = ensure_tone(sound.key)
    command = _player_command(target)
    if not command:
        log.warning("No audio player found for %s", target.name)
        return False
    try:
        child = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _children.append(child)
        _write_ringing([*(e for e in _read_ringing() if _is_ours(e)), {"pid": child.pid, "file": str(target)}])
        return True
    except OSError as exc:
        log.warning("Could not start audio player: %s", exc)
        return False


_ACTIONS: bool | None = None


def _supports_actions(command: str) -> bool:
    """Does this notify-send have a Stop button (libnotify 0.8+)?"""
    global _ACTIONS
    if _ACTIONS is None:
        try:
            out = subprocess.run([command, "--help"], capture_output=True, text=True, timeout=5)
            _ACTIONS = "--action" in out.stdout
        except (OSError, subprocess.TimeoutExpired):
            _ACTIONS = False
    return _ACTIONS


def _notify_with_stop(command: str, title: str, message: str) -> None:
    """Show the notification with a Stop button; pressing it silences the alarm."""
    try:
        done = subprocess.run(
            [command, f"--app-name={APP_NAME}", "--urgency=critical", "--action=stop=Stop alarm",
             title, message],
            capture_output=True, text=True, timeout=300, check=False,
        )
        if done.stdout.strip() == "stop":
            stop_all()
    except (OSError, subprocess.TimeoutExpired):
        pass


def notify(title: str, message: str, *, stoppable: bool = False) -> bool:
    """A desktop notification. ``stoppable`` adds a Stop button where the desktop supports it."""
    command = shutil.which("notify-send")
    if not command:
        return False
    if stoppable and _supports_actions(command):
        threading.Thread(target=_notify_with_stop, args=(command, title, message), daemon=True).start()
        return True
    try:
        subprocess.run(
            [command, f"--app-name={APP_NAME}", "--urgency=critical", "--expire-time=15000", title, message],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
