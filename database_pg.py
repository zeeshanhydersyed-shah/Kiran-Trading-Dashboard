"""
PostgreSQL storage layer for PSX sector/price data.
Mirrors database.py exactly — same function signatures, same return types.
Used automatically when the DATABASE_URL environment variable is set.
"""

import json
import logging
import os
from contextlib import contextmanager

# psycopg2 imported lazily inside _connect() to avoid segfaults on startup
# if the binary wheel is incompatible with the current Python version.
logger = logging.getLogger(__name__)

# Read lazily inside _connect() so hot-reloads and late env-var injection both work
def _get_url() -> str:
    return os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or ""


def _parse_pg_url(url: str) -> dict:
    """
    Parse a postgresql:// URL into psycopg2.connect keyword args.

    Standard urlparse breaks when the password contains special characters
    like ?, #, $, + (common in auto-generated Supabase passwords).
    We parse manually so those characters are passed through unchanged.
    """
    # Strip scheme
    rest = url.split("://", 1)[-1]

    # Split on the LAST @ so an @ inside the password still works
    at = rest.rfind("@")
    userinfo = rest[:at]
    hostinfo = rest[at + 1:]

    # user : password  (split on first colon only)
    colon = userinfo.index(":")
    user     = userinfo[:colon]
    password = userinfo[colon + 1:]

    # host:port / dbname
    if "/" in hostinfo:
        host_port, dbname = hostinfo.rsplit("/", 1)
        dbname = dbname.split("?")[0]   # strip any ?sslmode=... suffix
    else:
        host_port = hostinfo
        dbname = "postgres"

    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 5432

    return dict(
        host=host, port=port,
        dbname=dbname or "postgres",
        user=user, password=password,
        sslmode="require",
    )


def _connect():
    """Connect to PostgreSQL using keyword args (handles special chars in password)."""
    import psycopg2  # lazy import — keeps module-level import clean on Python 3.14+
    return psycopg2.connect(**_parse_pg_url(_get_url()))


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _exec(conn, sql: str, params=None):
    """Execute a single statement."""
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur


def _fetchall(conn, sql: str, params=None) -> list[dict]:
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return [dict(r) for r in cur.fetchall()]


def _fetchone(conn, sql: str, params=None):
    import psycopg2.extras
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def init_db():
    """Create tables if they don't exist (idempotent)."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS sectors (
            symbol  TEXT NOT NULL,
            sector  TEXT NOT NULL,
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
            symbol  TEXT NOT NULL,
            date    TEXT NOT NULL,
            high    DOUBLE PRECISION,
            low     DOUBLE PRECISION,
            close   DOUBLE PRECISION NOT NULL,
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
    with get_conn() as conn:
        for stmt in ddl_statements:
            _exec(conn, stmt)

    # Non-destructive migrations: add columns that older deployments may lack
    migrations = [
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS quality_score   INTEGER DEFAULT 0",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS quality_checks  TEXT DEFAULT '{}'",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS range_width_pct DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS range_window    INTEGER",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS sector_rank     INTEGER",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS breadth_score   DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS source          TEXT DEFAULT 'System'",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS actual_exit     DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS actual_pl_pkr   DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS actual_pl_pct   DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS actual_rr       DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS holding_days    INTEGER",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS exit_date       TEXT",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS actual_entry    DOUBLE PRECISION",
        "ALTER TABLE prices ADD COLUMN IF NOT EXISTS volume BIGINT",
        "ALTER TABLE prices ADD COLUMN IF NOT EXISTS high   DOUBLE PRECISION",
        "ALTER TABLE prices ADD COLUMN IF NOT EXISTS low    DOUBLE PRECISION",
    ]
    with get_conn() as conn:
        for sql in migrations:
            try:
                _exec(conn, sql)
            except Exception:
                pass

    logger.info("PostgreSQL database initialised.")


# ---------------------------------------------------------------------------
# Sectors
# ---------------------------------------------------------------------------

def upsert_sectors(rows: list[tuple[str, str]]):
    sql = """
        INSERT INTO sectors (symbol, sector) VALUES (%s, %s)
        ON CONFLICT (symbol) DO UPDATE SET sector = EXCLUDED.sector
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    logger.debug("Upserted %d sector rows", len(rows))


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def upsert_prices(rows: list[tuple]):
    normalised = []
    for r in rows:
        if len(r) >= 6:
            sym, dt, high, low, close, vol = r[0], r[1], r[2], r[3], r[4], r[5]
        elif len(r) == 4:
            sym, dt, close, vol = r[0], r[1], r[2], r[3]
            high, low = None, None
        else:
            sym, dt, close = r[0], r[1], r[2]
            high, low, vol = None, None, None
        normalised.append((sym, dt, high, low, close, vol))

    sql = """
        INSERT INTO prices (symbol, date, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date) DO UPDATE
            SET high   = COALESCE(EXCLUDED.high,   prices.high),
                low    = COALESCE(EXCLUDED.low,    prices.low),
                volume = COALESCE(EXCLUDED.volume, prices.volume)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, normalised)
    logger.debug("Upserted %d price rows", len(rows))


def upsert_index_prices(rows: list[tuple]):
    sql = """
        INSERT INTO index_prices (symbol, date, high, low, close)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date) DO UPDATE
            SET high = COALESCE(EXCLUDED.high, index_prices.high),
                low  = COALESCE(EXCLUDED.low,  index_prices.low)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    logger.debug("Upserted %d index price rows", len(rows))


def get_index_prices(symbol: str = "KSE-100") -> list[dict]:
    with get_conn() as conn:
        return _fetchall(
            conn,
            "SELECT date, high, low, close FROM index_prices WHERE symbol = %s ORDER BY date",
            (symbol,),
        )


def get_all_symbols() -> list[str]:
    with get_conn() as conn:
        rows = _fetchall(conn, "SELECT symbol FROM sectors ORDER BY symbol")
    return [r["symbol"] for r in rows]


def get_all_sectors_df():
    with get_conn() as conn:
        return _fetchall(
            conn,
            "SELECT symbol, sector FROM sectors ORDER BY sector, symbol",
        )


def get_prices_df(symbol: str, limit: int = 60) -> list[dict]:
    with get_conn() as conn:
        return _fetchall(
            conn,
            "SELECT date, close FROM prices WHERE symbol = %s ORDER BY date DESC LIMIT %s",
            (symbol, limit),
        )


def get_latest_scraped_date() -> str | None:
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date) AS d FROM prices")
    return row["d"] if row else None


def get_price_date_range() -> tuple[str | None, str | None]:
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MIN(date) AS mn, MAX(date) AS mx FROM prices")
    return (row["mn"], row["mx"]) if row else (None, None)


def get_sector_price_data() -> list[dict]:
    sql = """
        SELECT s.symbol, s.sector, p.date,
               COALESCE(p.high, p.close) AS high,
               COALESCE(p.low,  p.close) AS low,
               p.close,
               COALESCE(p.volume, 0)     AS volume
        FROM sectors s
        JOIN prices  p ON p.symbol = s.symbol
        ORDER BY s.symbol, p.date
    """
    with get_conn() as conn:
        return _fetchall(conn, sql)


def get_prices_for_breadth() -> list[dict]:
    """Return all symbol/date/close rows for Weinstein breadth computation."""
    with get_conn() as conn:
        return _fetchall(conn, "SELECT symbol, date, close FROM prices ORDER BY symbol, date")


def count_prices() -> int:
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT COUNT(*) AS n FROM prices")
    return row["n"] if row else 0


def count_sectors() -> int:
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT COUNT(*) AS n FROM sectors")
    return row["n"] if row else 0


# ---------------------------------------------------------------------------
# Trade setups
# ---------------------------------------------------------------------------

def save_trade_setup(s: dict) -> int:
    sql = """
        INSERT INTO trade_setups (
            created_date, direction, symbol, sector, sector_momentum,
            stock_perf_30d, stock_perf_10d, latest_close,
            support_level, resistance_level,
            entry_price, stop_loss, target_1r, target_2r,
            risk_pct, atr_pct, status, notes,
            quality_score, quality_checks,
            range_width_pct, range_window, sector_rank, breadth_score,
            source
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                s["created_date"], s["direction"], s["symbol"], s["sector"],
                s.get("sector_momentum", "—"),
                s.get("stock_perf_30d", 0.0), s.get("stock_perf_10d", 0.0),
                s.get("latest_close", 0.0),
                s.get("support_level"), s.get("resistance_level"),
                s["entry_price"], s["stop_loss"],
                s.get("target_1r", 0.0), s.get("target_2r", 0.0),
                s.get("risk_pct", 0.0), s.get("atr_pct", 0.0),
                "Pending", s.get("notes", ""),
                s.get("quality_score", 0),
                json.dumps(s.get("quality_checks", {})),
                s.get("range_width_pct"), s.get("range_window"),
                s.get("sector_rank"), s.get("breadth_score"),
                s.get("source", "System"),
            ))
            return cur.fetchone()[0]


def get_trade_setups(status: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if status:
            return _fetchall(
                conn,
                "SELECT * FROM trade_setups WHERE status=%s ORDER BY created_date DESC",
                (status,),
            )
        return _fetchall(conn, "SELECT * FROM trade_setups ORDER BY created_date DESC")


def update_trade_setup(setup_id: int, status: str, outcome: str | None = None, notes: str | None = None):
    with get_conn() as conn:
        _exec(conn, """
            UPDATE trade_setups
            SET status  = %s,
                outcome = COALESCE(%s, outcome),
                notes   = COALESCE(%s, notes)
            WHERE id = %s
        """, (status, outcome, notes, setup_id))


def activate_trade_setup(
    setup_id: int,
    actual_entry: float | None = None,
    notes: str | None = None,
):
    with get_conn() as conn:
        _exec(conn, """
            UPDATE trade_setups
            SET status       = 'Active',
                actual_entry = COALESCE(%s, actual_entry),
                notes        = COALESCE(%s, notes)
            WHERE id = %s
        """, (actual_entry, notes, setup_id))


def close_trade_setup(
    setup_id: int,
    exit_price: float,
    exit_date: str,
    status: str,
    outcome: str,
    notes: str | None = None,
):
    with get_conn() as conn:
        row = _fetchone(
            conn,
            "SELECT entry_price, actual_entry, direction, created_date FROM trade_setups WHERE id = %s",
            (setup_id,),
        )
        if row is None:
            return

        entry     = float(row["actual_entry"] or row["entry_price"])
        direction = row["direction"]
        open_date = row["created_date"]

        if entry > 0:
            if direction == "LONG":
                pl_pct = (exit_price - entry) / entry * 100
                pl_pkr = exit_price - entry
            else:
                pl_pct = (entry - exit_price) / entry * 100
                pl_pkr = entry - exit_price
        else:
            pl_pct = 0.0
            pl_pkr = 0.0

        try:
            from datetime import date as _date
            d0   = _date.fromisoformat(open_date[:10])
            d1   = _date.fromisoformat(exit_date[:10])
            hold = (d1 - d0).days
        except Exception:
            hold = None

        _exec(conn, """
            UPDATE trade_setups
            SET actual_exit   = %s,
                exit_date     = %s,
                actual_pl_pct = %s,
                actual_pl_pkr = %s,
                holding_days  = %s,
                status        = %s,
                outcome       = %s,
                notes         = COALESCE(%s, notes)
            WHERE id = %s
        """, (exit_price, exit_date, round(pl_pct, 2), round(pl_pkr, 2), hold,
              status, outcome, notes, setup_id))


def delete_trade_setup(setup_id: int):
    with get_conn() as conn:
        _exec(conn, "DELETE FROM trade_setups WHERE id = %s", (setup_id,))


def setup_already_saved(symbol: str, direction: str, created_date: str) -> bool:
    with get_conn() as conn:
        row = _fetchone(
            conn,
            "SELECT 1 FROM trade_setups WHERE symbol=%s AND direction=%s AND created_date=%s LIMIT 1",
            (symbol, direction, created_date),
        )
    return row is not None


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

def get_backtest_summary() -> list[dict]:
    try:
        with get_conn() as conn:
            return _fetchall(conn, "SELECT * FROM backtest_setups ORDER BY as_of_date")
    except Exception:
        return []


def auto_save_setups(setups: list[dict]) -> int:
    saved = 0
    for s in setups:
        if not setup_already_saved(s["symbol"], s["direction"], s["created_date"]):
            s_with_source = dict(s, source="System")
            save_trade_setup(s_with_source)
            saved += 1
    if saved:
        logger.info("Auto-saved %d new system setup(s).", saved)
    return saved
