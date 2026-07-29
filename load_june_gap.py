"""
load_june_gap.py
----------------
One-time script: recovers June 8-11 prices from psx_data_corrupted.db
and inserts them into psx_data.db.

Run from psx_pipeline root:
    python load_june_gap.py
"""

import sqlite3, os, sys

BASE     = os.path.dirname(os.path.abspath(__file__))
CORRUPT  = os.path.join(BASE, "psx_data_corrupted.db")
LIVE     = os.path.join(BASE, "psx_data.db")

# ── Step 1: extract June 8-11 from corrupted DB ──────────────
print("Step 1 — Extracting June 8-11 rows from psx_data_corrupted.db...")
if not os.path.exists(CORRUPT):
    print("ERROR: psx_data_corrupted.db not found.")
    sys.exit(1)

src = sqlite3.connect(CORRUPT)
src.execute("PRAGMA writable_schema=ON")
src_cur = src.cursor()

src_cur.execute("SELECT symbol FROM sectors")
all_syms = [r[0] for r in src_cur.fetchall()]
print(f"  Probing {len(all_syms)} symbols...")

recovered = []
errors = 0
for sym in all_syms:
    try:
        src_cur.execute(
            "SELECT symbol,date,close,volume,high,low,open "
            "FROM prices WHERE symbol=? AND date>='2026-06-06'",
            (sym,)
        )
        rows = src_cur.fetchall()
        if rows:
            recovered.extend(rows)
    except:
        errors += 1

src.close()
print(f"  Recovered: {len(recovered)} rows from {len(set(r[0] for r in recovered))} symbols")
print(f"  Dates:     {sorted(set(r[1] for r in recovered))}")
print(f"  Symbols errored (corrupt pages): {errors}")

# ── Step 2: insert into live DB ───────────────────────────────
print("\nStep 2 — Inserting into psx_data.db...")
dst = sqlite3.connect(LIVE)
dst.execute("PRAGMA synchronous=NORMAL")
dst.execute("BEGIN")
dst.executemany(
    "INSERT OR IGNORE INTO prices(symbol,date,close,volume,high,low,open) VALUES(?,?,?,?,?,?,?)",
    recovered
)
dst.commit()

cur = dst.cursor()
cur.execute("SELECT COUNT(*) FROM prices WHERE date>='2026-06-08'")
print(f"  Jun 8-11 rows in DB: {cur.fetchone()[0]}")
cur.execute("SELECT MAX(date) FROM prices")
print(f"  Latest date in DB:   {cur.fetchone()[0]}")
dst.close()

# ── Step 3: recover index_prices June 8-11 ───────────────────
print("\nStep 3 — Extracting June 8-11 index_prices from corrupted DB...")
src = sqlite3.connect(CORRUPT)
src.execute("PRAGMA writable_schema=ON")
src_cur = src.cursor()

idx_recovered = []
try:
    src_cur.execute(
        "SELECT symbol,date,high,low,close,open FROM index_prices WHERE date>='2026-06-06'"
    )
    idx_recovered = src_cur.fetchall()
    print(f"  Recovered: {len(idx_recovered)} index rows")
    print(f"  Dates:     {sorted(set(r[1] for r in idx_recovered))}")
    print(f"  Symbols:   {sorted(set(r[0] for r in idx_recovered))}")
except Exception as e:
    print(f"  ERROR reading index_prices: {e}")
src.close()

if idx_recovered:
    dst = sqlite3.connect(LIVE)
    dst.execute("PRAGMA synchronous=NORMAL")
    dst.execute("BEGIN")
    dst.executemany(
        "INSERT OR IGNORE INTO index_prices(symbol,date,high,low,close,open) VALUES(?,?,?,?,?,?)",
        idx_recovered
    )
    dst.commit()
    cur = dst.cursor()
    cur.execute("SELECT MAX(date) FROM index_prices")
    print(f"  Latest index date in DB: {cur.fetchone()[0]}")
    dst.close()

print("\n✅ Done. Restart Kiran to see updated data.")
print("   GitHub Actions will add June 12 automatically at ~22:00.")
