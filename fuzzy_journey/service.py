"""The background alarm service (``fuzzy-journey.service``).

Runs without GTK, without the network and without the GUI being open.
Every few seconds it asks the database what is due, claims it, and rings.
"""

from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timedelta

from . import alarms, sound
from .database import Database
from .meta import APP_NAME
from .paths import DATABASE_PATH
from .prayer_times import PrayerLibrary
from .rhythm import DayKind

POLL_SECONDS = 5
log = logging.getLogger("fuzzy-journey-alarms")


def due_rings(db: Database, library: PrayerLibrary, now: datetime) -> list[alarms.Ring]:
    """Claim and return everything that should ring at ``now``."""
    rings = alarms.claim_due_reminders(db, now)

    slug = db.settings.location.slug
    today = now.date()
    yesterday = today - timedelta(days=1)
    kinds = {day: entry.kind for day, entry in db.day_entries(yesterday, today).items()}
    events = alarms.scheduled_events(
        today,
        prayer_day=library.day(slug, today),
        prayer_alarms=db.prayer_alarms(),
        activities=db.list_activities(),
        kinds={yesterday: DayKind.STEADY, today: DayKind.STEADY, **kinds},
    )
    return rings + alarms.claim_due_events(db, events, now)


def deliver(ring: alarms.Ring) -> None:
    sound.notify(f"{APP_NAME} · {ring.title}", ring.message)
    if ring.sound.enabled:
        sound.play(ring.sound)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = Database()
    library = PrayerLibrary()
    db.prune_history()
    log.info("Alarm service started. Database: %s", DATABASE_PATH)

    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    while not stop.is_set():
        try:
            for ring in due_rings(db, library, datetime.now()):
                log.info("Ringing %s (%s)", ring.title, ring.key)
                deliver(ring)
        except Exception:  # noqa: BLE001 - the service must never die on one bad tick
            log.exception("Alarm check failed; will retry.")
        stop.wait(POLL_SECONDS)

    log.info("Alarm service stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
