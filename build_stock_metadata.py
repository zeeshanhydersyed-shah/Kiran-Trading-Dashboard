"""
build_stock_metadata.py
-----------------------
Creates and populates the stock_metadata master reference table in psx_data.db.

Inclusion rule: 473 clean symbols from sectors table, excluding:
  - FUTURE CONTRACTS
  - STOCK INDEX FUTURE CONTRACTS
  - Unknown Sector
  - All 12 sectors in EXCLUDED_SECTORS (config.py)

Run from psx_pipeline root:
    python build_stock_metadata.py
"""

import sqlite3
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "psx_data.db")

# Mirror of config.py EXCLUDED_SECTORS — kept inline so this script is self-contained
EXCLUDED_SECTORS = {
    "CLOSE - END MUTUAL FUND",
    "INV. BANKS / INV. COS. / SECURITIES COS.",
    "LEASING COMPANIES",
    "LEATHER & TANNERIES",
    "MODARABAS",
    "SUGAR & ALLIED INDUSTRIES",
    "SYNTHETIC & RAYON",
    "TEXTILE SPINNING",
    "TEXTILE WEAVING",
    "TOBACCO",
    "VANASPATI & ALLIED INDUSTRIES",
    "WOOLLEN",
    "Unknown Sector",
    "FUTURE CONTRACTS",
    "STOCK INDEX FUTURE CONTRACTS",
}

ACTIVE_CUTOFF = "2024-01-01"  # latest price date < this → delisted / inactive

print("=" * 60)
print("build_stock_metadata.py")
print("=" * 60)

if not os.path.exists(DB):
    print(f"ERROR: {DB} not found.")
    sys.exit(1)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ── Step 1: CREATE TABLE ──────────────────────────────────────
print("\nStep 1 — Creating stock_metadata table...")
con.execute("DROP TABLE IF EXISTS stock_metadata")
con.execute("""
    CREATE TABLE stock_metadata (
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
print("  Table created (or replaced).")

# ── Step 2: Pull clean symbols from sectors ───────────────────
print("\nStep 2 — Pulling clean symbols from sectors table...")
placeholders = ",".join("?" * len(EXCLUDED_SECTORS))
cur.execute(
    f"SELECT symbol, sector FROM sectors WHERE sector NOT IN ({placeholders})",
    tuple(EXCLUDED_SECTORS)
)
sector_rows = {r["symbol"]: r["sector"] for r in cur.fetchall()}
print(f"  {len(sector_rows)} clean symbols found.")

if not sector_rows:
    print("ERROR: No symbols found — check EXCLUDED_SECTORS against sectors table.")
    sys.exit(1)

# ── Step 3: Pull kse100_constituents ─────────────────────────
print("\nStep 3 — Loading kse100_constituents...")
cur.execute("SELECT symbol, company_name FROM kse100_constituents")
kse100 = {r["symbol"]: r["company_name"] for r in cur.fetchall()}
print(f"  {len(kse100)} KSE-100 constituents loaded.")

# ── Step 4: Pull price date ranges per symbol ─────────────────
print("\nStep 4 — Computing price date ranges per symbol...")
syms_in = tuple(sector_rows.keys())
if len(syms_in) == 1:
    syms_in = syms_in + ("__dummy__",)  # sqlite tuple edge case

cur.execute(
    f"""
    SELECT symbol, MIN(date) AS first_date, MAX(date) AS last_date
    FROM prices
    WHERE symbol IN ({','.join('?' * len(syms_in))})
    GROUP BY symbol
    """,
    syms_in
)
price_ranges = {r["symbol"]: (r["first_date"], r["last_date"]) for r in cur.fetchall()}
print(f"  Price ranges found for {len(price_ranges)} symbols.")

no_price_syms = set(sector_rows) - set(price_ranges)
if no_price_syms:
    print(f"  ⚠  {len(no_price_syms)} symbols in sectors but no price rows: {sorted(no_price_syms)[:10]}...")

# ── Step 5: Assemble and insert rows ─────────────────────────
print("\nStep 5 — Assembling and inserting rows...")
rows = []
for symbol, sector in sector_rows.items():
    company_name  = kse100.get(symbol)          # None if not KSE-100
    in_kse100     = 1 if symbol in kse100 else 0

    if symbol in price_ranges:
        listing_date, last_date = price_ranges[symbol]
        is_active      = 1 if last_date >= ACTIVE_CUTOFF else 0
        delisting_date = last_date if is_active == 0 else None
    else:
        listing_date   = None
        last_date      = None
        is_active      = 0
        delisting_date = None

    rows.append((
        symbol,
        company_name,
        sector,
        listing_date,
        delisting_date,
        is_active,
        in_kse100,
        None,          # notes — blank by default
    ))

con.executemany(
    """
    INSERT INTO stock_metadata
        (symbol, company_name, sector, listing_date, delisting_date, is_active, in_kse100, notes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    rows
)
con.commit()
print(f"  Inserted {len(rows)} rows.")

# ── Step 6: Validation report ─────────────────────────────────
print("\n" + "=" * 60)
print("VALIDATION REPORT")
print("=" * 60)

cur.execute("SELECT COUNT(*) FROM stock_metadata")
total = cur.fetchone()[0]
print(f"\nTotal rows          : {total}")

cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE is_active = 1")
active = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE is_active = 0")
inactive = cur.fetchone()[0]
print(f"Active (is_active=1): {active}")
print(f"Inactive (0)        : {inactive}")

cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE in_kse100 = 1")
kse_count = cur.fetchone()[0]
print(f"KSE-100 members     : {kse_count}")

cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE company_name IS NOT NULL")
named = cur.fetchone()[0]
print(f"With company_name   : {named}  (only KSE-100 stocks have names)")

cur.execute("SELECT COUNT(*) FROM stock_metadata WHERE listing_date IS NULL")
no_price = cur.fetchone()[0]
print(f"No price data       : {no_price}")

print("\nSector breakdown:")
cur.execute("""
    SELECT sector, COUNT(*) n,
           SUM(is_active) active,
           SUM(in_kse100) kse100
    FROM stock_metadata
    GROUP BY sector
    ORDER BY n DESC
""")
print(f"  {'Sector':<45} {'Total':>5} {'Active':>7} {'KSE100':>7}")
print("  " + "-" * 66)
for r in cur.fetchall():
    print(f"  {r[0]:<45} {r[1]:>5} {r[2]:>7} {r[3]:>7}")

print("\nSample rows (first 10):")
cur.execute("""
    SELECT symbol, company_name, sector, listing_date, delisting_date, is_active, in_kse100
    FROM stock_metadata ORDER BY symbol LIMIT 10
""")
for r in cur.fetchall():
    cname = (r[1] or "")[:20]
    print(f"  {r[0]:<10} {cname:<22} {r[4] or r[3] or 'N/A':<12}  active={r[5]}  kse100={r[6]}")

print("\n✅ stock_metadata built successfully.")
print("=" * 60)
con.close()
