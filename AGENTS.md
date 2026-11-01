# Contributor notes

## Project direction

Fuzzy Journey is a Linux-first desktop daily planner with a local alarm service. The original all-in-one CLI planner remains the source of truth for prayer-time and work/sleep calculations.

## Important guarantees

- Alarm scheduling and delivery must not make network requests.
- Alarm definitions and delivery history belong in the local SQLite database under the XDG data directory.
- The desktop window is not the alarm process. The user systemd service must continue to run when the GUI closes.
- Claim an alarm in a database transaction before sending notification/audio, so service restarts do not duplicate delivery.
- Preserve the five-minute catch-up window unless tests and documentation are updated together.
- A one-time alarm must be disabled after it is claimed.
- Use the operating system's local timezone for alarm times.
- Do not imply that software can ring while the computer is powered off or wake hardware from suspend.

## Linux integration

- GUI: GTK 4 and libadwaita via the system Python GI bindings.
- Background scheduler: Python standard library only.
- Notifications: `notify-send`; audio fallback order: `paplay`, `pw-play`, then `aplay`.
- User service: `fuzzy-journey.service`, installed under `~/.config/systemd/user`.
- The service must not import GTK or libadwaita.

## Existing CLI contract

Develop the prayer/work/sleep calculation logic in `prayer_aio.py`. Keep its current CLI flags and guarantees unless a deliberate compatibility change is documented.

- CSV encoding remains `utf-8-sig`.
- CSV date format remains `DD-MM-YYYY`.
- Existing valid CSV files are preserved by default.
- `--override` backs up existing data before regeneration.
- Flex time is re-derived from raw rows and must never be incrementally added to an existing schedule.
- Atomic CSV writes and exact header validation must remain intact.

## Tests

Run:

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 -m py_compile fuzzy_journey/*.py prayer_aio.py
```

GUI imports require the Linux GTK 4 / libadwaita GI packages and are intentionally not imported by the alarm-engine unit tests.
