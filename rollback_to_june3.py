#!/usr/bin/env python3
"""
ROLLBACK: Restore database to June 3 state only.
ksestocks has NOT provided June 4 data yet.
"""

import sqlite3
from database import init_db, get_latest_stock_date, count_prices

init_db()

print("=" * 80)
print("ROLLBACK: Restore to June 3 State")
print("=" * 80)
print()

# Current state
latest_before = get_latest_stock_date()
count_before = count_prices()
print(f"[BEFORE] Latest: {latest_before}, Total records: {count_before}")

# Delete June 4 data (which shouldn't exist)
print()
print("[ACTION] Deleting June 4 data from database...")
conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()

cursor.execute("DELETE FROM prices WHERE date = '2026-06-04'")
deleted_prices = cursor.rowcount
print(f"  Deleted {deleted_prices} price records")

cursor.execute("DELETE FROM index_prices WHERE date = '2026-06-04'")
deleted_indices = cursor.rowcount
print(f"  Deleted {deleted_indices} index records")

conn.commit()
conn.close()

# Verify state
latest_after = get_latest_stock_date()
count_after = count_prices()
print()
print(f"[AFTER] Latest: {latest_after}, Total records: {count_after}")
print()

# Verify June 3 is intact
conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM prices WHERE date = '2026-06-03'")
june3_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM index_prices WHERE date = '2026-06-03'")
june3_indices = cursor.fetchone()[0]
conn.close()

print(f"[VERIFICATION]")
print(f"  June 3 price records: {june3_count}")
print(f"  June 3 index records: {june3_indices}")
print()

if latest_after == "2026-06-03" and june3_count > 0:
    print("[SUCCESS] Database rolled back to June 3 state")
    print("  Latest date: June 3, 2026 ✓")
    print("  June 3 data intact: Yes ✓")
    print("  June 4 data removed: Yes ✓")
else:
    print("[ERROR] Rollback incomplete")

print()
print("=" * 80)
