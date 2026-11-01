from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from .paths import APP_DATA_DIR, ensure_data_dir

SOUND_PRESETS = {
    "classic": "Classic",
    "gentle": "Gentle",
    "urgent": "Urgent",
    "digital": "Digital",
}

MELODIES = {
    "classic": [(880, 0.42), (0, 0.16), (1175, 0.42), (0, 0.16), (880, 0.42), (0, 0.16), (1175, 0.75)],
    "gentle": [(523, 0.45), (659, 0.45), (784, 0.70), (0, 0.15), (659, 0.7)],
    "urgent": [(1046, 0.22), (0, 0.08), (1318, 0.22), (0, 0.08), (1568, 0.35)],
    "digital": [(1200, 0.12), (0, 0.08), (1200, 0.12), (0, 0.08), (1600, 0.28)],
}


def sound_path(sound_key: str = "classic") -> Path:
    key = sound_key if sound_key in SOUND_PRESETS else "classic"
    return APP_DATA_DIR / ("alarm.wav" if key == "classic" else f"alarm-{key}.wav")


def ensure_alarm_sound(sound_key: str = "classic") -> Path:
    """Create a local sound preset with the standard library."""
    ensure_data_dir()
    path = sound_path(sound_key)
    if path.is_file():
        return path

    sample_rate = 22050
    samples = bytearray()
    for frequency, duration in MELODIES.get(sound_key, MELODIES["classic"]) * 4:
        count = int(sample_rate * duration)
        for index in range(count):
            if frequency == 0:
                value = 0
            else:
                attack = min(1.0, index / (sample_rate * 0.02))
                release = min(1.0, (count - index) / (sample_rate * 0.05))
                envelope = min(attack, release)
                value = int(10500 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
            samples.extend(struct.pack("<h", value))

    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(samples)
    return path


def send_notification(title: str, message: str) -> None:
    command = shutil.which("notify-send")
    if not command:
        return
    try:
        subprocess.run(
            [command, "--app-name=Fuzzy Journey", "--urgency=critical",
             "--expire-time=15000", title, message],
            check=False, timeout=5,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _audio_command(path: Path) -> list[str] | None:
    """Choose a player that can decode common compressed audio formats."""
    for name in ("mpv", "ffplay", "mpg123", "cvlc"):
        executable = shutil.which(name)
        if not executable:
            continue
        if name == "mpv":
            return [executable, "--no-video", "--really-quiet", str(path)]
        if name == "ffplay":
            return [executable, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        if name == "mpg123":
            return [executable, "-q", str(path)]
        return [executable, "--play-and-exit", "--quiet", str(path)]

    # The simple desktop audio players are reliable for generated / standard WAV tones.
    if path.suffix.lower() in {".wav", ".wave"}:
        for name in ("paplay", "pw-play", "aplay"):
            executable = shutil.which(name)
            if executable:
                return [executable, str(path)]
    return None


def play_alarm_sound(sound_key: str = "classic", custom_sound_path: str | None = None) -> bool:
    """Play a selected preset or a user-selected audio file."""
    if custom_sound_path:
        sound_file = Path(custom_sound_path).expanduser()
        if not sound_file.is_file():
            sound_file = ensure_alarm_sound(sound_key)
    else:
        sound_file = ensure_alarm_sound(sound_key)

    command = _audio_command(sound_file)
    if not command:
        return False
    try:
        subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def deliver_alarm(alarm: dict) -> None:
    title = alarm.get("title") or "Reminder"
    send_notification(f"Fuzzy Journey · {title}", f"It's {alarm['alarm_time']}. Your reminder is due.")
    if alarm.get("sound_enabled", True):
        play_alarm_sound(alarm.get("sound_key", "classic"), alarm.get("custom_sound_path"))
