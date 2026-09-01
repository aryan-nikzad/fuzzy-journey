import requests
import csv
import time

YEAR = 2026
LATITUDE = 32.3261
LONGITUDE = 50.8572
METHOD = 7

OUTPUT_FILE = f"shahrekord_prayer_times_{YEAR}.csv"

required_times = [
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
]

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:

    writer = csv.writer(f)

    # CSV header
    writer.writerow([
        "Date",
        *required_times
    ])

    # Request every month
    for month in range(1, 13):

        print(f"Requesting {YEAR}/{month}...")

        url = f"https://api.aladhan.com/v1/calendar/{YEAR}/{month}"

        params = {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "method": METHOD,
        }

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        response.raise_for_status()

        result = response.json()

        if result["code"] != 200:
            raise Exception(
                f"API error for {YEAR}/{month}: {result}"
            )

        data = result["data"]

        for day in data:

            timings = day["timings"]

            row = [
                day["date"]["gregorian"]["date"]
            ]

            for time_name in required_times:

                # "04:04 (+0330)" -> "04:04"
                value = timings[time_name].split(" ")[0]

                row.append(value)

            writer.writerow(row)

        # Avoid hitting API too quickly
        time.sleep(0.5)


print()
print(f"Done!")
print(f"Saved to: {OUTPUT_FILE}")
