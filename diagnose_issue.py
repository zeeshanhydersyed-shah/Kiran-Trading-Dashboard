#!/usr/bin/env python3
"""Diagnose the June 3 vs June 4 data issue."""

import sqlite3
from datetime import date, timedelta
from scraper import scrape_date, build_session

conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()

print("=" * 80)
print("DATA INTEGRITY DIAGNOSIS")
print("=" * 80)
print()

# Check database state
print("[1] Database state:")
cursor.execute("SELECT date, COUNT(*) as cnt FROM prices GROUP BY date ORDER BY date DESC LIMIT 10")
print("  Recent dates:")
for row in cursor.fetchall():
    print(f"    {row[0]}: {row[1]} records")
print()

# Check what ksestocks actually has
print("[2] What ksestocks.com currently has:")
print("  Testing scrape_date for recent dates...")
print()

session = build_session()

# Try to scrape June 3
print("  Attempting to scrape 2026-06-03:")
try:
    s_rows, p_rows, i_rows = scrape_date(date(2026, 6, 3), session)
    if p_rows:
        print(f"    SUCCESS: Got {len(p_rows)} price records, {len(i_rows)} index records")
        # Show a sample
        if p_rows:
            sym, dt, o, h, l, c, v = p_rows[0]
            print(f"    Sample: {sym} on {dt}")
    else:
        print(f"    NO DATA: Empty response (holiday or not available)")
except Exception as e:
    print(f"    ERROR: {e}")
print()

# Try to scrape June 4
print("  Attempting to scrape 2026-06-04:")
try:
    s_rows, p_rows, i_rows = scrape_date(date(2026, 6, 4), session)
    if p_rows:
        print(f"    SUCCESS: Got {len(p_rows)} price records, {len(i_rows)} index records")
        # Show a sample
        if p_rows:
            sym, dt, o, h, l, c, v = p_rows[0]
            print(f"    Sample: {sym} on {dt}")
    else:
        print(f"    NO DATA: Empty response (holiday or not available)")
except Exception as e:
    print(f"    ERROR: {e}")
print()

# Analysis
print("[3] Analysis:")
print()
print("Issue: June 3 missing from database, June 4 present")
print()
print("Possible causes:")
print("  A) June 3 was never a trading date (weekend/holiday)")
print("  B) June 3 was scraped but relabeled to June 2 (stale detection)")
print("  C) June 4 data is actually what should be June 3 (mislabeled)")
print("  D) ksestocks returned June 3 data when June 4 was requested")
print()

conn.close()
