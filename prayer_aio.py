#!/usr/bin/env python3
"""Command-line prayer-time planner. A thin entry point; the code lives in ``fuzzy_journey``.

    python3 prayer_aio.py --today
    python3 prayer_aio.py --75 --tomorrow
    python3 prayer_aio.py --flex-time 00:30
    python3 prayer_aio.py --year 2027 --evening-start 19:30 --no-show

See ``python3 prayer_aio.py --help`` and fuzzy_journey/cli.py.
"""

import sys

from fuzzy_journey.cli import main, parse_clock_time, parse_hhmm  # noqa: F401
from fuzzy_journey.prayer_times import RAW_FIELDNAMES, SCHEDULE_FIELDNAMES, build_schedule  # noqa: F401
from fuzzy_journey.rhythm import calculate_work_blocks  # noqa: F401  (kept for existing imports)

if __name__ == "__main__":
    sys.exit(main())
