import sqlite3
from stock_signals import update_base_tightness_vol_contraction

update_base_tightness_vol_contraction()

DB = 'psx_data.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# 1. NULL counts
cur.execute("SELECT COUNT(*) FROM stock_signals WHERE base_tightness IS NULL")
print("base_tightness NULLs:", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM stock_signals WHERE vol_contraction IS NULL")
print("vol_contraction NULLs:", cur.fetchone()[0])

# 2. Sample 10 rows base_tightness < 8 for 2026-06-11
print("\nSample 10 rows base_tightness < 8 on 2026-06-11 (ASC):")
cur.execute("""
    SELECT symbol, base_tightness, vol_contraction
    FROM stock_signals
    WHERE date = '2026-06-11' AND base_tightness < 8
    ORDER BY base_tightness ASC
    LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r}")

# 3. Sample 10 rows vol_contraction < 70 for 2026-06-11
print("\nSample 10 rows vol_contraction < 70 on 2026-06-11 (ASC):")
cur.execute("""
    SELECT symbol, base_tightness, vol_contraction
    FROM stock_signals
    WHERE date = '2026-06-11' AND vol_contraction < 70
    ORDER BY vol_contraction ASC
    LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r}")

# 4. Count both < thresholds
cur.execute("""
    SELECT COUNT(*)
    FROM stock_signals
    WHERE date = '2026-06-11'
      AND base_tightness < 8
      AND vol_contraction < 70
""")
print("\nRows with base_tightness < 8 AND vol_contraction < 70 on 2026-06-11:", cur.fetchone()[0])

conn.close()
