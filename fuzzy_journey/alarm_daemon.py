from __future__ import annotations

import logging
import time

from .alarm_engine import fire_due_alarms, fire_due_schedule_events
from .notifications import deliver_alarm
from .paths import DATABASE_PATH, ensure_data_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("fuzzy-journey-alarm")


def main() -> None:
    ensure_data_dir()
    log.info("Alarm service started. Local database: %s", DATABASE_PATH)
    while True:
        try:
            due_events = fire_due_alarms() + fire_due_schedule_events()
            for alarm in due_events:
                log.info("Firing alarm %s (%s)", alarm["id"], alarm["title"])
                deliver_alarm(alarm)
        except Exception:
            log.exception("Alarm check failed; the service will retry.")
        time.sleep(5)


if __name__ == "__main__":
    main()
