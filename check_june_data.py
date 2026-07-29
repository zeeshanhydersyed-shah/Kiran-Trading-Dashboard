#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()

print("June 2026 dates in database:")
cursor.execute("SELECT DISTINCT date FROM prices WHERE date LIKE '2026-06%' ORDER BY date DESC")
for row in cursor.fetchall():
    cursor.execute(f"SELECT COUNT(*) FROM prices WHERE date = '{row[0]}'")
    count = cursor.fetchone()[0]
    print(f"  {row[0]}: {count} records")

print()
print("Checking for June 3:")
cursor.execute("SELECT COUNT(*) FROM prices WHERE date = '2026-06-03'")
result = cursor.fetchone()[0]
print(f"June 3 records: {result}")

if result == 0:
    print("June 3 is MISSING from database!")
    print()
    print("This means either:")
    print("1. June 3 data was never scraped")
    print("2. June 3 data was relabeled (stale detection triggered)")
    print("3. June 3 data was deleted")

conn.close()
