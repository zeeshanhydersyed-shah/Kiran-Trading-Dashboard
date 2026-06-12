"""
Merge psx_historical_2005_2010.db → psx_data.db

Strategy: ATTACH staging DB and INSERT OR IGNORE directly via SQL.
No row-by-row Python iteration — single bulk INSERT per table.
psx_data.db existing data is never modified (IGNORE on conflict).

Run from project root:
    python merge_2005_2010.py
"""

import sqlite3
from pathlib import Path

PROJECT_DIR = Path(r"C:\Users\Lenovo\psx_pipeline")
MAIN_DB     = PROJECT_DIR / "psx_data.db"
STAGING_DB  = PROJECT_DIR / "psx_historical_2005_2010.db"

def main():
    print("=" * 62)
    print("  MERGE — psx_historical_2005_2010.db → psx_data.db")
    print("=" * 62)

    # ── Pre-merge counts ──────────────────────────────────────────
    print("\n── Pre-merge state ──────────────────────────────────────────")
    conn = sqlite3.connect(MAIN_DB)
    cur  = conn.cursor()

    pre_p  = cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM prices").fetchone()
    pre_ip = cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM index_prices").fetchone()
    print(f"  prices       : {pre_p[0]:>10,} rows  |  {pre_p[1]} → {pre_p[2]}")
    print(f"  index_prices : {pre_ip[0]:>10,} rows  |  {pre_ip[1]} → {pre_ip[2]}")

    # ── Attach staging and INSERT OR IGNORE ───────────────────────
    print("\n── Merging … ────────────────────────────────────────────────")
    cur.execute(f"ATTACH DATABASE ? AS staging", (str(STAGING_DB),))

    # prices: (symbol, date, close, volume, high, low, open)
    cur.execute("""
        INSERT OR IGNORE INTO prices (symbol, date, close, volume, high, low, open)
        SELECT symbol, date, close, volume, high, low, open
        FROM staging.prices_staging
    """)
    prices_inserted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    print(f"  prices       : {prices_inserted:,} rows inserted")

    # index_prices: (symbol, date, high, low, close, open)
    # staging has no open column — insert NULL for open
    cur.execute("""
        INSERT OR IGNORE INTO index_prices (symbol, date, high, low, close, open)
        SELECT symbol, date, high, low, close, NULL
        FROM staging.index_prices_staging
    """)
    index_inserted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    print(f"  index_prices : {index_inserted:,} rows inserted")

    cur.execute("DETACH DATABASE staging")

    # ── Post-merge counts ─────────────────────────────────────────
    print("\n── Post-merge state ─────────────────────────────────────────")
    post_p  = cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM prices").fetchone()
    post_ip = cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM index_prices").fetchone()
    print(f"  prices       : {post_p[0]:>10,} rows  |  {post_p[1]} → {post_p[2]}")
    print(f"  index_prices : {post_ip[0]:>10,} rows  |  {post_ip[1]} → {post_ip[2]}")

    # ── Sanity assertions ─────────────────────────────────────────
    print("\n── Sanity checks ────────────────────────────────────────────")
    expected_p  = pre_p[0]  + prices_inserted
    expected_ip = pre_ip[0] + index_inserted

    p_ok  = post_p[0]  == expected_p
    ip_ok = post_ip[0] == expected_ip
    date_ok = post_p[1] <= "2005-01-03"   # new earliest should be 2005

    print(f"  prices row count   : {'PASS' if p_ok  else 'FAIL ⛔'}  "
          f"(expected {expected_p:,}, got {post_p[0]:,})")
    print(f"  index_prices count : {'PASS' if ip_ok else 'FAIL ⛔'}  "
          f"(expected {expected_ip:,}, got {post_ip[0]:,})")
    print(f"  Earliest date      : {'PASS' if date_ok else 'FAIL ⛔'}  "
          f"({post_p[1]})")

    # ── Duplicate check ───────────────────────────────────────────
    print("\n── Duplicate check ──────────────────────────────────────────")
    dupes = cur.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT symbol, date FROM prices GROUP BY symbol, date HAVING COUNT(*) > 1"
        ")"
    ).fetchone()[0]
    print(f"  prices duplicates  : {dupes}  {'PASS' if dupes == 0 else 'FAIL ⛔'}")

    conn.close()

    print("\n" + "=" * 62)
    if p_ok and ip_ok and date_ok and dupes == 0:
        print("  ✓ Merge successful. Paste this output for confirmation.")
    else:
        print("  ⛔ One or more checks failed. Do not push until resolved.")
    print("=" * 62)


if __name__ == "__main__":
    main()
