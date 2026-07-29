# run: python step1b_universe_gap.py
import sqlite3

DB = "psx_data.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

print("=" * 70)
print("STEP 1B — UNIVERSE GAP ANALYSIS")
print("=" * 70)

# Total distinct symbols in prices
cur.execute("SELECT COUNT(DISTINCT symbol) FROM prices")
total_in_prices = cur.fetchone()[0]
print(f"\n  Distinct symbols in prices table     : {total_in_prices}")
print(f"  Symbols in stock_metadata            : 314")

# Symbols in prices but NOT in stock_metadata
cur.execute("""
    SELECT COUNT(DISTINCT symbol) FROM prices
    WHERE symbol NOT IN (SELECT symbol FROM stock_metadata)
""")
missing = cur.fetchone()[0]
print(f"  In prices but MISSING from metadata  : {missing}")

# Full list of missing symbols with their date range and trading days
print("\n--- SYMBOLS IN prices BUT NOT IN stock_metadata ---")
cur.execute("""
    SELECT symbol,
           MIN(date) as first_price,
           MAX(date) as last_price,
           COUNT(*) as trading_days
    FROM prices
    WHERE symbol NOT IN (SELECT symbol FROM stock_metadata)
    GROUP BY symbol
    ORDER BY last_price DESC
""")
rows = cur.fetchall()
print(f"  {'symbol':12} {'first_price':12} {'last_price':12} {'days':>6}")
print("  " + "-" * 50)
for r in rows:
    print(f"  {r[0]:12} {r[1]:12} {r[2]:12} {r[3]:>6}")

# Breakdown: how many missing symbols are likely delisted vs recent
cur.execute("""
    SELECT
        SUM(CASE WHEN last_price < '2024-01-01' THEN 1 ELSE 0 END) as pre2024,
        SUM(CASE WHEN last_price >= '2024-01-01' THEN 1 ELSE 0 END) as post2024
    FROM (
        SELECT symbol, MAX(date) as last_price
        FROM prices
        WHERE symbol NOT IN (SELECT symbol FROM stock_metadata)
        GROUP BY symbol
    )
""")
r = cur.fetchone()
print(f"\n  Of the {missing} missing symbols:")
print(f"    last_price < 2024-01-01  (likely delisted) : {r[0]}")
print(f"    last_price >= 2024-01-01 (recently active) : {r[1]}")

conn.close()
print("\n" + "=" * 70)
print("STEP 1B COMPLETE — share output before any further steps")
print("=" * 70)