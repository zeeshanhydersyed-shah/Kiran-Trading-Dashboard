"""
migrate_to_supabase.py
PSX SQLite -> Supabase PostgreSQL data migration script.
Safe to re-run (idempotent: skips tables already fully migrated).
DO NOT run without reviewing the migration order and special cases below.
"""

import os
import sys
import csv
import time
import argparse
import logging
from datetime import datetime, date
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import sqlite3

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("migrate_to_supabase.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "psx_data.db")
CSV_BACKUP  = os.path.join(BASE_DIR, "supabase_only_trade_setups_backup.csv")
DOTENV_PATH = os.path.join(BASE_DIR, ".env")

# ── Migration order ────────────────────────────────────────────────────────────
# Largest tables first; sectors is SKIPPED (already migrated and verified).
MIGRATION_ORDER = [
    "prices",
    "prices_adjusted",
    "symbol_active_dates",
    "stock_signals",
    "setup_log",
    "sector_signals",
    "index_prices",
    "market_regime",
    "backtest_setups",
    "sim_portfolio_trades",
    "sim_portfolio_trades_v2",
    "sim_portfolio_trades_v3",
    "portfolio_signals",
    "stm_signals",
    "screened_dates",
    "market_flows",
    "fs_line_items",
    "stock_metadata",
    "stock_market_cap",
    "kse100_constituents",
    "leaders_scan",
    "trade_setups",          # SPECIAL: merged from SQLite + CSV backup
    "recovery_signals",
    "agent_opportunities",
    "agent_chat_log",
    "agent_learning_log",
    "mv_signals",
    "agent_memory",
    # Remaining small tables
    "agent_patterns",
    "agent_reference_breakouts",
    "agent_reports",
    "agent_trader_profile",
    "backtest_setups",       # duplicate guard — skip logic handles it
    "corporate_action_suspects",
    "financial_snapshots",
    "fs_analysis",
    "leaders_top_picks",
    "portfolio_transactions",
    "portfolio_values",
    "prediction_log",
    "sim_portfolio_trades",   # duplicate guard
    "uin_settlement",
    "valuation_findings",
]

# Deduplicate while preserving order
seen = set()
MIGRATION_ORDER = [t for t in MIGRATION_ORDER if not (t in seen or seen.add(t))]

# Tables to skip entirely
SKIP_TABLES = {"sectors"}

BATCH_SIZE = 5_000

# ── Boolean columns per table (SQLite 0/1 -> Python True/False) ────────────────
BOOLEAN_COLS = {
    "agent_patterns":   {"is_active"},
    "mv_signals":       {"market_up"},
    "recovery_signals": {"fresh", "kse_regime_ok"},
    "setup_log":        {"bos_flag"},
    "stock_metadata":   {"is_active"},
    "stock_signals":    {"bos_flag", "stage2_bull", "close_above_ema50",
                         "ema50_slope_pos", "overhead_clear",
                         "close_above_ema150", "ema150_slope_pos"},
}

# ── Connections ────────────────────────────────────────────────────────────────
def get_pg_conn():
    load_dotenv(DOTENV_PATH)
    url = os.getenv("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL not found in .env")
    conn = psycopg2.connect(url, connect_timeout=30)
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '300s'")
        cur.execute("SET work_mem = '64MB'")
    conn.commit()
    return conn

def get_sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Type conversion ────────────────────────────────────────────────────────────
def get_pg_column_info(pg_conn, table_name):
    """Return list of (col_name, data_type) in ordinal order."""
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        return cur.fetchall()

def convert_row(row, col_names, col_types, bool_cols):
    """
    Convert a SQLite row (tuple) to a Postgres-compatible tuple.
    - date string -> Python date
    - timestamp string -> kept as string (psycopg2 handles ISO strings)
    - 0/1 in boolean cols -> True/False
    - '' (empty string) -> None (Postgres NULL)
    """
    result = []
    for val, col_name, col_type in zip(row, col_names, col_types):
        # Empty string -> NULL
        if val == "":
            val = None

        if val is None:
            result.append(None)
            continue

        # Boolean conversion
        if col_name in bool_cols:
            result.append(bool(val))
            continue

        # Date columns
        if col_type == "date":
            if isinstance(val, str):
                try:
                    result.append(date.fromisoformat(val))
                except ValueError:
                    result.append(None)
            else:
                result.append(val)
            continue

        result.append(val)
    return tuple(result)

# ── Core migration function ────────────────────────────────────────────────────
def migrate_table(table_name, pg_conn, sq_conn, summary):
    t_start = time.time()
    log.info(f"{'='*60}")
    log.info(f"TABLE: {table_name}")

    # Column info from Postgres (authoritative schema)
    col_info  = get_pg_column_info(pg_conn, table_name)
    col_names = [c[0] for c in col_info]
    col_types = [c[1] for c in col_info]

    # Skip GENERATED ALWAYS AS IDENTITY columns (id) — Postgres auto-fills them
    # But we DO include them from SQLite to preserve original IDs via OVERRIDING SYSTEM VALUE
    has_identity = False
    with pg_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
              AND identity_generation = 'ALWAYS'
        """, (table_name,))
        identity_cols = {r[0] for r in cur.fetchall()}
    has_identity = bool(identity_cols)

    bool_cols = BOOLEAN_COLS.get(table_name, set())

    # SQLite row count
    sq_cur = sq_conn.cursor()
    sq_cur.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    sqlite_count = sq_cur.fetchone()[0]
    log.info(f"  SQLite rows: {sqlite_count:,}")

    # Postgres row count
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        pg_count = cur.fetchone()[0]
    log.info(f"  Supabase rows: {pg_count:,}")

    # Skip / resume logic
    if pg_count >= sqlite_count and sqlite_count > 0:
        log.info(f"  SKIPPED: already complete ({pg_count:,} >= {sqlite_count:,} rows)")
        summary.append({
            "table": table_name, "source": sqlite_count,
            "migrated": pg_count, "match": "SKIPPED",
            "time": f"{time.time()-t_start:.1f}s"
        })
        return True

    if 0 < pg_count < sqlite_count:
        log.warning(f"  PARTIAL: Supabase has {pg_count:,} of {sqlite_count:,} rows")
        ans = input(f"  [{table_name}] Truncate and restart? (y=truncate, s=skip, Enter=skip): ").strip().lower()
        if ans == "y":
            log.info(f"  Truncating {table_name}...")
            with pg_conn.cursor() as cur:
                cur.execute(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE')
            pg_conn.commit()
            pg_count = 0
        else:
            log.info(f"  SKIPPED: partial migration left in place")
            summary.append({
                "table": table_name, "source": sqlite_count,
                "migrated": pg_count, "match": "PARTIAL-SKIPPED",
                "time": f"{time.time()-t_start:.1f}s"
            })
            return True

    if sqlite_count == 0:
        log.info(f"  Source is empty — nothing to migrate")
        summary.append({
            "table": table_name, "source": 0,
            "migrated": 0, "match": "OK-EMPTY",
            "time": f"{time.time()-t_start:.1f}s"
        })
        return True

    # Build INSERT SQL
    # Use OVERRIDING SYSTEM VALUE to preserve original IDs from SQLite
    col_list   = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(["%s"] * len(col_names))
    if has_identity:
        insert_sql = (
            f'INSERT INTO "{table_name}" ({col_list}) '
            f'OVERRIDING SYSTEM VALUE VALUES %s '
            f'ON CONFLICT DO NOTHING'
        )
    else:
        insert_sql = (
            f'INSERT INTO "{table_name}" ({col_list}) '
            f'VALUES %s '
            f'ON CONFLICT DO NOTHING'
        )

    # Fetch and insert in batches
    sq_cur.execute(f"SELECT {', '.join(col_names)} FROM [{table_name}]")
    migrated = 0

    while True:
        raw_rows = sq_cur.fetchmany(BATCH_SIZE)
        if not raw_rows:
            break
        batch = [convert_row(tuple(r), col_names, col_types, bool_cols) for r in raw_rows]
        with pg_conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, insert_sql, batch, page_size=BATCH_SIZE)
        pg_conn.commit()
        migrated += len(batch)
        pct = migrated / sqlite_count * 100
        elapsed = time.time() - t_start
        rate = migrated / elapsed if elapsed > 0 else 0
        log.info(f"  {table_name}: {migrated:,} / {sqlite_count:,} ({pct:.1f}%) — {rate:.0f} rows/s")

    # Final verification
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        final_count = cur.fetchone()[0]

    elapsed = time.time() - t_start
    if final_count == sqlite_count:
        log.info(f"  VERIFIED: {final_count:,} rows match — {elapsed:.1f}s")
        match = "OK"
    else:
        log.error(f"  MISMATCH: Supabase={final_count:,}, SQLite={sqlite_count:,} — STOPPING")
        summary.append({
            "table": table_name, "source": sqlite_count,
            "migrated": final_count, "match": "MISMATCH-STOP",
            "time": f"{elapsed:.1f}s"
        })
        return False

    summary.append({
        "table": table_name, "source": sqlite_count,
        "migrated": final_count, "match": match,
        "time": f"{elapsed:.1f}s"
    })
    return True

# ── Special: trade_setups MERGE ───────────────────────────────────────────────
def migrate_trade_setups_merged(pg_conn, sq_conn, summary):
    t_start = time.time()
    table_name = "trade_setups"
    log.info(f"{'='*60}")
    log.info(f"TABLE: {table_name} (SPECIAL MERGE)")

    col_info  = get_pg_column_info(pg_conn, table_name)
    col_names = [c[0] for c in col_info]
    col_types = [c[1] for c in col_info]
    bool_cols = BOOLEAN_COLS.get(table_name, set())

    # Check if already done
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        pg_count = cur.fetchone()[0]

    sq_cur = sq_conn.cursor()
    sq_cur.execute(f"SELECT COUNT(*) FROM [{table_name}]")
    sqlite_count = sq_cur.fetchone()[0]

    # Load CSV backup
    csv_rows = []
    if os.path.exists(CSV_BACKUP):
        with open(CSV_BACKUP, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_rows = list(reader)
        log.info(f"  CSV backup loaded: {len(csv_rows)} rows")
    else:
        log.warning(f"  CSV backup NOT found at {CSV_BACKUP} — proceeding with SQLite only")

    # Build set of local (symbol, created_date) keys
    sq_cur.execute("SELECT symbol, created_date FROM trade_setups")
    local_keys = {(r[0], str(r[1])) for r in sq_cur.fetchall()}

    # CSV rows NOT in local SQLite
    csv_only = [r for r in csv_rows if (r["symbol"], str(r["created_date"])) not in local_keys]
    log.info(f"  SQLite rows:    {sqlite_count:,}")
    log.info(f"  CSV total rows: {len(csv_rows)}")
    log.info(f"  CSV-only rows (not in SQLite): {len(csv_only)}")
    expected_total = sqlite_count + len(csv_only)
    log.info(f"  Expected merged total: {expected_total:,}")

    if pg_count >= expected_total and pg_count > 0:
        log.info(f"  SKIPPED: already complete ({pg_count:,} rows in Supabase)")
        summary.append({
            "table": table_name, "source": f"{sqlite_count}+{len(csv_only)}csv",
            "migrated": pg_count, "match": "SKIPPED",
            "time": f"{time.time()-t_start:.1f}s"
        })
        return True

    if pg_count > 0:
        log.warning(f"  PARTIAL: {pg_count:,} rows already in Supabase")
        ans = input("  Truncate and restart trade_setups merge? (y=truncate, s=skip, Enter=skip): ").strip().lower()
        if ans == "y":
            with pg_conn.cursor() as cur:
                cur.execute(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE')
            pg_conn.commit()
            log.info("  Truncated.")
        else:
            log.info("  SKIPPED.")
            summary.append({
                "table": table_name, "source": f"{sqlite_count}+{len(csv_only)}csv",
                "migrated": pg_count, "match": "PARTIAL-SKIPPED",
                "time": f"{time.time()-t_start:.1f}s"
            })
            return True

    col_list     = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(["%s"] * len(col_names))
    insert_sql   = (
        f'INSERT INTO "{table_name}" ({col_list}) '
        f'OVERRIDING SYSTEM VALUE VALUES %s '
        f'ON CONFLICT DO NOTHING'
    )

    # --- Pass 1: local SQLite rows ---
    sq_cur.execute(f"SELECT {', '.join(col_names)} FROM [{table_name}]")
    raw_rows = sq_cur.fetchall()
    batch = [convert_row(tuple(r), col_names, col_types, bool_cols) for r in raw_rows]
    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, insert_sql, batch, page_size=BATCH_SIZE)
    pg_conn.commit()
    log.info(f"  Inserted {len(batch):,} rows from local SQLite")

    # --- Pass 2: CSV-only rows ---
    if csv_only:
        csv_batch = []
        for csv_row in csv_only:
            row_tuple = []
            for col_name, col_type in zip(col_names, col_types):
                raw = csv_row.get(col_name, None)
                # Normalize empty string -> None
                if raw == "" or raw == "None":
                    raw = None
                # Boolean
                if col_name in bool_cols and raw is not None:
                    raw = bool(int(raw))
                # Date
                elif col_type == "date" and raw is not None:
                    try:
                        raw = date.fromisoformat(str(raw))
                    except ValueError:
                        raw = None
                # Numeric
                elif col_type in ("numeric", "double precision") and raw is not None:
                    try:
                        raw = float(raw)
                    except (ValueError, TypeError):
                        raw = None
                elif col_type in ("integer", "bigint") and raw is not None:
                    try:
                        raw = int(raw)
                    except (ValueError, TypeError):
                        raw = None
                row_tuple.append(raw)
            csv_batch.append(tuple(row_tuple))

        with pg_conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, insert_sql, csv_batch, page_size=BATCH_SIZE)
        pg_conn.commit()
        log.info(f"  Inserted {len(csv_batch):,} rows from CSV backup")

    # Verify
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        final_count = cur.fetchone()[0]

    elapsed = time.time() - t_start
    if final_count == expected_total:
        log.info(f"  VERIFIED: {final_count:,} rows (SQLite {sqlite_count} + CSV {len(csv_only)}) — {elapsed:.1f}s")
        match = "OK-MERGED"
    else:
        log.error(f"  MISMATCH: got {final_count:,}, expected {expected_total:,}")
        match = "MISMATCH"

    summary.append({
        "table": table_name,
        "source": f"{sqlite_count}+{len(csv_only)}csv={expected_total}",
        "migrated": final_count,
        "match": match,
        "time": f"{elapsed:.1f}s"
    })
    return match in ("OK-MERGED",)

# ── Main ───────────────────────────────────────────────────────────────────────
def main(only_table=None):
    overall_start = time.time()
    log.info("PSX -> Supabase Migration Starting")
    log.info(f"SQLite source: {SQLITE_PATH}")
    if only_table:
        log.info(f"MODE: single-table test — {only_table}")
    log.info(f"Tables to migrate: {len(MIGRATION_ORDER)}")
    log.info(f"Batch size: {BATCH_SIZE:,}")

    pg_conn = get_pg_conn()
    sq_conn = get_sqlite_conn()

    summary = []
    success = True

    run_order = [only_table] if only_table else MIGRATION_ORDER

    for table_name in run_order:
        if table_name in SKIP_TABLES:
            log.info(f"SKIP (explicitly excluded): {table_name}")
            continue

        if table_name == "trade_setups":
            ok = migrate_trade_setups_merged(pg_conn, sq_conn, summary)
        else:
            ok = migrate_table(table_name, pg_conn, sq_conn, summary)

        if not ok:
            log.error(f"Migration STOPPED after failure in {table_name}")
            success = False
            break

    # Reset identity sequences for tables that used OVERRIDING SYSTEM VALUE
    log.info(f"\n{'='*60}")
    log.info("Resetting identity sequences...")
    all_sequence_tables = [
        "trade_setups", "backtest_setups", "corporate_action_suspects",
        "mv_signals", "portfolio_signals", "portfolio_transactions",
        "portfolio_values", "recovery_signals", "setup_log",
        "sim_portfolio_trades", "sim_portfolio_trades_v2", "sim_portfolio_trades_v3",
        "stm_signals", "agent_chat_log", "agent_learning_log", "agent_memory",
        "agent_opportunities", "agent_patterns", "agent_reference_breakouts",
        "agent_reports", "agent_trader_profile", "leaders_scan", "leaders_top_picks",
        "market_flows", "prediction_log", "uin_settlement",
    ]
    sequence_tables = [only_table] if only_table else all_sequence_tables
    with pg_conn.cursor() as cur:
        for t in sequence_tables:
            try:
                cur.execute(f"""
                    SELECT setval(
                        pg_get_serial_sequence('"{t}"', 'id'),
                        COALESCE((SELECT MAX(id) FROM "{t}"), 1)
                    )
                """)
                log.info(f"  Sequence reset: {t}")
            except Exception as e:
                log.warning(f"  Sequence reset skipped for {t}: {e}")
                pg_conn.rollback()
    pg_conn.commit()

    # Print summary table
    elapsed_total = time.time() - overall_start
    log.info(f"\n{'='*60}")
    log.info(f"MIGRATION SUMMARY  (total elapsed: {elapsed_total:.1f}s)")
    log.info(f"{'='*60}")
    hdr = f"{'Table':<35} {'Source':>15} {'Migrated':>10} {'Match':<15} {'Time':>8}"
    log.info(hdr)
    log.info("-" * len(hdr))
    for row in summary:
        log.info(
            f"{row['table']:<35} {str(row['source']):>15} "
            f"{str(row['migrated']):>10} {row['match']:<15} {row['time']:>8}"
        )
    log.info(f"\nOverall status: {'SUCCESS' if success else 'STOPPED WITH ERRORS'}")

    pg_conn.close()
    sq_conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PSX SQLite -> Supabase migration")
    parser.add_argument("--table", metavar="TABLE_NAME",
                        help="Migrate only this one table (for testing)")
    args = parser.parse_args()
    main(only_table=args.table)
