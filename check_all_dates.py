#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('psx_data.db')
cursor = conn.cursor()

print("All June dates in database:")
cursor.execute("SELECT DISTINCT date FROM prices WHERE date LIKE '2026-06%' ORDER BY date DESC")
dates = cursor.fetchall()

if dates:
    for row in dates:
        date_val = row[0]
        cursor.execute(f"SELECT COUNT(*) FROM prices WHERE date = '{date_val}'")
        count = cursor.fetchone()[0]
        print(f"  {date_val}: {count} records")
else:
    print("  (No June 2026 data found)")

    # Check all dates in database
    print()
    print("Available dates in database:")
    cursor.execute("SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 20")
    for row in cursor.fetchall():
        cursor.execute(f"SELECT COUNT(*) FROM prices WHERE date = '{row[0]}'")
        count = cursor.fetchone()[0]
        print(f"  {row[0]}: {count} records")

conn.close()
