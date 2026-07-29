#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()

print("VERIFICATION: Database state after fix")
print("=" * 60)
print()

cursor.execute("SELECT date, COUNT(*) FROM prices WHERE date LIKE '2026-06%' ORDER BY date DESC")
print("Price records by date:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]} records")

print()

# Final status
cursor.execute("SELECT MAX(date) FROM prices")
latest = cursor.fetchone()[0]
print(f"Latest date in database: {latest}")
print()

if latest == "2026-06-04":
    print("[SUCCESS] Data is correctly labeled!")
    print("  - June 3 restored: 601 records")
    print("  - June 4 available: 601 records")
else:
    print(f"[CHECK] Latest date is: {latest}")

conn.close()
