"""Where things live on disk."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
APP_ROOT = PACKAGE_DIR.parent
RESOURCE_DIR = PACKAGE_DIR / "resources"
BUNDLED_DATA_DIR = PACKAGE_DIR / "data"

XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
APP_DATA_DIR = XDG_DATA_HOME / "fuzzy-journey"
DATABASE_PATH = APP_DATA_DIR / "fuzzy-journey.sqlite3"
CUSTOM_SOUND_DIR = APP_DATA_DIR / "custom-sounds"
BACKUP_DIR = APP_DATA_DIR / "backup"


def ensure_data_dir() -> Path:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DATA_DIR
