import sqlite3
conn = sqlite3.connect('psx_data.db')
cur = conn.cursor()

# Check stock_metadata for DFC-related columns
print("stock_metadata cols:", [r[1] for r in cur.execute("PRAGMA table_info(stock_metadata)").fetchall()])
sample = cur.execute("SELECT * FROM stock_metadata LIMIT 3").fetchall()
for r in sample: print(' ', r)

# Check mv_signals is_dfc
print("\nmv_signals is_dfc - distinct values and counts:")
rows = cur.execute("SELECT is_dfc, COUNT(*) FROM mv_signals GROUP BY is_dfc").fetchall()
for r in rows: print(' ', r)

# Get the DFC symbols from mv_signals (most recent date)
print("\nDFC symbols (from mv_signals, latest date):")
latest = cur.execute("SELECT MAX(as_of_date) FROM mv_signals").fetchone()[0]
print(f"Latest mv_signals date: {latest}")
dfc_syms = cur.execute(
    "SELECT DISTINCT symbol FROM mv_signals WHERE is_dfc = 1 AND as_of_date = ?", (latest,)
).fetchall()
print(f"DFC count: {len(dfc_syms)}")
print([r[0] for r in dfc_syms])

conn.close()
