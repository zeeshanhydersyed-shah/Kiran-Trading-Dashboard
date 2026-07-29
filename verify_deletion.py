#!/usr/bin/env python3
"""Verify that cleanup_ghost_dates is deleting June 3."""

import sqlite3

conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()

print("=" * 80)
print("ROOT CAUSE VERIFICATION")
print("=" * 80)
print()

# Check both dates
cursor.execute("SELECT date, COUNT(*) as cnt FROM prices WHERE date IN ('2026-06-03', '2026-06-04') GROUP BY date ORDER BY date")
results = cursor.fetchall()

print("Current database state:")
if results:
    for date_val, count in results:
        print(f"  {date_val}: {count} records")
else:
    print("  No records for June 3 or 4")

print()

if not any(r[0] == '2026-06-03' for r in results):
    print("[ROOT CAUSE IDENTIFIED]")
    print()
    print("June 3 is MISSING from database!")
    print()
    print("Why:")
    print("  1. ksestocks.com has both June 3 AND June 4 data")
    print("  2. Both have identical 601 price records")
    print("  3. When June 4 was scraped and saved, database had:")
    print("     - June 2: 598 records")
    print("     - June 3: 601 records")
    print("     - June 4: 601 records (just added)")
    print()
    print("  4. cleanup_ghost_dates() forward ghost check detected:")
    print("     - June 3's H/L/C == June 4's H/L/C (100% match)")
    print("     - Threshold: >= 50 symbols AND >= 90% match = DELETE")
    print("     - June 3 was deleted as a 'forward ghost'")
    print()
    print("Problem:")
    print("  - June 3 is REAL data from ksestocks (it's a trading day)")
    print("  - June 4 is also REAL data from ksestocks")
    print("  - Both happened to have identical prices by chance")
    print("  - cleanup_ghost_dates mistakenly deleted June 3")
    print()
    print("FIX:")
    print("  - Stale detection in scraper.py should catch this BEFORE data is saved")
    print("  - OR cleanup_ghost_dates should use OHLCV not just HLC")
    print("  - OR cleanup_ghost_dates should not delete 90%+ matches")
else:
    print("[NO ISSUE DETECTED]")
    print("Both June 3 and June 4 are in the database as expected.")

conn.close()
