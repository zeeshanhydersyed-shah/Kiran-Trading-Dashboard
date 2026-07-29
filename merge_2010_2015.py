"""
Step 5 — Merge staging → psx_data.db
RUN ONLY AFTER explicit approval following verify_2010_2015.py PASS.

Usage:
    python merge_2010_2015.py

Safety:
    - Uses INSERT OR IGNORE — no existing rows are modified
    - Reads row counts before and after for validation report
    - Does NOT touch psx_historical_2015_2020.db
    - Does NOT touch any dashboard / pipeline file
"""

import sqlite3
from pathlib import Path

PROJECT_DIR = Path(r"C:\Users\Lenovo\psx_pipeline")
STAGING_DB  = PROJECT_DIR / "psx_historical_2010_2015.db"
MAIN_DB     = PROJECT_DIR / "psx_data.db"


def get_counts(conn, table):
    r = conn.execute(f"SELECT COUNT(*), MIN(date), MAX(date) FROM {table}").fetchone()
    return r[0], r[1], r[2]


# ── Pre-merge snapshot ────────────────────────────────────────────────────────
print("Connecting to databases...")
main = sqlite3.connect(MAIN_DB)
stg  = sqlite3.connect(f"file:{STAGING_DB}?mode=ro", uri=True)

pre_p_count, pre_p_min, pre_p_max = get_counts(main, "prices")
pre_i_count, pre_i_min, pre_i_max = get_counts(main, "index_prices")

stg_p_count = stg.execute("SELECT COUNT(*) FROM prices_staging").fetchone()[0]
stg_i_count = stg.execute("SELECT COUNT(*) FROM index_prices_staging").fetchone()[0]

print(f"\nPre-merge state:")
print(f"  prices        : {pre_p_count:,} rows  ({pre_p_min} → {pre_p_max})")
print(f"  index_prices  : {pre_i_count:,} rows  ({pre_i_min} → {pre_i_max})")
print(f"\nStaging rows to append:")
print(f"  prices_staging       : {stg_p_count:,}")
print(f"  index_prices_staging : {stg_i_count:,}")

# Attach staging and run INSERT OR IGNORE
print("\nAttaching staging DB and merging...")

main.execute(f"ATTACH DATABASE '{STAGING_DB}' AS stg")

main.execute("""
    INSERT OR IGNORE INTO prices (symbol, date, close, volume, high, low, open)
    SELECT symbol, date, close, volume, high, low, open
    FROM stg.prices_staging
""")
prices_added = main.execute("SELECT changes()").fetchone()[0]

main.execute("""
    INSERT OR IGNORE INTO index_prices (symbol, date, high, low, close)
    SELECT symbol, date, high, low, close
    FROM stg.index_prices_staging
""")
idx_added = main.execute("SELECT changes()").fetchone()[0]

main.commit()

# ── Post-merge validation ─────────────────────────────────────────────────────
post_p_count, post_p_min, post_p_max = get_counts(main, "prices")
post_i_count, post_i_min, post_i_max = get_counts(main, "index_prices")

dup_p = main.execute(
    "SELECT COUNT(*) FROM ("
    "  SELECT symbol, date FROM prices GROUP BY symbol, date HAVING COUNT(*) > 1"
    ")"
).fetchone()[0]

dup_i = main.execute(
    "SELECT COUNT(*) FROM ("
    "  SELECT symbol, date FROM index_prices GROUP BY symbol, date HAVING COUNT(*) > 1"
    ")"
).fetchone()[0]

print("\n" + "="*60)
print("  STEP 6 — POST-MERGE VALIDATION")
print("="*60)
print(f"  1. prices total rows       : {post_p_count:,}")
print(f"  2. index_prices total rows : {post_i_count:,}")
print(f"  3. prices earliest date    : {post_p_min}")
print(f"  4. index_prices earliest   : {post_i_min}")
print(f"  5. Rows added to prices    : {prices_added:,}")
print(f"  6. Rows added to index_p   : {idx_added:,}")
print(f"  7. Duplicate (sym,date) in prices       : {dup_p}  {'✅' if dup_p == 0 else '❌ PROBLEM'}")
print(f"     Duplicate (sym,date) in index_prices : {dup_i}  {'✅' if dup_i == 0 else '❌ PROBLEM'}")

print(f"\n  prices range   : {post_p_min} → {post_p_max}")
print(f"  index range    : {post_i_min} → {post_i_max}")

main.execute("DETACH DATABASE stg")
main.close()
stg.close()

if dup_p == 0 and dup_i == 0:
    print("\n✅ Merge complete. No duplicates. Database is clean.")
else:
    print("\n❌ Duplicates detected — investigate before using the database.")
