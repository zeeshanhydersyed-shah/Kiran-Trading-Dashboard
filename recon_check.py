"""
Reconnaissance check for psx_data.db
Run: python recon_check.py
"""
import sqlite3

DB = r"C:\Users\Lenovo\psx_pipeline\psx_data.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

print("=" * 55)
print("PRICES TABLE")
print("=" * 55)
cur.execute("SELECT COUNT(*) FROM prices")
print(f"Total rows      : {cur.fetchone()[0]:,}")
cur.execute("SELECT MIN(date), MAX(date) FROM prices")
r = cur.fetchone()
print(f"Earliest date   : {r[0]}")
print(f"Latest date     : {r[1]}")
cur.execute("SELECT COUNT(DISTINCT symbol) FROM prices")
print(f"Distinct symbols: {cur.fetchone()[0]:,}")

print()
print("=" * 55)
print("INDEX_PRICES TABLE")
print("=" * 55)
cur.execute("SELECT COUNT(*) FROM index_prices")
print(f"Total rows      : {cur.fetchone()[0]:,}")
cur.execute("SELECT MIN(date), MAX(date) FROM index_prices")
r = cur.fetchone()
print(f"Earliest date   : {r[0]}")
print(f"Latest date     : {r[1]}")
cur.execute("SELECT DISTINCT symbol FROM index_prices ORDER BY symbol")
print(f"Index symbols   : {[row[0] for row in cur.fetchall()]}")

print()
print("=" * 55)
print("SCHEMA CHECK")
print("=" * 55)
cur.execute("PRAGMA table_info(prices)")
print("prices columns:", [row[1] for row in cur.fetchall()])
cur.execute("PRAGMA table_info(index_prices)")
print("index_prices columns:", [row[1] for row in cur.fetchall()])

conn.close()
print()
print("Done. Paste this output back.")
