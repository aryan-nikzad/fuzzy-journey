import csv
from datetime import datetime, timedelta

INPUT_FILE = "shahrekord_prayer_times_2026.csv"
OUTPUT_FILE = "shahrekord_prayer_times_2026_calculated.csv"


# ==================================================
# Helpers
# ==================================================

def parse_time(value):
    return datetime.strptime(value, "%H:%M")


def duration_string(start, end):
    """
    Calculate duration between two times.
    If end is earlier than start, assume it is on the next day.
    """
    duration = end - start

    if duration.total_seconds() < 0:
        duration += timedelta(days=1)

    total_minutes = int(duration.total_seconds() / 60)

    hours = total_minutes // 60
    minutes = total_minutes % 60

    return f"{hours:02d}:{minutes:02d}"


def timedelta_to_string(duration):
    """Convert a timedelta to HH:MM."""
    total_minutes = int(duration.total_seconds() / 60)

    hours = total_minutes // 60
    minutes = total_minutes % 60

    return f"{hours:02d}:{minutes:02d}"


# ==================================================
# Calculate work blocks
# ==================================================

def calculate_work_blocks(fajr, isha, percentage):

    # ----------------------------------------------
    # Total Fajr -> Isha
    # ----------------------------------------------

    total_duration = isha - fajr

    if total_duration.total_seconds() < 0:
        total_duration += timedelta(days=1)

    # Percentage target
    target = total_duration * percentage

    # ----------------------------------------------
    # Block 1
    # Fajr -> maximum 14:00
    # ----------------------------------------------

    limit_14 = fajr.replace(
        hour=14,
        minute=0,
        second=0,
        microsecond=0
    )

    if limit_14 < fajr:
        limit_14 += timedelta(days=1)

    block1_available = limit_14 - fajr

    block1_duration = min(
        target,
        block1_available
    )

    # ----------------------------------------------
    # Remaining goes to block 2
    # ----------------------------------------------

    remaining = target - block1_duration

    # ----------------------------------------------
    # Block 1
    # ----------------------------------------------

    block1_start = fajr
    block1_end = fajr + block1_duration

    # ----------------------------------------------
    # Block 2 starts at 18:00
    # ----------------------------------------------

    block2_start = fajr.replace(
        hour=18,
        minute=0,
        second=0,
        microsecond=0
    )

    if block2_start < fajr:
        block2_start += timedelta(days=1)

    block2_end = block2_start + remaining

    return {
        "total": target,
        "remain": remaining,
        "block1_start": block1_start,
        "block1_end": block1_end,
        "block2_start": block2_start,
        "block2_end": block2_end,
    }


# ==================================================
# Read input CSV
# ==================================================

with open(
    INPUT_FILE,
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    rows = list(csv.DictReader(f))


# ==================================================
# Basic calculations + work blocks
# ==================================================

for i, row in enumerate(rows):

    # Current day's times
    fajr = parse_time(row["Fajr"])
    sunrise = parse_time(row["Sunrise"])
    sunset = parse_time(row["Sunset"])
    isha = parse_time(row["Isha"])

    # ----------------------------------------------
    # Sunrise -> Sunset
    # ----------------------------------------------

    row["Day long"] = duration_string(
        sunrise,
        sunset
    )

    # ----------------------------------------------
    # Fajr -> Isha
    # ----------------------------------------------

    row["Fajr to Isha"] = duration_string(
        fajr,
        isha
    )

    # ----------------------------------------------
    # Sunset -> NEXT Sunrise
    # ----------------------------------------------

    if i + 1 < len(rows):

        next_sunrise = parse_time(
            rows[i + 1]["Sunrise"]
        )

        row["Night long"] = duration_string(
            sunset,
            next_sunrise
        )

    else:
        row["Night long"] = ""

    # ----------------------------------------------
    # Isha -> NEXT Fajr
    # ----------------------------------------------

    if i + 1 < len(rows):

        next_fajr = parse_time(
            rows[i + 1]["Fajr"]
        )

        row["Isha to Fajr"] = duration_string(
            isha,
            next_fajr
        )

    else:
        row["Isha to Fajr"] = ""

    # ==================================================
    # 50% calculation
    # ==================================================

    work50 = calculate_work_blocks(
        fajr,
        isha,
        0.50
    )

    row["50_percent_total_before_14"] = timedelta_to_string(
        work50["total"]
    )

    row["50_percent_remain"] = timedelta_to_string(
        work50["remain"]
    )

    row["50_percent_block1_start"] = (
        work50["block1_start"].strftime("%H:%M")
    )

    row["50_percent_block1_end"] = (
        work50["block1_end"].strftime("%H:%M")
    )

    row["50_percent_block2_start"] = (
        work50["block2_start"].strftime("%H:%M")
    )

    row["50_percent_block2_end"] = (
        work50["block2_end"].strftime("%H:%M")
    )

    # ==================================================
    # 75% calculation
    # ==================================================

    work75 = calculate_work_blocks(
        fajr,
        isha,
        0.75
    )

    row["75_percent_total_before_14"] = timedelta_to_string(
        work75["total"]
    )

    row["75_percent_remain"] = timedelta_to_string(
        work75["remain"]
    )

    row["75_percent_block1_start"] = (
        work75["block1_start"].strftime("%H:%M")
    )

    row["75_percent_block1_end"] = (
        work75["block1_end"].strftime("%H:%M")
    )

    row["75_percent_block2_start"] = (
        work75["block2_start"].strftime("%H:%M")
    )

    row["75_percent_block2_end"] = (
        work75["block2_end"].strftime("%H:%M")
    )


# ==================================================
# Wakeup + Bed
# ==================================================

for row in rows:

    # ----------------------------------------------
    # Wakeup = Fajr
    # ----------------------------------------------

    row["Wakeup_50"] = row["Fajr"]
    row["Wakeup_75"] = row["Fajr"]

    # ----------------------------------------------
    # Bed 50
    # max(Block 2 end, Isha)
    # ----------------------------------------------

    isha = parse_time(row["Isha"])

    block2_end_50 = parse_time(
        row["50_percent_block2_end"]
    )

    bed50 = max(
        block2_end_50,
        isha
    )

    row["Bed_50"] = bed50.strftime("%H:%M")

    # ----------------------------------------------
    # Bed 75
    # max(Block 2 end, Isha)
    # ----------------------------------------------

    block2_end_75 = parse_time(
        row["75_percent_block2_end"]
    )

    bed75 = max(
        block2_end_75,
        isha
    )

    row["Bed_75"] = bed75.strftime("%H:%M")


# ==================================================
# Total awake + total sleep
# ==================================================

for i, row in enumerate(rows):

    wake50 = parse_time(row["Wakeup_50"])
    bed50 = parse_time(row["Bed_50"])

    wake75 = parse_time(row["Wakeup_75"])
    bed75 = parse_time(row["Bed_75"])

    # ----------------------------------------------
    # Total awake
    # ----------------------------------------------

    row["50 total awake"] = duration_string(
        wake50,
        bed50
    )

    row["75 total awake"] = duration_string(
        wake75,
        bed75
    )

    # ----------------------------------------------
    # Total sleep = Bed -> NEXT Fajr
    # ----------------------------------------------

    if i + 1 < len(rows):

        next_wake50 = parse_time(
            rows[i + 1]["Wakeup_50"]
        )

        next_wake75 = parse_time(
            rows[i + 1]["Wakeup_75"]
        )

        row["50 total sleep"] = duration_string(
            bed50,
            next_wake50
        )

        row["75 total sleep"] = duration_string(
            bed75,
            next_wake75
        )

    else:
        row["50 total sleep"] = ""
        row["75 total sleep"] = ""


# ==================================================
# Overdrive
# ==================================================

for i, row in enumerate(rows):

    if i + 1 < len(rows):

        # ------------------------------------------
        # Default sleep = Isha -> NEXT Fajr
        # ------------------------------------------

        isha = parse_time(row["Isha"])
        next_fajr = parse_time(
            rows[i + 1]["Fajr"]
        )

        default_sleep = next_fajr - isha

        if default_sleep.total_seconds() < 0:
            default_sleep += timedelta(days=1)

        # ------------------------------------------
        # 50% actual sleep
        # ------------------------------------------

        bed50 = parse_time(
            row["Bed_50"]
        )

        actual_sleep_50 = next_fajr - bed50

        if actual_sleep_50.total_seconds() < 0:
            actual_sleep_50 += timedelta(days=1)

        # How much sleep was lost?
        overdrive_50 = max(
            timedelta(0),
            default_sleep - actual_sleep_50
        )

        row["50 overdrive"] = timedelta_to_string(
            overdrive_50
        )

        # ------------------------------------------
        # 75% actual sleep
        # ------------------------------------------

        bed75 = parse_time(
            row["Bed_75"]
        )

        actual_sleep_75 = next_fajr - bed75

        if actual_sleep_75.total_seconds() < 0:
            actual_sleep_75 += timedelta(days=1)

        # How much sleep was lost?
        overdrive_75 = max(
            timedelta(0),
            default_sleep - actual_sleep_75
        )

        row["75 overdrive"] = timedelta_to_string(
            overdrive_75
        )

    else:
        row["50 overdrive"] = ""
        row["75 overdrive"] = ""


# ==================================================
# Output columns
# ==================================================

fieldnames = [

    # Original prayer times
    "Date",
    "Fajr",
    "Sunrise",
    "Dhuhr",
    "Asr",
    "Sunset",
    "Maghrib",
    "Isha",
    "Imsak",
    "Midnight",
    "Firstthird",
    "Lastthird",

    # Basic calculations
    "Day long",
    "Night long",
    "Fajr to Isha",
    "Isha to Fajr",

    # 50% work
    "50_percent_total_before_14",
    "50_percent_remain",
    "50_percent_block1_start",
    "50_percent_block1_end",
    "50_percent_block2_start",
    "50_percent_block2_end",

    # 75% work
    "75_percent_total_before_14",
    "75_percent_remain",
    "75_percent_block1_start",
    "75_percent_block1_end",
    "75_percent_block2_start",
    "75_percent_block2_end",

    # 50% sleep
    "Wakeup_50",
    "Bed_50",
    "50 total awake",
    "50 total sleep",

    # 75% sleep
    "Wakeup_75",
    "Bed_75",
    "75 total awake",
    "75 total sleep",

    # Overdrive
    "50 overdrive",
    "75 overdrive",
]


# ==================================================
# Write output CSV
# ==================================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8-sig",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()
    writer.writerows(rows)


print("Done!")
print(f"Saved to: {OUTPUT_FILE}")
