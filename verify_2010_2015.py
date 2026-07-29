"""
Step 4 — Cross-Verification Report
Run after scrape_2010_2015.py completes.

Usage:
    python verify_2010_2015.py

Reads:
    psx_historical_2010_2015.db  (staging — read-only)
    psx_data.db                  (main — read-only, for ticker comparison)

Prints PASS / FAIL for each check. Does NOT modify any database.
"""

import sqlite3
from pathlib import Path

PROJECT_DIR = Path(r"C:\Users\Lenovo\psx_pipeline")
STAGING_DB  = PROJECT_DIR / "psx_historical_2010_2015.db"
MAIN_DB     = PROJECT_DIR / "psx_data.db"

PASS = "✅ PASS"
FAIL = "❌ FAIL"

results = {}


def banner(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(label, passed, detail=""):
    status = PASS if passed else FAIL
    results[label] = passed
    msg = f"  {status}  {label}"
    if detail:
        msg += f"\n         {detail}"
    print(msg)
    return passed


# ─────────────────────────────────────────────────────────────────────────────
stg = sqlite3.connect(f"file:{STAGING_DB}?mode=ro", uri=True)
main = sqlite3.connect(f"file:{MAIN_DB}?mode=ro", uri=True)

# ── CHECK 1 — Row counts per year ─────────────────────────────────────────────
banner("CHECK 1 — Row counts per year (prices_staging)")
rows_by_year = stg.execute(
    "SELECT substr(date,1,4) AS yr, COUNT(*) FROM prices_staging GROUP BY yr ORDER BY yr"
).fetchall()
total_price_rows = sum(c for _, c in rows_by_year)

for yr, cnt in rows_by_year:
    print(f"    {yr}  :  {cnt:,} rows")

print(f"\n  Total prices_staging rows : {total_price_rows:,}")

idx_rows = stg.execute("SELECT COUNT(*) FROM index_prices_staging").fetchone()[0]
print(f"  Total index_prices_staging: {idx_rows:,}")

year_years = [yr for yr, _ in rows_by_year]
has_all_years = all(str(y) in year_years for y in range(2010, 2015))
check("All 5 years present in prices_staging", has_all_years,
      f"Years found: {year_years}")
check("prices_staging not empty", total_price_rows > 0,
      f"{total_price_rows:,} rows")
check("index_prices_staging not empty", idx_rows > 0,
      f"{idx_rows:,} rows")


# ── CHECK 2 — Date range ──────────────────────────────────────────────────────
banner("CHECK 2 — Date range")
r = stg.execute("SELECT MIN(date), MAX(date) FROM prices_staging").fetchone()
earliest_p, latest_p = r
print(f"  prices_staging  : {earliest_p} → {latest_p}")

r = stg.execute("SELECT MIN(date), MAX(date) FROM index_prices_staging").fetchone()
earliest_i, latest_i = r
print(f"  index_staging   : {earliest_i} → {latest_i}")

check("prices_staging earliest >= 2010-01-01", earliest_p >= "2010-01-01",
      f"got {earliest_p}")
check("prices_staging latest <= 2014-12-31",   latest_p <= "2014-12-31",
      f"got {latest_p}")


# ── CHECK 3 — Ticker coverage ─────────────────────────────────────────────────
banner("CHECK 3 — Ticker coverage")

stg_symbols  = {r[0] for r in stg.execute("SELECT DISTINCT symbol FROM prices_staging").fetchall()}
main_symbols = {r[0] for r in main.execute("SELECT DISTINCT symbol FROM prices").fetchall()}

# Tickers in main but entirely absent from staging
missing_from_stg = main_symbols - stg_symbols
print(f"  Staging symbols : {len(stg_symbols):,}")
print(f"  Main symbols    : {len(main_symbols):,}")
print(f"  In main but NOT in staging: {len(missing_from_stg):,}  (expected — post-2014 listings)")

if len(missing_from_stg) <= 30:
    print(f"  Missing         : {sorted(missing_from_stg)}")
else:
    sample = sorted(missing_from_stg)[:30]
    print(f"  Missing (sample): {sample}  ... and {len(missing_from_stg)-30} more")

# Tickers with < 100 trading days in staging
sparse = stg.execute(
    "SELECT symbol, COUNT(*) AS days FROM prices_staging "
    "GROUP BY symbol HAVING days < 100 ORDER BY days"
).fetchall()
print(f"\n  Symbols with < 100 trading days in staging: {len(sparse)}")
if sparse:
    for sym, days in sparse[:20]:
        print(f"    {sym}: {days} days")
    if len(sparse) > 20:
        print(f"    ... and {len(sparse)-20} more")

check("Staging has at least 50 symbols", len(stg_symbols) >= 50,
      f"{len(stg_symbols)} symbols")


# ── CHECK 4 — Duplicate check ─────────────────────────────────────────────────
banner("CHECK 4 — Duplicate (symbol, date) check")

dup_p = stg.execute(
    "SELECT COUNT(*) FROM ("
    "  SELECT symbol, date, COUNT(*) AS n FROM prices_staging "
    "  GROUP BY symbol, date HAVING n > 1"
    ")"
).fetchone()[0]

dup_i = stg.execute(
    "SELECT COUNT(*) FROM ("
    "  SELECT symbol, date, COUNT(*) AS n FROM index_prices_staging "
    "  GROUP BY symbol, date HAVING n > 1"
    ")"
).fetchone()[0]

print(f"  Duplicate pairs in prices_staging       : {dup_p}")
print(f"  Duplicate pairs in index_prices_staging : {dup_i}")
check("Zero duplicates in prices_staging",       dup_p == 0)
check("Zero duplicates in index_prices_staging", dup_i == 0)


# ── CHECK 5 — OHLCV sanity ────────────────────────────────────────────────────
banner("CHECK 5 — OHLCV sanity")

issues = {}

# High < Low
n = stg.execute("SELECT COUNT(*) FROM prices_staging WHERE high < low").fetchone()[0]
issues["high < low"] = n

# Close > High
n = stg.execute("SELECT COUNT(*) FROM prices_staging WHERE close > high").fetchone()[0]
issues["close > high"] = n

# Close < Low
n = stg.execute("SELECT COUNT(*) FROM prices_staging WHERE close < low").fetchone()[0]
issues["close < low"] = n

# Open out of range (open is always NULL so skip this check — consistent with main DB)
# Volume = 0 or NULL (prices only — index_prices has no volume column)
n = stg.execute(
    "SELECT COUNT(*) FROM prices_staging WHERE volume = 0 OR volume IS NULL"
).fetchone()[0]
issues["volume 0 or NULL"] = n

# Any price column NULL or zero (close must be present)
n = stg.execute(
    "SELECT COUNT(*) FROM prices_staging WHERE close IS NULL OR close = 0"
).fetchone()[0]
issues["close NULL or 0"] = n

n = stg.execute(
    "SELECT COUNT(*) FROM prices_staging WHERE high IS NULL OR low IS NULL"
).fetchone()[0]
issues["high or low NULL"] = n

all_sane = True
for label, cnt in issues.items():
    ok = cnt == 0
    if not ok:
        all_sane = False
    print(f"  {label:25s}: {cnt:>6,}  {'OK' if ok else '⚠️  REVIEW'}")

check("OHLCV sanity — no critical violations",
      issues["high < low"] == 0 and issues["close > high"] == 0 and issues["close < low"] == 0,
      "high<low / close>high / close<low counts above")


# ── CHECK 6 — Overlap check ───────────────────────────────────────────────────
banner("CHECK 6 — Overlap with main DB (no rows >= 2015-01-01)")

overlap_p = stg.execute(
    "SELECT COUNT(*) FROM prices_staging WHERE date >= '2015-01-01'"
).fetchone()[0]
overlap_i = stg.execute(
    "SELECT COUNT(*) FROM index_prices_staging WHERE date >= '2015-01-01'"
).fetchone()[0]

print(f"  prices_staging rows with date >= 2015-01-01       : {overlap_p}")
print(f"  index_prices_staging rows with date >= 2015-01-01 : {overlap_i}")
check("Zero prices_staging overlap",       overlap_p == 0)
check("Zero index_prices_staging overlap", overlap_i == 0)


# ── Summary ───────────────────────────────────────────────────────────────────
banner("SUMMARY")
passed = sum(1 for v in results.values() if v)
total  = len(results)
print(f"\n  {passed}/{total} checks passed\n")
for label, ok in results.items():
    print(f"  {'✅' if ok else '❌'}  {label}")

stg.close()
main.close()

if passed == total:
    print("\n  All checks PASSED. Safe to approve merge (Step 5).")
else:
    print(f"\n  {total - passed} check(s) FAILED. Review before merge.")
