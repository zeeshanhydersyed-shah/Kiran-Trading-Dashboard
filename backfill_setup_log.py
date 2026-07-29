"""
Backfill setup_log with historical setups from stock_signals.
Processes all 4 setup types per date. Outcome columns left NULL.
Run with --dry-run to test on first month only (2015-01-01 to 2015-01-31).
"""

import os
import sqlite3
import sys
from config import DB_PATH

DRY_RUN_END = "2015-01-31"

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")

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
          AND ss.avg_vol_10d > 500000
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

def _append_setup_log_today_pg() -> int:
    """PG-backed equivalent of append_setup_log_today(). Same 3-step logic
    (insert setups, fill forward returns via compute_forward_returns, label
    outcomes), %s placeholders, ON CONFLICT DO NOTHING instead of INSERT OR
    IGNORE. Assumes setup_log already exists in Supabase with the same
    UNIQUE constraint the SQLite schema uses (migrated once via
    migrate_to_supabase.py) — no DDL run here."""
    import logging
    import psycopg2.extras
    from database_pg import get_conn

    log = logging.getLogger(__name__)
    total_inserted = 0

    try:
        with get_conn() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            cur.execute("SELECT MAX(date) AS d FROM stock_signals")
            target_date = cur.fetchone()["d"]
            if not target_date:
                log.warning("setup_log hook (PG): no data in stock_signals.")
                return 0

            cur.execute("SELECT MAX(setup_date) AS d FROM setup_log")
            already = cur.fetchone()["d"]
            if already and already >= target_date:
                log.info("setup_log already up to date for %s (PG).", target_date)
                return 0

            setup_insert_pg = """
                INSERT INTO setup_log
                    (symbol, setup_date, setup_type, regime,
                     rs_rank, sector_rs_rank, rank_change, rs_score_20,
                     base_tightness, vol_contraction, pivot_distance_pct,
                     bos_flag, sector, outcome_label)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """

            queries_pg = [
                ("BREAKOUT", """
                    SELECT ss.symbol, ss.date, 'BREAKOUT', mr.regime,
                           ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                           ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                           ss.bos_flag, sm.sector, 'BREAKEVEN'
                    FROM stock_signals ss
                    LEFT JOIN market_regime mr ON ss.date = mr.date
                    LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                    WHERE ss.date = %s
                      AND ss.bos_flag = 1
                      AND ss.avg_vol_10d > 500000
                      AND COALESCE((
                          SELECT ss_prev.bos_flag
                          FROM stock_signals ss_prev
                          WHERE ss_prev.symbol = ss.symbol
                            AND ss_prev.date < ss.date
                          ORDER BY ss_prev.date DESC
                          LIMIT 1
                      ), 0) = 0
                """),
                ("PRE_BREAKOUT", """
                    SELECT ss.symbol, ss.date, 'PRE_BREAKOUT', mr.regime,
                           ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                           ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                           ss.bos_flag, sm.sector, 'BREAKEVEN'
                    FROM stock_signals ss
                    LEFT JOIN market_regime mr ON ss.date = mr.date
                    LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                    WHERE ss.date = %s
                      AND ss.pivot_distance_pct BETWEEN 0 AND 3
                      AND ss.base_tightness < 8
                      AND ss.avg_vol_10d > 200000
                """),
                ("RS_LEADER_MARKET", """
                    SELECT ss.symbol, ss.date, 'RS_LEADER_MARKET', mr.regime,
                           ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                           ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                           ss.bos_flag, sm.sector, 'BREAKEVEN'
                    FROM stock_signals ss
                    LEFT JOIN market_regime mr ON ss.date = mr.date
                    LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                    WHERE ss.date = %s
                      AND ss.avg_vol_10d > 200000
                    ORDER BY ss.rs_score_20 DESC
                    LIMIT 20
                """),
                ("RS_LEADER_SECTOR", """
                    SELECT ss.symbol, ss.date, 'RS_LEADER_SECTOR', mr.regime,
                           ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                           ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                           ss.bos_flag, sm.sector, 'BREAKEVEN'
                    FROM stock_signals ss
                    LEFT JOIN market_regime mr ON ss.date = mr.date
                    LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                    WHERE ss.date = %s
                      AND ss.avg_vol_10d > 200000
                      AND ss.sector_rs_rank <= 3
                """),
            ]

            try:
                for setup_type, select_sql in queries_pg:
                    cur.execute(select_sql, (target_date,))
                    rows = [tuple(r.values()) for r in cur.fetchall()]
                    if rows:
                        psycopg2.extras.execute_batch(cur, setup_insert_pg, rows)
                        total_inserted += len(rows)
                log.info("setup_log (PG): %d rows inserted for %s.", total_inserted, target_date)
            except Exception as exc:
                log.warning("setup_log step 1 (insert, PG) failed: %s", exc)

        # Step 2 — forward returns (own connection, branches on _PG_URL internally)
        try:
            from compute_forward_returns import main as cfr_main
            cfr_main()
            log.info("setup_log (PG): forward returns updated.")
        except Exception as exc:
            log.warning("setup_log step 2 (forward returns, PG) failed: %s", exc)

        # Step 3 — label outcomes
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE setup_log
                    SET outcome_label = CASE
                        WHEN fwd_return_10d > 0 THEN 'WINNER'
                        WHEN fwd_return_10d < 0 THEN 'LOSER'
                        ELSE 'BREAKEVEN'
                    END
                    WHERE fwd_return_10d IS NOT NULL
                      AND (outcome_label = 'BREAKEVEN' OR outcome_label IS NULL)
                """)
                log.info("setup_log (PG): %d rows labelled.", cur.rowcount)
        except Exception as exc:
            log.warning("setup_log step 3 (labelling, PG) failed: %s", exc)

    except Exception as exc:
        log.warning("setup_log hook (PG) failed: %s", exc)

    return total_inserted


def append_setup_log_today() -> int:
    """Insert today's setups, fill forward returns, label outcomes."""
    import logging
    log = logging.getLogger(__name__)

    if _PG_URL:
        return _append_setup_log_today_pg()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_inserted = 0

    try:
        # ── STEP 1: Insert today's setups ─────────────────────────────────
        row = cur.execute("SELECT MAX(date) FROM stock_signals").fetchone()
        target_date = row[0] if row else None
        if not target_date:
            log.warning("setup_log hook: no data in stock_signals.")
            return 0

        already = cur.execute(
            "SELECT MAX(setup_date) FROM setup_log"
        ).fetchone()[0]
        if already and already >= target_date:
            log.info("setup_log already up to date for %s.", target_date)
            return 0

        setup_insert = """
            INSERT OR IGNORE INTO setup_log
                (symbol, setup_date, setup_type, regime,
                 rs_rank, sector_rs_rank, rank_change, rs_score_20,
                 base_tightness, vol_contraction, pivot_distance_pct,
                 bos_flag, sector, outcome_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        queries = [
            ("BREAKOUT", """
                SELECT ss.symbol, ss.date, 'BREAKOUT', mr.regime,
                       ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                       ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                       ss.bos_flag, sm.sector, 'BREAKEVEN'
                FROM stock_signals ss
                LEFT JOIN market_regime mr ON ss.date = mr.date
                LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.bos_flag = 1
                  AND ss.avg_vol_10d > 500000
                  AND COALESCE((
                      SELECT ss_prev.bos_flag
                      FROM stock_signals ss_prev
                      WHERE ss_prev.symbol = ss.symbol
                        AND ss_prev.date < ss.date
                      ORDER BY ss_prev.date DESC
                      LIMIT 1
                  ), 0) = 0
            """),
            ("PRE_BREAKOUT", """
                SELECT ss.symbol, ss.date, 'PRE_BREAKOUT', mr.regime,
                       ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                       ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                       ss.bos_flag, sm.sector, 'BREAKEVEN'
                FROM stock_signals ss
                LEFT JOIN market_regime mr ON ss.date = mr.date
                LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.pivot_distance_pct BETWEEN 0 AND 3
                  AND ss.base_tightness < 8
                  AND ss.avg_vol_10d > 200000
            """),
            ("RS_LEADER_MARKET", """
                SELECT ss.symbol, ss.date, 'RS_LEADER_MARKET', mr.regime,
                       ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                       ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                       ss.bos_flag, sm.sector, 'BREAKEVEN'
                FROM stock_signals ss
                LEFT JOIN market_regime mr ON ss.date = mr.date
                LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.avg_vol_10d > 200000
                ORDER BY ss.rs_score_20 DESC
                LIMIT 20
            """),
            ("RS_LEADER_SECTOR", """
                SELECT ss.symbol, ss.date, 'RS_LEADER_SECTOR', mr.regime,
                       ss.rs_rank, ss.sector_rs_rank, ss.rank_change, ss.rs_score_20,
                       ss.base_tightness, ss.vol_contraction, ss.pivot_distance_pct,
                       ss.bos_flag, sm.sector, 'BREAKEVEN'
                FROM stock_signals ss
                LEFT JOIN market_regime mr ON ss.date = mr.date
                LEFT JOIN stock_metadata sm ON ss.symbol = sm.symbol
                WHERE ss.date = ?
                  AND ss.avg_vol_10d > 200000
                  AND ss.sector_rs_rank <= 3
            """),
        ]

        try:
            for setup_type, select_sql in queries:
                rows = cur.execute(select_sql, (target_date,)).fetchall()
                cur.executemany(setup_insert, rows)
                total_inserted += cur.rowcount
            conn.commit()
            log.info("setup_log: %d rows inserted for %s.", total_inserted, target_date)
        except Exception as exc:
            log.warning("setup_log step 1 (insert) failed: %s", exc)

        # ── STEP 2: Fill forward returns ───────────────────────────────────
        try:
            from compute_forward_returns import main as cfr_main
            cfr_main()
            log.info("setup_log: forward returns updated.")
        except Exception as exc:
            log.warning("setup_log step 2 (forward returns) failed: %s", exc)

        # ── STEP 3: Label outcomes ─────────────────────────────────────────
        try:
            cur.execute("""
                UPDATE setup_log
                SET outcome_label = CASE
                    WHEN fwd_return_10d > 0 THEN 'WINNER'
                    WHEN fwd_return_10d < 0 THEN 'LOSER'
                    ELSE 'BREAKEVEN'
                END
                WHERE fwd_return_10d IS NOT NULL
                  AND (outcome_label = 'BREAKEVEN' OR outcome_label IS NULL)
            """)
            labelled = cur.rowcount
            conn.commit()
            log.info("setup_log: %d rows labelled.", labelled)
        except Exception as exc:
            log.warning("setup_log step 3 (labelling) failed: %s", exc)

    finally:
        conn.close()

    return total_inserted


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
