from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

from .paths import ALARM_SOUND_PATH, ensure_data_dir


def ensure_alarm_sound(path: Path = ALARM_SOUND_PATH) -> Path:
    """Create a small, self-contained alarm tone using only the standard library."""
    ensure_data_dir()
    if path.is_file():
        return path

    sample_rate = 22050
    melody = [(880, 0.42), (0, 0.16), (1175, 0.42), (0, 0.16), (880, 0.42), (0, 0.16), (1175, 0.75)]
    samples = bytearray()
    for frequency, duration in melody * 4:
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


def play_alarm_sound() -> None:
    sound_path = ensure_alarm_sound()
    player = next((shutil.which(name) for name in ("paplay", "pw-play", "aplay") if shutil.which(name)), None)
    if not player:
        return
    try:
        subprocess.Popen(
            [player, str(sound_path)],
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
        play_alarm_sound()
