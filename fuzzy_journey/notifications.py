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

# Each preset is a short sequence of tones (frequency Hz, duration seconds).
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
    """Create a local, self-contained sound preset using only the standard library."""
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
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def play_alarm_sound(sound_key: str = "classic") -> None:
    sound_file = ensure_alarm_sound(sound_key)
    player = next((shutil.which(name) for name in ("paplay", "pw-play", "aplay") if shutil.which(name)), None)
    if not player:
        return
    try:
        subprocess.Popen(
            [player, str(sound_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def deliver_alarm(alarm: dict) -> None:
    title = alarm.get("title") or "Reminder"
    send_notification(f"Fuzzy Journey · {title}", f"It's {alarm['alarm_time']}. Your reminder is due.")
    if alarm.get("sound_enabled", True):
        play_alarm_sound(alarm.get("sound_key", "classic"))
