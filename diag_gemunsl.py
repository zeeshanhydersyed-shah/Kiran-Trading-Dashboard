import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

print("1. stock_metadata for GEMUNSL:")
cur.execute("""
SELECT symbol, sector, listing_date, delisting_date, is_active, in_kse100
FROM stock_metadata
WHERE symbol = 'GEMUNSL'
""")
for r in cur.fetchall():
    print(f"  {r}")

print("\n2. prices_adjusted for GEMUNSL:")
cur.execute("""
SELECT COUNT(*) as row_count, MIN(date) as first_date, MAX(date) as last_date
FROM prices_adjusted
WHERE symbol = 'GEMUNSL'
""")
for r in cur.fetchall():
    print(f"  {r}")

print("\n3. prices for GEMUNSL:")
cur.execute("""
SELECT COUNT(*) as row_count, MIN(date) as first_date, MAX(date) as last_date
FROM prices
WHERE symbol = 'GEMUNSL'
""")
for r in cur.fetchall():
    print(f"  {r}")

conn.close()
