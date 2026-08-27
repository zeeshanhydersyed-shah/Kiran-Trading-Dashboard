"""
build_stock_metadata.py
-----------------------
Creates and (re)populates the stock_metadata master reference table in
psx_data.db.

IDEMPOTENT UPSERT - not a drop-and-rebuild.
    Historically this script did DROP TABLE + full re-insert, which destroyed
    every manually-added row on each run (the local table has been hand-expanded
    well beyond the ~314 symbols the `sectors` feed yields cleanly). It now:
      * never drops the table,
      * UPSERTs the computed "should-be-tracked" set (sector not excluded, plus
        config.UNIVERSE_WHITELIST), applying config.SECTOR_OVERRIDES,
      * leaves the `notes` column untouched (manual annotations survive),
      * never deletes - rows present but not in the computed set (manual /
        legacy / now-excluded) are reported and preserved.

Inclusion rule: symbols from the `sectors` table whose sector is NOT in
config.EXCLUDED_SECTORS, UNION config.UNIVERSE_WHITELIST. Sector labels are
run through config.SECTOR_OVERRIDES.

Run from psx_pipeline root:
    python build_stock_metadata.py
"""

import os
import sqlite3
import sys

from config import EXCLUDED_SECTORS, SECTOR_OVERRIDES, UNIVERSE_WHITELIST

BASE = os.path.dirname(os.path.abspath(__file__))
# STOCK_METADATA_DB lets the test suite point this at an isolated copy.
# Production runs leave it unset and hit the real psx_data.db.
DB   = os.environ.get("STOCK_METADATA_DB") or os.path.join(BASE, "psx_data.db")

ACTIVE_CUTOFF = "2024-01-01"  # latest price date < this -> delisted / inactive

print("=" * 60)
print("build_stock_metadata.py  (idempotent upsert)")
print("=" * 60)

if not os.path.exists(DB):
    print(f"ERROR: {DB} not found.")
    sys.exit(1)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# -- Step 1: CREATE TABLE IF NOT EXISTS (never drop) -----------
print("\nStep 1 - Ensuring stock_metadata table exists...")
con.execute("""
    CREATE TABLE IF NOT EXISTS stock_metadata (
        symbol        TEXT PRIMARY KEY,
        company_name  TEXT,
        sector        TEXT,
        listing_date  TEXT,
        delisting_date TEXT,
        is_active     INTEGER NOT NULL DEFAULT 1,
        in_kse100     INTEGER NOT NULL DEFAULT 0,
        notes         TEXT
    )
""")
con.commit()
existing_before = {r["symbol"] for r in cur.execute("SELECT symbol FROM stock_metadata")}
print(f"  Table present. {len(existing_before)} rows currently.")

# -- Step 2: Compute the include-set from `sectors` (+ whitelist) --
print("\nStep 2 - Computing include-set from sectors table...")
placeholders = ",".join("?" * len(EXCLUDED_SECTORS))
cur.execute(
    f"SELECT symbol, sector FROM sectors WHERE sector NOT IN ({placeholders})",
    tuple(EXCLUDED_SECTORS),
)
include = {r["symbol"]: r["sector"] for r in cur.fetchall()}

# Hard include-list: these are tracked regardless of what `sectors` says.
# Their real sector must come from SECTOR_OVERRIDES.
for sym in UNIVERSE_WHITELIST:
    if sym not in SECTOR_OVERRIDES:
        print(f"  WARNING: whitelist symbol {sym} has no SECTOR_OVERRIDES entry - skipping.")
        continue
    include[sym] = SECTOR_OVERRIDES[sym]

# Apply overrides across the whole set.
for sym, override in SECTOR_OVERRIDES.items():
    if sym in include:
        include[sym] = override

print(f"  {len(include)} symbols in include-set "
      f"({len(UNIVERSE_WHITELIST)} from whitelist).")

if not include:
    print("ERROR: include-set empty - check EXCLUDED_SECTORS against sectors table.")
    sys.exit(1)

# -- Step 3: Reference data (KSE-100 names, price ranges) ------
print("\nStep 3 - Loading kse100_constituents + price date ranges...")
cur.execute("SELECT symbol, company_name FROM kse100_constituents")
kse100 = {r["symbol"]: r["company_name"] for r in cur.fetchall()}
print(f"  {len(kse100)} KSE-100 constituents.")

syms = list(include)
price_ranges = {}
CHUNK = 900
for i in range(0, len(syms), CHUNK):
    part = syms[i:i + CHUNK]
    cur.execute(
        f"""
        SELECT symbol, MIN(date) AS first_date, MAX(date) AS last_date
        FROM prices
        WHERE symbol IN ({",".join("?" * len(part))})
        GROUP BY symbol
        """,
        part,
    )
    for r in cur.fetchall():
        price_ranges[r["symbol"]] = (r["first_date"], r["last_date"])
print(f"  Price ranges for {len(price_ranges)} / {len(syms)} symbols.")

no_price = sorted(set(include) - set(price_ranges))
if no_price:
    print(f"  !  {len(no_price)} include-set symbols have no price rows: {no_price[:10]}"
          f"{' ...' if len(no_price) > 10 else ''}")

# -- Step 4: UPSERT ------------------------------------------------
# On UPDATE we refresh only the source-derived columns (sector, company_name,
# in_kse100, listing_date). is_active / delisting_date / notes are manual-
# curation columns: a symbol that has been hand-flagged delisted (is_active=0)
# stays that way -- the rebuild must not silently re-activate it just because a
# stale price row happens to fall after ACTIVE_CUTOFF. Those three are set on
# INSERT only.
print("\nStep 4 - Upserting rows...")
rows = []
for symbol, sector in include.items():
    company_name = kse100.get(symbol)
    in_kse100    = 1 if symbol in kse100 else 0
    if symbol in price_ranges:
        listing_date, last_date = price_ranges[symbol]
        is_active      = 1 if last_date and last_date >= ACTIVE_CUTOFF else 0
        delisting_date = last_date if is_active == 0 else None
    else:
        listing_date = delisting_date = None
        is_active    = 0
    rows.append((symbol, company_name, sector, listing_date, delisting_date,
                 is_active, in_kse100))

con.executemany(
    """
    INSERT INTO stock_metadata
        (symbol, company_name, sector, listing_date, delisting_date,
         is_active, in_kse100, notes)
    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
    ON CONFLICT(symbol) DO UPDATE SET
        company_name = excluded.company_name,
        sector       = excluded.sector,
        listing_date = excluded.listing_date,
        in_kse100    = excluded.in_kse100
        -- is_active, delisting_date, notes: manual-curation columns,
        -- INSERT-only, never overwritten on a rebuild
    """,
    rows,
)
con.commit()

inserted = sorted(set(include) - existing_before)
updated  = sorted(set(include) & existing_before)
preserved = sorted(existing_before - set(include))
print(f"  Inserted : {len(inserted)}")
print(f"  Updated  : {len(updated)}")
print(f"  Preserved (manual / legacy / now-excluded, untouched): {len(preserved)}")

# -- Step 5: Validation report --------------------------------
print("\n" + "=" * 60)
print("VALIDATION REPORT")
print("=" * 60)

cur.execute("SELECT COUNT(*) FROM stock_metadata")
print(f"\nTotal rows          : {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE is_active = 1")
print(f"Active (is_active=1) : {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE in_kse100 = 1")
print(f"KSE-100 members     : {cur.fetchone()[0]}")

# Whitelist must all be present with their override sector.
print("\nUNIVERSE_WHITELIST check:")
for sym in sorted(UNIVERSE_WHITELIST):
    row = cur.execute(
        "SELECT sector, is_active FROM stock_metadata WHERE symbol = ?", (sym,)
    ).fetchone()
    want = SECTOR_OVERRIDES.get(sym)
    ok = row and row["sector"] == want
    print(f"  {sym:10s} -> {dict(row) if row else 'MISSING'}   "
          f"{'OK' if ok else 'MISMATCH (want ' + str(want) + ')'}")

if inserted:
    print(f"\nNewly inserted symbols: {inserted}")
if preserved:
    sample = preserved[:20]
    print(f"\nPreserved-untouched sample ({len(preserved)} total): {sample}"
          f"{' ...' if len(preserved) > 20 else ''}")

print("\nSector breakdown:")
cur.execute("""
    SELECT sector, COUNT(*) n, SUM(is_active) active, SUM(in_kse100) kse100
    FROM stock_metadata GROUP BY sector ORDER BY n DESC
""")
print(f"  {'Sector':<45} {'Total':>5} {'Active':>7} {'KSE100':>7}")
print("  " + "-" * 66)
for r in cur.fetchall():
    print(f"  {r[0]:<45} {r[1]:>5} {r[2] or 0:>7} {r[3] or 0:>7}")

print("\n[OK] stock_metadata upsert complete.")
print("=" * 60)
con.close()
