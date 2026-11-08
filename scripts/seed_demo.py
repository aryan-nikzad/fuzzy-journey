"""Fill a scratch data folder with believable demo data (for screenshots and manual testing).

    XDG_DATA_HOME=/tmp/fj-demo python3 scripts/seed_demo.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fuzzy_journey.database import Database  # noqa: E402
from fuzzy_journey.models import Activity, Alarm, PrayerAlarm, Sound, Task, TaskStatus  # noqa: E402
from fuzzy_journey.rhythm import DayKind  # noqa: E402


def main() -> None:
    db = Database()
    db.settings.welcome_seen = True
    today = date(2026, 11, 2)
    db.settings.bank_start = today - timedelta(days=20)

    pattern = {1: DayKind.PUSH, 2: DayKind.PUSH, 4: DayKind.REST, 8: DayKind.PUSH, 9: DayKind.PUSH,
               11: DayKind.PUSH, 12: DayKind.REST, 15: DayKind.PUSH, 16: DayKind.PUSH, 18: DayKind.PUSH}
    for offset, kind in pattern.items():
        db.set_day_kind(today - timedelta(days=offset), kind)
    db.set_day_kind(today - timedelta(days=6), DayKind.PUSH, "Release week")

    db.save_activity(Activity("Morning call", "personal", "07:30", "08:00", 31, alarm_at_start=True))
    db.save_activity(Activity("Gym", "health", "16:00", "17:00", 127, alarm_at_start=True))
    db.save_activity(Activity("Family dinner", "personal", "19:30", "20:30", 127))
    db.save_alarm(Alarm("Take vitamins", "08:15", 127))
    db.save_alarm(Alarm("Call the bank", "10:30", 31))
    for name in ("Fajr", "Dhuhr", "Maghrib"):
        db.save_prayer_alarm(PrayerAlarm(name, True, 0, Sound(True, "gentle")))
    for title, minutes in (("Write the chapter", 90), ("Reply to emails", 30), ("Review pull requests", 45)):
        db.save_task(Task(title, minutes, today))
    done = next(t for t in db.tasks_on(today) if t.title == "Reply to emails")
    db.set_task_status(done.id, TaskStatus.DONE)
    for title, minutes in (("Plan the release", 60), ("Prepare the talk", 120)):
        db.save_task(Task(title, minutes, today + timedelta(days=1)))
    print("Seeded", db.path)


if __name__ == "__main__":
    main()
