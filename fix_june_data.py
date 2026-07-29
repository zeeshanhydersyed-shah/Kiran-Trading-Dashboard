#!/usr/bin/env python3
"""
Fix the June 3 vs June 4 data issue.

This script:
1. Detects the mislabeled data
2. Scrapes fresh June 3 and June 4 data from ksestocks
3. Relabels and saves correctly
4. Removes incorrect labels
"""

import logging
from datetime import date
from database import get_latest_stock_date, init_db, upsert_prices, upsert_index_prices, count_prices
from scraper import scrape_date, scrape_date_range, build_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("=" * 80)
print("FIX SCRIPT: Correct June 3 vs June 4 Data Issue")
print("=" * 80)
print()

init_db()

# Check current state
latest = get_latest_stock_date()
print(f"[1] Current database state: Latest date = {latest}")

# Verify the issue
if latest == "2026-06-04":
    print("    Problem detected: June 4 is labeled but ksestocks only has June 3")
    print()

    # Check if June 3 exists
    import sqlite3
    conn = sqlite3.connect('psx_data.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM prices WHERE date = '2026-06-03'")
    june3_count = cursor.fetchone()[0]
    conn.close()

    if june3_count == 0:
        print("    June 3 is completely missing!")
        print()
        print("[2] Restoring June 3 and June 4 data...")
        print()

        # Scrape fresh data
        session = build_session()

        # First scrape June 3
        print("    Scraping June 3...")
        s_rows_3, p_rows_3, i_rows_3 = scrape_date(date(2026, 6, 3), session)
        print(f"    Got {len(p_rows_3)} price records")

        # Then scrape June 4
        print("    Scraping June 4...")
        s_rows_4, p_rows_4, i_rows_4 = scrape_date(date(2026, 6, 4), session)
        print(f"    Got {len(p_rows_4)} price records")
        print()

        # Clear the database June 4 records
        print("[3] Clearing incorrect June 4 records...")
        import sqlite3
        conn = sqlite3.connect('psx_data.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM prices WHERE date = '2026-06-04'")
        cursor.execute("DELETE FROM index_prices WHERE date = '2026-06-04'")
        conn.commit()
        conn.close()
        print("    Deleted incorrect June 4 data")
        print()

        # Save correct data
        print("[4] Saving correct data...")

        if p_rows_3:
            upsert_prices(p_rows_3)
            logger.info("Saved June 3 data: %d records", len(p_rows_3))

        if i_rows_3:
            upsert_index_prices(i_rows_3)
            logger.info("Saved June 3 index data: %d records", len(i_rows_3))

        if p_rows_4:
            upsert_prices(p_rows_4)
            logger.info("Saved June 4 data: %d records", len(p_rows_4))

        if i_rows_4:
            upsert_index_prices(i_rows_4)
            logger.info("Saved June 4 index data: %d records", len(i_rows_4))

        print()

        # Verify
        new_latest = get_latest_stock_date()
        new_count = count_prices()
        print("[5] Verification:")
        print(f"    Latest date: {new_latest}")
        print(f"    Total records: {new_count}")
        print()
        print("[SUCCESS] Data has been restored!")

    else:
        print(f"    June 3 exists with {june3_count} records")
        print("    No restoration needed")

elif latest == "2026-06-03":
    print("    Correct: Database shows June 3 (as expected)")
    print()
    print("[OK] No fix needed")
else:
    print(f"    Unexpected date: {latest}")
    print("    Manual investigation required")

print()
print("=" * 80)
