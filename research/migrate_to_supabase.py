"""
One-time migration: copy all data from the local SQLite DB to Supabase (PostgreSQL).

Usage:
    set SUPABASE_DB_URL=postgresql://postgres:[password]@[host]:5432/postgres
    python migrate_to_supabase.py

The script is safe to re-run — every INSERT uses ON CONFLICT DO NOTHING,
so already-migrated rows are silently skipped.

Tables migrated:
    sectors          →  all rows
    prices           →  all rows  (can be large, ~332K rows; batched 5000 at a time)
    index_prices     →  all rows
    trade_setups     →  all rows  (IDs are preserved so existing data stays intact)
"""

import os
import sys
import sqlite3
import psycopg2
import psycopg2.extras

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "psx_data.db")
PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
BATCH = 5_000


def _parse_pg_url(url: str) -> dict:
    """Parse postgresql:// URL into psycopg2 kwargs, handling special chars in password."""
    rest     = url.split("://", 1)[-1]
    at       = rest.rfind("@")
    userinfo = rest[:at]
    hostinfo = rest[at + 1:]
    colon    = userinfo.index(":")
    user     = userinfo[:colon]
    password = userinfo[colon + 1:]
    if "/" in hostinfo:
        host_port, dbname = hostinfo.rsplit("/", 1)
        dbname = dbname.split("?")[0]
    else:
        host_port, dbname = hostinfo, "postgres"
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        port = int(port)
    else:
        host, port = host_port, 5432
    return dict(host=host, port=port, dbname=dbname or "postgres",
                user=user, password=password, sslmode="require")


def main():
    if not PG_URL:
        print("ERROR: Set DATABASE_URL or SUPABASE_DB_URL before running.")
        sys.exit(1)

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite DB not found at {SQLITE_PATH}")
        sys.exit(1)

    sqlite = sqlite3.connect(SQLITE_PATH)
    sqlite.row_factory = sqlite3.Row
    pg = psycopg2.connect(**_parse_pg_url(PG_URL))

    try:
        _ensure_schema(pg)
        _migrate_sectors(sqlite, pg)
        _migrate_prices(sqlite, pg)
        _migrate_index_prices(sqlite, pg)
        _migrate_trade_setups(sqlite, pg)
        pg.commit()
        print("\nMigration complete.")
    except Exception as e:
        pg.rollback()
        print(f"\nMigration FAILED: {e}")
        raise
    finally:
        sqlite.close()
        pg.close()


# ---------------------------------------------------------------------------

def _ensure_schema(pg):
    """Create tables in Supabase if they don't already exist."""
    print("Ensuring schema exists in Supabase…")
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS sectors (
            symbol TEXT NOT NULL,
            sector TEXT NOT NULL,
            PRIMARY KEY (symbol)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS prices (
            symbol  TEXT NOT NULL,
            date    TEXT NOT NULL,
            close   DOUBLE PRECISION NOT NULL,
            volume  BIGINT,
            high    DOUBLE PRECISION,
            low     DOUBLE PRECISION,
            PRIMARY KEY (symbol, date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_prices_date   ON prices (date)",
        "CREATE INDEX IF NOT EXISTS idx_prices_symbol ON prices (symbol)",
        """
        CREATE TABLE IF NOT EXISTS index_prices (
            symbol TEXT NOT NULL,
            date   TEXT NOT NULL,
            high   DOUBLE PRECISION,
            low    DOUBLE PRECISION,
            close  DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (symbol, date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_idx_date ON index_prices (date)",
        """
        CREATE TABLE IF NOT EXISTS trade_setups (
            id               SERIAL PRIMARY KEY,
            created_date     TEXT NOT NULL,
            direction        TEXT NOT NULL,
            symbol           TEXT NOT NULL,
            sector           TEXT NOT NULL,
            sector_momentum  TEXT NOT NULL,
            stock_perf_30d   DOUBLE PRECISION NOT NULL,
            stock_perf_10d   DOUBLE PRECISION NOT NULL,
            latest_close     DOUBLE PRECISION NOT NULL,
            support_level    DOUBLE PRECISION,
            resistance_level DOUBLE PRECISION,
            entry_price      DOUBLE PRECISION NOT NULL,
            stop_loss        DOUBLE PRECISION NOT NULL,
            target_1r        DOUBLE PRECISION NOT NULL,
            target_2r        DOUBLE PRECISION NOT NULL,
            risk_pct         DOUBLE PRECISION NOT NULL,
            atr_pct          DOUBLE PRECISION NOT NULL,
            status           TEXT NOT NULL DEFAULT 'Pending',
            outcome          TEXT,
            notes            TEXT,
            quality_score    INTEGER DEFAULT 0,
            quality_checks   TEXT DEFAULT '{}',
            range_width_pct  DOUBLE PRECISION,
            range_window     INTEGER,
            sector_rank      INTEGER,
            breadth_score    DOUBLE PRECISION,
            source           TEXT DEFAULT 'System',
            actual_exit      DOUBLE PRECISION,
            actual_pl_pkr    DOUBLE PRECISION,
            actual_pl_pct    DOUBLE PRECISION,
            actual_rr        DOUBLE PRECISION,
            holding_days     INTEGER,
            exit_date        TEXT,
            actual_entry     DOUBLE PRECISION
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_setups_symbol ON trade_setups (symbol)",
        "CREATE INDEX IF NOT EXISTS idx_setups_status ON trade_setups (status)",
    ]
    with pg.cursor() as cur:
        for s in stmts:
            cur.execute(s)
    pg.commit()
    print("  Schema OK.")


def _migrate_sectors(sqlite, pg):
    rows = sqlite.execute("SELECT symbol, sector FROM sectors").fetchall()
    print(f"Sectors: {len(rows)} rows…", end=" ")
    with pg.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """INSERT INTO sectors (symbol, sector) VALUES (%s, %s)
               ON CONFLICT (symbol) DO NOTHING""",
            [(r["symbol"], r["sector"]) for r in rows],
            page_size=BATCH,
        )
    print("done.")


def _migrate_prices(sqlite, pg):
    total = sqlite.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    print(f"Prices: {total} rows (batches of {BATCH})…")
    offset = 0
    migrated = 0
    while True:
        rows = sqlite.execute(
            "SELECT symbol, date, high, low, close, volume FROM prices ORDER BY date, symbol LIMIT ? OFFSET ?",
            (BATCH, offset),
        ).fetchall()
        if not rows:
            break
        with pg.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                """INSERT INTO prices (symbol, date, high, low, close, volume)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (symbol, date) DO NOTHING""",
                [(r["symbol"], r["date"], r["high"], r["low"], r["close"], r["volume"]) for r in rows],
                page_size=BATCH,
            )
        offset   += BATCH
        migrated += len(rows)
        pct = migrated / total * 100
        print(f"  {migrated:,} / {total:,}  ({pct:.0f}%)")
    print(f"  Prices done ({migrated:,} rows).")


def _migrate_index_prices(sqlite, pg):
    rows = sqlite.execute("SELECT symbol, date, high, low, close FROM index_prices").fetchall()
    print(f"Index prices: {len(rows)} rows…", end=" ")
    with pg.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """INSERT INTO index_prices (symbol, date, high, low, close)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (symbol, date) DO NOTHING""",
            [(r["symbol"], r["date"], r["high"], r["low"], r["close"]) for r in rows],
            page_size=BATCH,
        )
    print("done.")


def _migrate_trade_setups(sqlite, pg):
    rows = sqlite.execute("SELECT * FROM trade_setups ORDER BY id").fetchall()
    print(f"Trade setups: {len(rows)} rows…", end=" ")

    cols = [
        "id", "created_date", "direction", "symbol", "sector", "sector_momentum",
        "stock_perf_30d", "stock_perf_10d", "latest_close",
        "support_level", "resistance_level",
        "entry_price", "stop_loss", "target_1r", "target_2r",
        "risk_pct", "atr_pct", "status", "outcome", "notes",
        "quality_score", "quality_checks", "range_width_pct", "range_window",
        "sector_rank", "breadth_score", "source",
        "actual_exit", "actual_pl_pkr", "actual_pl_pct", "actual_rr",
        "holding_days", "exit_date", "actual_entry",
    ]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names    = ", ".join(cols)

    def _safe(r, col):
        try:
            return r[col]
        except (IndexError, KeyError):
            return None

    data = [tuple(_safe(r, c) for c in cols) for r in rows]

    with pg.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            f"""INSERT INTO trade_setups ({col_names})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING""",
            data,
            page_size=500,
        )
        # Reset the SERIAL sequence so new inserts start after the max migrated id
        if rows:
            max_id = max(r["id"] for r in rows)
            cur.execute(
                "SELECT setval(pg_get_serial_sequence('trade_setups','id'), %s)",
                (max_id,),
            )
    print("done.")


if __name__ == "__main__":
    main()
