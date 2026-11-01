from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
APP_DATA_DIR = XDG_DATA_HOME / "fuzzy-journey"
DATABASE_PATH = APP_DATA_DIR / "fuzzy-journey.sqlite3"
ALARM_SOUND_PATH = APP_DATA_DIR / "alarm.wav"


def schedule_path(year: int, city: str = "shahrekord") -> Path | None:
    """Prefer user-managed data; fall back to the bundled offline schedule."""
    filename = f"{city}_prayer_times_{year}_schedule.csv"
    for candidate in (APP_DATA_DIR / filename, APP_ROOT / filename):
        if candidate.is_file():
            return candidate
    return None


def ensure_data_dir() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
