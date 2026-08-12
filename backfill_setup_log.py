"""
Backfill setup_log with historical setups from stock_signals.
Processes all 4 setup types per date. Outcome columns left NULL.
Run with --dry-run to test on first month only (2015-01-01 to 2015-01-31).
"""

import logging
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

            cur.execute("SELECT MAX(setup_date) AS d FROM setup_log")
            already = cur.fetchone()["d"]

            # Bounded scan is an optimisation only; _pending_setup_log_dates()
            # holds the policy, shared with the SQLite path above.
            if already:
                cur.execute(
                    "SELECT DISTINCT date AS d FROM stock_signals "
                    "WHERE date >= %s ORDER BY date",
                    (already,),
                )
                signal_dates = [r["d"] for r in cur.fetchall()]
            else:
                cur.execute("SELECT MAX(date) AS d FROM stock_signals")
                row = cur.fetchone()
                signal_dates = [row["d"]] if row and row["d"] else []

            if not signal_dates:
                log.warning("setup_log hook (PG): no data in stock_signals.")
                return 0

            pending = _pending_setup_log_dates(signal_dates, already)
            if not pending:
                log.info("setup_log already up to date for %s (PG).", already)
                return 0
            if len(pending) > 1:
                log.warning(
                    "setup_log (PG): backfilling %d missing date(s), %s -> %s.",
                    len(pending), pending[0], pending[-1],
                )

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
                      -- `bos_flag = 1` (what the SQLite twin of this query
                      -- says) raises `operator does not exist: boolean =
                      -- integer` on Postgres, where the column is BOOLEAN,
                      -- not INTEGER. That error aborts the transaction, so
                      -- all four queries for the date fail and NOTHING is
                      -- written -- which is why production setup_log sat
                      -- frozen at 2026-06-30 for six weeks while
                      -- stock_signals stayed current. Same SQLite/Postgres
                      -- type-mismatch class as the TEXT vs DATE gotcha in
                      -- CLAUDE.md. See docs/KIRAN_CLEANUP_AUDIT.md §25.
                      AND ss.bos_flag IS TRUE
                      AND ss.avg_vol_10d > 500000
                      AND COALESCE((
                          SELECT ss_prev.bos_flag
                          FROM stock_signals ss_prev
                          WHERE ss_prev.symbol = ss.symbol
                            AND ss_prev.date < ss.date
                          ORDER BY ss_prev.date DESC
                          LIMIT 1
                      ), FALSE) IS FALSE
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

            for target_date in pending:
                # Commit per date for the same reason as the SQLite path: a
                # mid-backfill failure keeps the days already written.
                try:
                    day_inserted = 0
                    for setup_type, select_sql in queries_pg:
                        cur.execute(select_sql, (target_date,))
                        rows = [tuple(r.values()) for r in cur.fetchall()]
                        if rows:
                            psycopg2.extras.execute_batch(cur, setup_insert_pg, rows)
                            day_inserted += len(rows)
                    conn.commit()
                    total_inserted += day_inserted
                    log.info("setup_log (PG): %d rows inserted for %s.",
                             day_inserted, target_date)
                except Exception as exc:
                    conn.rollback()
                    log.warning("setup_log step 1 (insert, PG) failed for %s: %s",
                                target_date, exc)

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


# ── Daily setup-detection rules, SQLite ───────────────────────────────────────
# Module-level and shared: append_setup_log_today() (the daily hook) and
# append_setup_log_for_dates() (one-off repair of holes below the high-water
# mark) MUST insert by identical rules, or a repaired date would disagree with
# the days around it. Note these are the DAILY rules -- BREAKOUT on the
# transition day only -- which deliberately differ from run()'s historical
# backfill above (every bos_flag=1 day). See docs/KIRAN_CLEANUP_AUDIT.md §24.
_DAILY_SETUP_INSERT_SQLITE = """
    INSERT OR IGNORE INTO setup_log
        (symbol, setup_date, setup_type, regime,
         rs_rank, sector_rs_rank, rank_change, rs_score_20,
         base_tightness, vol_contraction, pivot_distance_pct,
         bos_flag, sector, outcome_label)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_DAILY_QUERIES_SQLITE = [
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


def _insert_setup_log_for_date(cur, target_date) -> int:
    """Run all four daily setup queries for one date. Does not commit."""
    inserted = 0
    for _setup_type, select_sql in _DAILY_QUERIES_SQLITE:
        rows = cur.execute(select_sql, (target_date,)).fetchall()
        cur.executemany(_DAILY_SETUP_INSERT_SQLITE, rows)
        inserted += cur.rowcount
    return inserted


def _pending_setup_log_dates(signal_dates, last_logged):
    """Which trading dates still need setup_log rows written.

    Pure and DB-free on purpose, so the policy can be unit-tested directly and
    stays identical across the SQLite and Postgres paths -- same shape as
    regime.py's _pending_regime_rows().

    Before 2026-08-12 this logic was `target_date = MAX(stock_signals.date)`
    with no loop, which meant a transient failure on any single day lost that
    day permanently: the next successful run just wrote whatever the newest
    date was and moved on. `stock_signals.py` (which this reads from) has
    always backfilled a date range, so the two drifted apart silently --
    confirmed in the local DB, where stock_signals holds every trading date
    through 2026-08-11 while setup_log stops at 2026-07-31, plus older
    one-day holes at 2026-07-13/20/21/29. Same defect class as the
    market_regime/sector_signals loss (docs/KIRAN_CLEANUP_AUDIT.md §21, §22
    A1/A2, audited under B5).

    Two cases:
      * `last_logged is None` (setup_log empty) -> the newest date only. An
        empty table is NOT a licence to replay all history through here: the
        historical backfill in this same module inserts BREAKOUT on every
        bos_flag=1 day, while this function inserts transition days only
        (prev bos_flag = 0), so replaying history here would write rows that
        disagree with the historical record. Deliberate, not an oversight.
      * otherwise -> every signal date after `last_logged`, oldest first.
    """
    dates = sorted(set(signal_dates))
    if not dates:
        return []
    if last_logged is None:
        return dates[-1:]
    return [d for d in dates if d > last_logged]


def append_setup_log_today() -> int:
    """Insert setups for every pending trading date, fill forward returns,
    label outcomes."""
    import logging
    log = logging.getLogger(__name__)

    if _PG_URL:
        return _append_setup_log_today_pg()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_inserted = 0

    try:
        # ── STEP 1: Insert today's setups ─────────────────────────────────
        already = cur.execute(
            "SELECT MAX(setup_date) FROM setup_log"
        ).fetchone()[0]

        # Bounding the scan by `already` is a pure optimisation -- the policy
        # itself lives in _pending_setup_log_dates(), which re-filters anyway.
        if already:
            signal_dates = [r[0] for r in cur.execute(
                "SELECT DISTINCT date FROM stock_signals WHERE date >= ? ORDER BY date",
                (already,),
            ).fetchall()]
        else:
            signal_dates = [r[0] for r in cur.execute(
                "SELECT MAX(date) FROM stock_signals"
            ).fetchall() if r[0]]

        if not signal_dates:
            log.warning("setup_log hook: no data in stock_signals.")
            return 0

        pending = _pending_setup_log_dates(signal_dates, already)
        if not pending:
            log.info("setup_log already up to date for %s.", already)
            return 0
        if len(pending) > 1:
            log.warning(
                "setup_log: backfilling %d missing date(s), %s -> %s.",
                len(pending), pending[0], pending[-1],
            )


        for target_date in pending:
            # Each date commits on its own, so a failure part-way through a
            # multi-day backfill keeps the days already written rather than
            # rolling the whole catch-up back.
            try:
                day_inserted = _insert_setup_log_for_date(cur, target_date)
                conn.commit()
                total_inserted += day_inserted
                log.info("setup_log: %d rows inserted for %s.", day_inserted, target_date)
            except Exception as exc:
                log.warning("setup_log step 1 (insert) failed for %s: %s", target_date, exc)

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


def append_setup_log_for_dates(dates, dry_run: bool = True) -> int:
    """Repair specific `setup_log` dates, by the DAILY rules.

    `append_setup_log_today()` only ever fills dates *after* setup_log's
    high-water mark, which is correct for the daily hook but cannot reach a
    hole below it. Those holes exist: before the 2026-08-12 backfill fix, a
    day the hook missed was lost the moment a newer date was written (see
    docs/KIRAN_CLEANUP_AUDIT.md §24). This is the deliberate, one-off repair
    path for them.

    Uses `_insert_setup_log_for_date()`, i.e. the exact same four queries the
    daily hook runs, so a repaired date agrees with the days around it rather
    than with run()'s different historical-backfill rules.

    `dry_run=True` by default and reports per date without writing, matching
    this project's standing production-write discipline (dry-run, then back
    up, then execute, then re-verify independently). `INSERT OR IGNORE` plus
    setup_log's UNIQUE(symbol, setup_date, setup_type) makes a real run
    idempotent, so re-running cannot duplicate rows.

    Postgres is deliberately NOT wired up here: repairing production is a
    separate decision that needs explicit sign-off, not a flag on a utility.
    """
    import logging
    log = logging.getLogger(__name__)

    if _PG_URL:
        raise RuntimeError(
            "append_setup_log_for_dates() is SQLite-only by design. Repairing "
            "production Supabase needs explicit sign-off and its own "
            "backup/dry-run/verify pass -- see docs/KIRAN_CLEANUP_AUDIT.md §24.4."
        )

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total = 0
    try:
        for target_date in sorted(set(dates)):
            has_signals = cur.execute(
                "SELECT COUNT(*) FROM stock_signals WHERE date = ?", (target_date,)
            ).fetchone()[0]
            existing = cur.execute(
                "SELECT COUNT(*) FROM setup_log WHERE setup_date = ?", (target_date,)
            ).fetchone()[0]
            if not has_signals:
                log.warning("%s: no stock_signals rows -- skipped.", target_date)
                continue

            if dry_run:
                would = sum(
                    len(cur.execute(sql, (target_date,)).fetchall())
                    for _t, sql in _DAILY_QUERIES_SQLITE
                )
                log.info("%s: DRY RUN -- %d row(s) would be written (%d already present).",
                         target_date, would, existing)
                total += would
                continue

            inserted = _insert_setup_log_for_date(cur, target_date)
            conn.commit()
            total += inserted
            log.info("%s: %d row(s) written (%d present before).",
                     target_date, inserted, existing)
    finally:
        conn.close()

    if dry_run:
        log.warning("DRY RUN -- nothing written. Re-run with dry_run=False to apply.")
    return total


if __name__ == "__main__":
    if "--repair-dates" in sys.argv:
        # python backfill_setup_log.py --repair-dates 2026-07-13,2026-07-20 [--execute]
        idx = sys.argv.index("--repair-dates")
        target_dates = [d.strip() for d in sys.argv[idx + 1].split(",") if d.strip()]
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        append_setup_log_for_dates(target_dates, dry_run="--execute" not in sys.argv)
    else:
        dry_run = "--dry-run" in sys.argv
        run(dry_run=dry_run)
