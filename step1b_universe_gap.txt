# run: python step1b_universe_gap.py
import sqlite3, re

DB = "psx_data.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

print("=" * 70)
print("STEP 1B — UNIVERSE GAP ANALYSIS (filtered)")
print("=" * 70)

# Futures pattern — matches SHEL-FEB, TOMCL-FEBB, LUCK-MARR, etc.
FUTURES_RE = re.compile(
    r'-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)B?$',
    re.IGNORECASE
)

# Pull all symbols from prices not in stock_metadata
cur.execute("""
    SELECT symbol, MIN(date) as first_price, MAX(date) as last_price, COUNT(*) as days
    FROM prices
    WHERE symbol NOT IN (SELECT symbol FROM stock_metadata)
    GROUP BY symbol
""")
all_missing = cur.fetchall()

# Get symbols with a known sector in the sectors table
cur.execute("SELECT DISTINCT symbol FROM sectors WHERE sector IS NOT NULL AND sector != ''")
sectored = {r[0] for r in cur.fetchall()}

# Apply both filters
rows = []
skipped_futures = 0
skipped_no_sector = 0
for symbol, first, last, days in all_missing:
    if FUTURES_RE.search(symbol):
        skipped_futures += 1
        continue
    if symbol not in sectored:
        skipped_no_sector += 1
        continue
    rows.append((symbol, first, last, days))

# Sort by last_price DESC
rows.sort(key=lambda x: x[2], reverse=True)

print(f"\n  Raw symbols in prices not in metadata : {len(all_missing)}")
print(f"  Excluded — futures contracts          : {skipped_futures}")
print(f"  Excluded — no known sector            : {skipped_no_sector}")
print(f"  Remaining clean candidates            : {len(rows)}")

print(f"\n--- CLEAN MISSING SYMBOLS (in prices, not in metadata, known sector) ---")
print(f"  {'symbol':14} {'first_price':12} {'last_price':12} {'days':>6}")
print("  " + "-" * 50)
for r in rows:
    print(f"  {r[0]:14} {r[1]:12} {r[2]:12} {r[3]:>6}")

# Breakdown by last_price era
pre2024  = sum(1 for r in rows if r[2] < '2024-01-01')
post2024 = sum(1 for r in rows if r[2] >= '2024-01-01')
print(f"\n  Of the {len(rows)} clean candidates:")
print(f"    last_price < 2024-01-01  (likely delisted) : {pre2024}")
print(f"    last_price >= 2024-01-01 (recently active)  : {post2024}")

conn.close()
print("\n" + "=" * 70)
print("STEP 1B COMPLETE — share output before any further steps")
print("=" * 70)