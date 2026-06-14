"""
Backfill setup_log with historical setups from stock_signals.
Processes all 4 setup types per date. Outcome columns left NULL.
Run with --dry-run to test on first month only (2015-01-01 to 2015-01-31).
"""

import sqlite3
import sys
from config import DB_PATH

DRY_RUN_END = "2015-01-31"

INSERT_SQL = """
INSERT OR IGNORE INTO setup_log (
    symbol, setup_date, setup_type, regime,
    rs_rank, sector_rs_rank, rank_change, rs_score_20,
    base_tightness, vol_contraction, pivot_distance_pct,
    bos_flag, sector
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

def fetch_pre_breakout(cur, date):
    cur.execute("""
        SELECT ss.symbol, ss.date, 'PRE_BREAKOUT', mr.regime,
               ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
               ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
               ss.bos_flag, sm.sector
        FROM stock_signals ss
        LEFT JOIN market_regime mr ON mr.date = ss.date
        LEFT JOIN stock_metadata sm ON sm.symbol = ss.symbol
        WHERE ss.date = ?
          AND ss.pivot_distance_pct BETWEEN 0 AND 3
          AND ss.base_tightness < 8
          AND ss.avg_vol_10d > 200000
    """, (date,))
    return cur.fetchall()

def fetch_rs_leader_market(cur, date):
    cur.execute("""
        SELECT ss.symbol, ss.date, 'RS_LEADER_MARKET', mr.regime,
               ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
               ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
               ss.bos_flag, sm.sector
        FROM stock_signals ss
        LEFT JOIN market_regime mr ON mr.date = ss.date
        LEFT JOIN stock_metadata sm ON sm.symbol = ss.symbol
        WHERE ss.date = ?
          AND ss.avg_vol_10d > 200000
        ORDER BY ss.rs_score_20 DESC
        LIMIT 20
    """, (date,))
    return cur.fetchall()

def fetch_rs_leader_sector(cur, date):
    cur.execute("""
        SELECT ss.symbol, ss.date, 'RS_LEADER_SECTOR', mr.regime,
               ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
               ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
               ss.bos_flag, sm.sector
        FROM stock_signals ss
        LEFT JOIN market_regime mr ON mr.date = ss.date
        LEFT JOIN stock_metadata sm ON sm.symbol = ss.symbol
        WHERE ss.date = ?
          AND ss.avg_vol_10d > 200000
          AND ss.sector_rs_rank <= 3
    """, (date,))
    return cur.fetchall()

def fetch_breakout(cur, date):
    cur.execute("""
        SELECT ss.symbol, ss.date, 'BREAKOUT', mr.regime,
               ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
               ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
               ss.bos_flag, sm.sector
        FROM stock_signals ss
        LEFT JOIN market_regime mr ON mr.date = ss.date
        LEFT JOIN stock_metadata sm ON sm.symbol = ss.symbol
        WHERE ss.date = ?
          AND ss.bos_flag = 1
          AND ss.avg_vol_10d > 200000
    """, (date,))
    return cur.fetchall()

def run(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Fetch all dates from stock_signals in ascending order
    if dry_run:
        cur.execute(
            "SELECT DISTINCT date FROM stock_signals WHERE date <= ? ORDER BY date",
            (DRY_RUN_END,)
        )
        print(f"DRY RUN: processing dates up to {DRY_RUN_END}")
    else:
        cur.execute("SELECT DISTINCT date FROM stock_signals ORDER BY date")

    dates = [r[0] for r in cur.fetchall()]
    total_dates = len(dates)
    print(f"Total dates to process: {total_dates}")

    total_inserted = 0
    type_counts = {"PRE_BREAKOUT": 0, "RS_LEADER_MARKET": 0, "RS_LEADER_SECTOR": 0, "BREAKOUT": 0}

    for i, date in enumerate(dates, 1):
        rows_pre = fetch_pre_breakout(cur, date)
        rows_mkt = fetch_rs_leader_market(cur, date)
        rows_sec = fetch_rs_leader_sector(cur, date)
        rows_bos = fetch_breakout(cur, date)

        conn.executemany(INSERT_SQL, rows_pre)
        conn.executemany(INSERT_SQL, rows_mkt)
        conn.executemany(INSERT_SQL, rows_sec)
        conn.executemany(INSERT_SQL, rows_bos)
        conn.commit()

        type_counts["PRE_BREAKOUT"] += len(rows_pre)
        type_counts["RS_LEADER_MARKET"] += len(rows_mkt)
        type_counts["RS_LEADER_SECTOR"] += len(rows_sec)
        type_counts["BREAKOUT"] += len(rows_bos)
        total_inserted += len(rows_pre) + len(rows_mkt) + len(rows_sec) + len(rows_bos)

        if i % 500 == 0:
            print(f"  Processed {i}/{total_dates} dates — {total_inserted} rows so far")

    conn.close()

    print("\n=== SUMMARY ===")
    for k, v in type_counts.items():
        print(f"  {k}: {v} rows")
    print(f"  TOTAL inserted: {total_inserted}")

    if dry_run:
        # Print 3 sample rows
        conn2 = sqlite3.connect(DB_PATH)
        cur2 = conn2.cursor()
        cur2.execute("SELECT symbol, setup_date, setup_type, regime, rs_score_20, sector FROM setup_log LIMIT 3")
        rows = cur2.fetchall()
        conn2.close()
        print("\n=== SAMPLE ROWS ===")
        for r in rows:
            print(r)

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
