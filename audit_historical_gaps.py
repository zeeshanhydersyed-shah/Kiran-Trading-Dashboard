#!/usr/bin/env python3
"""
audit_historical_gaps.py -- One-time historical gap audit for the Kiran PSX database.

What it does
------------
1. Pulls every distinct date from the prices table (2020-01-01 to today).
2. Builds the PSX trading calendar (Mon-Fri) for that range, excluding a
   hardcoded list of Pakistani public holidays.
3. Finds every calendar-expected date that is MISSING from the database.
4. Finds every date IN the database that falls on a weekend (mislabelled).
5. Writes gap_audit_YYYYMMDD.csv with columns:
      date | day_of_week | gap_type
   gap_type values:
      missing_likely_holiday    -- weekday in calendar, absent from DB, on known holiday list
      missing_unknown_gap       -- weekday in calendar, absent from DB, NOT on holiday list
      weekend_in_db             -- date present in DB but falls on Sat or Sun

DOES NOT modify the database. Read-only audit.

Usage
-----
    python audit_historical_gaps.py
"""

import csv
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AUDIT_START = date(2020, 1, 1)

try:
    from config import DB_PATH
except ImportError:
    DB_PATH = str(Path(__file__).parent / "psx_data.db")

# ---------------------------------------------------------------------------
# Pakistani Public Holidays 2020-2026
# (PSX is closed on these dates in addition to weekends)
#
# Sources:
#   Fixed national holidays: March 23, May 1, August 14, December 25, Feb 5
#   Islamic lunar holidays: Eid ul Fitr, Eid ul Adha, Ashura, Eid Milad un Nabi
#   (dates are approximate per moon-sighting; extended closure days included)
#   One-off: Pakistan General Election Day Feb 8 2024
#   Confirmed from ksestocks.com data: Eid ul Adha 2026 = May 26-28
#
# Holiday classification:
#   missing_likely_holiday = gap date is in this set
#   missing_unknown_gap    = gap date is NOT in this set (investigate)
# ---------------------------------------------------------------------------
PSX_HOLIDAYS: set[date] = {

    # 2020
    date(2020, 2,  5),   # Kashmir Solidarity Day (annual, every Feb 5)
    date(2020, 3, 23),   # Pakistan Day
    date(2020, 5,  1),   # Labour Day
    # Eid ul Fitr 2020 -- PSX closed May 22-27 (extended closure)
    date(2020, 5, 22), date(2020, 5, 24), date(2020, 5, 25),
    date(2020, 5, 26), date(2020, 5, 27),
    # Eid ul Adha 2020
    date(2020, 7, 31), date(2020, 8,  1), date(2020, 8,  2),
    date(2020, 8, 14),   # Independence Day
    # Ashura 2020
    date(2020, 8, 28), date(2020, 8, 29),
    # Eid Milad un Nabi 2020 -- PSX also closed Oct 30
    date(2020, 10, 29), date(2020, 10, 30),
    date(2020, 12, 25),

    # 2021
    date(2021, 2,  5),   # Kashmir Solidarity Day
    date(2021, 3, 23),
    date(2021, 5,  1),
    # Eid ul Fitr 2021 -- extended closure May 7-15
    date(2021, 5,  7), date(2021, 5, 10), date(2021, 5, 11),
    date(2021, 5, 12), date(2021, 5, 13), date(2021, 5, 14), date(2021, 5, 15),
    # Eid ul Adha 2021
    date(2021, 7, 20), date(2021, 7, 21), date(2021, 7, 22),
    date(2021, 8, 14),
    # Ashura 2021
    date(2021, 8, 18), date(2021, 8, 19),
    # Eid Milad un Nabi 2021
    date(2021, 10, 19),
    date(2021, 12, 25),

    # 2022
    date(2022, 2,  5),   # Kashmir Solidarity Day
    date(2022, 3, 23),
    date(2022, 4, 29),   # pre-Eid extended closure (Friday before Eid ul Fitr)
    date(2022, 5,  1),   # Labour Day
    date(2022, 5,  2), date(2022, 5,  3), date(2022, 5,  4),  # Eid ul Fitr 2022
    date(2022, 5,  5),   # post-Eid extended closure
    # Eid ul Adha 2022 -- extended closure Jul 8-12
    date(2022, 7,  8), date(2022, 7,  9), date(2022, 7, 10),
    date(2022, 7, 11), date(2022, 7, 12),
    # Ashura 2022 -- including day after
    date(2022, 8,  7), date(2022, 8,  8), date(2022, 8,  9),
    date(2022, 8, 14),
    # Eid Milad un Nabi 2022
    date(2022, 10,  8), date(2022, 10,  9),
    date(2022, 11,  9),  # Iqbal Day (PSX observed in 2022)
    date(2022, 12, 25),

    # 2023
    date(2023, 3, 23),
    # Eid ul Fitr 2023 -- extended closure Apr 14, 21-25
    date(2023, 4, 14),   # pre-Eid extended closure
    date(2023, 4, 21), date(2023, 4, 22), date(2023, 4, 23),
    date(2023, 4, 24), date(2023, 4, 25),  # post-Eid
    date(2023, 5,  1),
    # Eid ul Adha 2023
    date(2023, 6, 28), date(2023, 6, 29), date(2023, 6, 30),
    # Ashura 2023
    date(2023, 7, 28), date(2023, 7, 29),
    date(2023, 8, 14),
    # Eid Milad un Nabi 2023 -- including day after
    date(2023, 9, 28), date(2023, 9, 29),
    date(2023, 11,  9),  # Iqbal Day (PSX observed in 2023)
    date(2023, 12, 25),

    # 2024
    date(2024, 2,  5),   # Kashmir Solidarity Day
    date(2024, 2,  8),   # Pakistan General Election Day
    date(2024, 3, 23),
    # Eid ul Fitr 2024 -- pre-Eid closure Apr 5, then Apr 10-12
    date(2024, 4,  5),
    date(2024, 4, 10), date(2024, 4, 11), date(2024, 4, 12),
    date(2024, 5,  1),
    date(2024, 5, 28),   # PSX closure (confirmed gap; possibly Shab-e-Qadr or admin)
    # Eid ul Adha 2024
    date(2024, 6, 17), date(2024, 6, 18), date(2024, 6, 19),
    # Ashura 2024
    date(2024, 7, 16), date(2024, 7, 17),
    date(2024, 8, 14),
    # Eid Milad un Nabi 2024 -- including day after
    date(2024, 9, 16), date(2024, 9, 17),
    date(2024, 12, 25),

    # 2025
    date(2025, 2,  5),   # Kashmir Solidarity Day
    date(2025, 3, 23),
    # Eid ul Fitr 2025 -- extended closure Mar 28, 30 - Apr 2
    date(2025, 3, 28),
    date(2025, 3, 30), date(2025, 3, 31), date(2025, 4,  1),
    date(2025, 4,  2),
    date(2025, 5,  1),
    date(2025, 5, 28),   # PSX closure (same pattern as 2024-05-28; likely Shab-e-Qadr)
    # Eid ul Adha 2025 -- including day after (Jun 6-9)
    date(2025, 6,  6), date(2025, 6,  7), date(2025, 6,  8), date(2025, 6,  9),
    # Ashura 2025
    date(2025, 7,  5), date(2025, 7,  6),
    date(2025, 8, 14),
    # Eid Milad un Nabi 2025
    date(2025, 9,  5),
    date(2025, 12, 25),

    # 2026
    date(2026, 2,  5),   # Kashmir Solidarity Day
    # Eid ul Fitr 2026
    date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 21),
    date(2026, 3, 23),   # Pakistan Day
    date(2026, 5,  1),   # Labour Day
    date(2026, 5,  4),   # PSX extended closure (Monday after Labour Day weekend)
    # Eid ul Adha 2026 -- confirmed May 26-28; PSX also closed May 29
    date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29),
    # Ashura 2026
    date(2026, 6, 25), date(2026, 6, 26),
    date(2026, 8, 14),
    # Eid Milad un Nabi 2026
    date(2026, 8, 25),
    date(2026, 12, 25),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def get_db_dates() -> set[str]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT DISTINCT date FROM prices").fetchall()
    conn.close()
    return {r[0] for r in rows}


def build_trading_calendar(start: date, end: date) -> list[date]:
    """All weekdays in [start, end] that are NOT in PSX_HOLIDAYS."""
    result = []
    d = start
    while d <= end:
        if _is_weekday(d) and d not in PSX_HOLIDAYS:
            result.append(d)
        d += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

def run_audit() -> None:
    today     = date.today()
    audit_end = today - timedelta(days=1)   # exclude today (may not be complete yet)

    print(f"\n{'=' * 60}")
    print(f"  PSX Historical Gap Audit")
    print(f"  Range: {AUDIT_START} to {audit_end}")
    print(f"  DB: {DB_PATH}")
    print(f"{'=' * 60}\n")

    # Step 1: load DB dates
    db_dates = get_db_dates()
    print(f"Distinct dates in DB:  {len(db_dates)}")

    # Step 2: build expected trading calendar
    trading_calendar     = build_trading_calendar(AUDIT_START, audit_end)
    trading_calendar_set = {d.strftime("%Y-%m-%d") for d in trading_calendar}
    print(f"Expected trading days: {len(trading_calendar)}")

    # Step 3: find gaps (expected but missing)
    missing = []
    for d in trading_calendar:
        ds = d.strftime("%Y-%m-%d")
        if ds not in db_dates:
            gap_type = (
                "missing_likely_holiday"
                if d in PSX_HOLIDAYS
                else "missing_unknown_gap"
            )
            missing.append({
                "date":        ds,
                "day_of_week": d.strftime("%A"),
                "gap_type":    gap_type,
            })

    # Step 4: find weekend dates in DB (mislabelled)
    weekend_rows = []
    for ds in sorted(db_dates):
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if not _is_weekday(d):
            weekend_rows.append({
                "date":        ds,
                "day_of_week": d.strftime("%A"),
                "gap_type":    "weekend_in_db",
            })

    # Step 5: write CSV
    all_rows  = sorted(missing + weekend_rows, key=lambda r: r["date"])
    today_str = today.strftime("%Y%m%d")
    csv_path  = Path(__file__).parent / f"gap_audit_{today_str}.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "day_of_week", "gap_type"])
        writer.writeheader()
        writer.writerows(all_rows)

    # Step 6: print summary
    unknown_gaps  = [r for r in missing if r["gap_type"] == "missing_unknown_gap"]
    likely_hols   = [r for r in missing if r["gap_type"] == "missing_likely_holiday"]
    weekend_in_db = weekend_rows

    print(f"\n{'─' * 60}")
    print(f"  SUMMARY")
    print(f"{'─' * 60}")
    print(f"  Missing -- unknown gap (data integrity issue): {len(unknown_gaps)}")
    print(f"  Missing -- likely holiday (expected):          {len(likely_hols)}")
    print(f"  Weekend dates IN database (mislabelled):       {len(weekend_in_db)}")
    print(f"{'─' * 60}")

    if unknown_gaps:
        print(f"\n  WARNING -- UNKNOWN GAPS (potential data integrity issues):")
        for r in unknown_gaps:
            print(f"     {r['date']}  ({r['day_of_week']})")
    else:
        print("\n  OK  No unknown gaps found.")

    if weekend_in_db:
        print(f"\n  WARNING -- WEEKEND DATES IN DB (mislabelled records):")
        for r in weekend_in_db:
            print(f"     {r['date']}  ({r['day_of_week']})")
    else:
        print("  OK  No weekend dates found in DB.")

    if likely_hols:
        print(f"\n  INFO  Likely holidays accounted for ({len(likely_hols)} dates -- first 10 shown):")
        for r in likely_hols[:10]:
            print(f"     {r['date']}  ({r['day_of_week']})")
        if len(likely_hols) > 10:
            print(f"     ... and {len(likely_hols) - 10} more (see CSV)")

    print(f"\n  Full audit written to: {csv_path}")
    print()


if __name__ == "__main__":
    run_audit()
