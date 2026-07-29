import sqlite3
from stock_signals import update_base_tightness_vol_contraction

update_base_tightness_vol_contraction()

DB = 'psx_data.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# 2. NULL count for avg_vol_10d
cur.execute("SELECT COUNT(*) FROM stock_signals WHERE avg_vol_10d IS NULL")
print("avg_vol_10d NULLs:", cur.fetchone()[0])

# 3. Sample 10 rows avg_vol_10d > 200000 AND base_tightness < 8 for 2026-06-11
print("\nSample 10 rows (avg_vol_10d > 200000 AND base_tightness < 8) on 2026-06-11 (base_tightness ASC):")
cur.execute("""
    SELECT symbol, base_tightness, vol_contraction, avg_vol_10d
    FROM stock_signals
    WHERE date = '2026-06-11'
      AND avg_vol_10d > 200000
      AND base_tightness < 8
    ORDER BY base_tightness ASC
    LIMIT 10
""")
for r in cur.fetchall():
    print(f"  {r}")

# 4. Count rows where all three conditions met
cur.execute("""
    SELECT COUNT(*)
    FROM stock_signals
    WHERE date = '2026-06-11'
      AND avg_vol_10d > 200000
      AND base_tightness < 8
      AND vol_contraction < 70
""")
print("\nRows with avg_vol_10d > 200000 AND base_tightness < 8 AND vol_contraction < 70 on 2026-06-11:", cur.fetchone()[0])

# 5. Min and max avg_vol_10d for 2026-06-11
cur.execute("""
    SELECT MIN(avg_vol_10d), MAX(avg_vol_10d)
    FROM stock_signals
    WHERE date = '2026-06-11'
""")
mn, mx = cur.fetchone()
print(f"\nMin avg_vol_10d on 2026-06-11: {mn:,.0f}")
print(f"Max avg_vol_10d on 2026-06-11: {mx:,.0f}")

conn.close()
