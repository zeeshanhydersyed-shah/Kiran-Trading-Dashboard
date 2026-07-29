import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

print("1. NULL count for high in prices_adjusted:")
cur.execute("SELECT COUNT(*) as null_highs FROM prices_adjusted WHERE high IS NULL")
print(f"  {cur.fetchone()}")

print("\n2. Sample 10 rows for OGDC (symbol, date, close, high, low, volume):")
cur.execute("""
SELECT symbol, date, close, high, low, volume
FROM prices_adjusted
WHERE symbol = 'OGDC'
ORDER BY date DESC
LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r}")

print("\n3. NULL count for low in prices_adjusted:")
cur.execute("SELECT COUNT(*) as null_lows FROM prices_adjusted WHERE low IS NULL")
print(f"  {cur.fetchone()}")

conn.close()
