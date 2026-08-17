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
    We parse manually and URL-decode each field so percent-encoded characters
    (e.g. %3F → ?) are passed to psycopg2 as their literal values.
    """
    from urllib.parse import unquote

    # Strip scheme
    rest = url.split("://", 1)[-1]

    # Split on the LAST @ so an @ inside the password still works
    at = rest.rfind("@")
    userinfo = rest[:at]
    hostinfo = rest[at + 1:]

    # user : password  (split on first colon only)
    colon = userinfo.index(":")
    user     = unquote(userinfo[:colon])
    password = unquote(userinfo[colon + 1:])

    # host:port / dbname
    if "/" in hostinfo:
        host_port, dbname = hostinfo.rsplit("/", 1)
        dbname = unquote(dbname.split("?")[0])  # strip any ?sslmode=... suffix
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
        """
        CREATE TABLE IF NOT EXISTS portfolio_transactions (
            id         SERIAL PRIMARY KEY,
            date       TEXT NOT NULL,
            type       TEXT NOT NULL,
            amount     DOUBLE PRECISION NOT NULL,
            notes      TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_portfolio_tx_date ON portfolio_transactions (date)",
        """
        CREATE TABLE IF NOT EXISTS portfolio_values (
            id         SERIAL PRIMARY KEY,
            date       TEXT NOT NULL UNIQUE,
            value      DOUBLE PRECISION NOT NULL,
            notes      TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_portfolio_val_date ON portfolio_values (date)",
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
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS trade_source    TEXT DEFAULT 'System'",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS reason_notes    TEXT",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS quantity        DOUBLE PRECISION",
        "ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS trade_execution TEXT DEFAULT 'Paper'",
        "ALTER TABLE prices ADD COLUMN IF NOT EXISTS volume BIGINT",
        "ALTER TABLE prices ADD COLUMN IF NOT EXISTS high   DOUBLE PRECISION",
        "ALTER TABLE prices ADD COLUMN IF NOT EXISTS low    DOUBLE PRECISION",
        # portfolio_values.date was declared UNIQUE in the CREATE TABLE above, but
        # CREATE TABLE IF NOT EXISTS never retrofits constraints onto a table that
        # already existed pre-UNIQUE — add_portfolio_value()'s ON CONFLICT (date)
        # silently fails on any such deployment without this. DO block (not plain
        # ALTER) so a rerun after the constraint already exists doesn't error and
        # abort the rest of this migrations loop.
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'portfolio_values_date_key'
            ) THEN
                ALTER TABLE portfolio_values ADD CONSTRAINT portfolio_values_date_key UNIQUE (date);
            END IF;
        END $$;
        """,
    ]
    with get_conn() as conn:
        for sql in migrations:
            try:
                _exec(conn, sql)
            except Exception:
                pass

    # Data migrations (safe to run multiple times)
    data_migrations = [
        "UPDATE trade_setups SET status='Closed' WHERE status IN ('Hit Target', 'Hit SL')",
        "UPDATE trade_setups SET outcome='Loss' WHERE outcome='LOSS'",
        "UPDATE trade_setups SET outcome='Win' WHERE outcome IN ('WIN', 'win')",
        "UPDATE trade_setups SET outcome='Breakeven' WHERE outcome IN ('BREAKEVEN', 'breakeven', 'BE')",
    ]
    with get_conn() as conn:
        for sql in data_migrations:
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
        if len(r) >= 7:
            sym, dt, high, low, close, vol, open_ = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        elif len(r) == 6:
            sym, dt, high, low, close, vol = r[0], r[1], r[2], r[3], r[4], r[5]
            open_ = None
        elif len(r) == 4:
            sym, dt, close, vol = r[0], r[1], r[2], r[3]
            high, low, open_ = None, None, None
        else:
            sym, dt, close = r[0], r[1], r[2]
            high, low, vol, open_ = None, None, None, None
        normalised.append((sym, dt, high, low, close, vol, open_))

    # close is only overwritable for a symbol's most recent date on record --
    # once a newer date exists for that symbol, older dates' close become
    # permanently frozen. Preserves the original "close is settled" protection
    # for historical data while allowing a same-day re-run to correct a close
    # caught before the source fully finalized (see 2026-07-08 KSE-100
    # incident: a 14:53 PKT scrape landed a stale index close, and the old
    # unconditional freeze meant no later run that day could fix it).
    sql = """
        INSERT INTO prices (symbol, date, high, low, close, volume, open)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date) DO UPDATE
            SET high   = COALESCE(EXCLUDED.high,   prices.high),
                low    = COALESCE(EXCLUDED.low,    prices.low),
                volume = COALESCE(EXCLUDED.volume, prices.volume),
                open   = COALESCE(EXCLUDED.open,   prices.open),
                close  = CASE
                             WHEN EXCLUDED.date = (SELECT MAX(date) FROM prices WHERE symbol = EXCLUDED.symbol)
                             THEN COALESCE(EXCLUDED.close, prices.close)
                             ELSE prices.close
                         END
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, normalised)
    logger.debug("Upserted %d price rows", len(rows))


def upsert_index_prices(rows: list[tuple]):
    normalised = []
    for r in rows:
        if len(r) >= 6:
            sym, dt, high, low, close, open_ = r[0], r[1], r[2], r[3], r[4], r[5]
        elif len(r) == 5:
            sym, dt, high, low, close = r[0], r[1], r[2], r[3], r[4]
            open_ = None
        else:
            sym, dt, close = r[0], r[1], r[2]
            high, low, open_ = None, None, None
        normalised.append((sym, dt, high, low, close, open_))

    # close is only overwritable for a symbol's most recent date on record --
    # see upsert_prices() above for the full rationale, same mechanism here.
    sql = """
        INSERT INTO index_prices (symbol, date, high, low, close, open)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, date) DO UPDATE
            SET high  = COALESCE(EXCLUDED.high, index_prices.high),
                low   = COALESCE(EXCLUDED.low,  index_prices.low),
                open  = COALESCE(EXCLUDED.open, index_prices.open),
                close = CASE
                            WHEN EXCLUDED.date = (SELECT MAX(date) FROM index_prices WHERE symbol = EXCLUDED.symbol)
                            THEN COALESCE(EXCLUDED.close, index_prices.close)
                            ELSE index_prices.close
                        END
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, normalised)
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
    if not row or row["d"] is None:
        return None
    d = row["d"]
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def get_latest_stock_date() -> str | None:
    """Return the most recent date in the prices (stock) table, or None."""
    return get_latest_scraped_date()


def get_latest_index_date() -> str | None:
    """Return the most recent date in the index_prices table, or None."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date) AS d FROM index_prices")
    if not row or row["d"] is None:
        return None
    d = row["d"]
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def get_price_date_range() -> tuple[str | None, str | None]:
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MIN(date) AS mn, MAX(date) AS mx FROM prices")
    if not row:
        return (None, None)
    def _s(v):
        return v.isoformat() if v is not None and hasattr(v, "isoformat") else (str(v) if v is not None else None)
    return (_s(row["mn"]), _s(row["mx"]))


def get_latest_prices() -> list[tuple]:
    """Return (symbol, date, high, low, close) rows for the most recent stored date."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date) AS d FROM prices")
        if not row or not row["d"]:
            return []
        rows = _fetchall(
            conn,
            "SELECT symbol, date, high, low, close FROM prices WHERE date = %s",
            (row["d"],),
        )
    return [(r["symbol"], r["date"], r["high"], r["low"], r["close"]) for r in rows]


def cleanup_ghost_dates():
    """
    Delete market-wide holiday ghosts: dates where PSX returned the previous
    or next session's data for almost all symbols instead of real trading data.

    Both directions (a date matching its LAG, or matching its LEAD) are
    identified from a single unmutated snapshot of the table -- one read,
    before any DELETE runs -- so that removing one candidate can never blind
    the other direction's reference point. The old version ran two separate
    DELETEs (forward then backward) in the same transaction; when a
    premature same-day scrape stored an earlier real date's data under a
    later fake date (2026-07-10 incident: 07-09 real, 07-10 fake, identical
    H/L/C), the forward DELETE matched 07-09 against its LEAD (07-10) and
    removed the genuinely correct 07-09 first. By the time the backward
    DELETE ran, its LAG reference for 07-10 was already gone (07-09
    deleted), so the actually-fake 07-10 survived uncorrected.

    Matching is inherently symmetric: if date D matches its LEAD (D+1), then
    D+1 also matches its LAG (D) -- same pair, same values, viewed from both
    sides. So any adjacent matching pair is *always* a backward-match and a
    forward-match simultaneously; the two directions cannot, from price data
    alone, distinguish "D is real, D+1 is a stale duplicate of it" from "D is
    a fake preview of D+1's real data" -- both produce identical symptoms.
    Every incident actually observed on this pipeline (this one, the
    KSE-100 index bug, the 585-symbol prices contamination) has been the
    first pattern: a newer date carrying an older date's stale values, never
    the reverse. For a mutually-matching pair, this function deletes the
    NEWER date -- a deliberate policy choice based on that history, not an
    algorithmic derivation from the data. It does NOT protect against the
    theoretical reverse pattern (an earlier date somehow previewing a later
    date's real values); that failure mode has never been observed here and
    is an accepted residual risk, not silently assumed away.

    A one-sided match (a date matching only its LAG or only its LEAD, not
    both -- possible at the edge of a short multi-date ghost run where the
    mutual partner doesn't clear the >=50-symbol / >=90% threshold) is still
    handled per its original direction, since there's no mutual-pair
    ambiguity to resolve in that case.
    """
    sql = """
        WITH windowed AS (
            SELECT symbol, date, high, low, close,
                   LAG(high)  OVER w AS ph, LAG(low)  OVER w AS pl, LAG(close)  OVER w AS pc,
                   LEAD(high) OVER w AS nh, LEAD(low) OVER w AS nl, LEAD(close) OVER w AS nc
            FROM prices
            WINDOW w AS (PARTITION BY symbol ORDER BY date)
        ),
        stats AS (
            SELECT
                date,
                COUNT(*) FILTER (WHERE ph IS NOT NULL) AS lag_total,
                SUM(CASE WHEN high = ph AND low = pl AND close = pc THEN 1 ELSE 0 END)
                    FILTER (WHERE ph IS NOT NULL) AS lag_matches,
                COUNT(*) FILTER (WHERE nh IS NOT NULL) AS lead_total,
                SUM(CASE WHEN high = nh AND low = nl AND close = nc THEN 1 ELSE 0 END)
                    FILTER (WHERE nh IS NOT NULL) AS lead_matches
            FROM windowed
            GROUP BY date
        ),
        flagged AS (
            SELECT date,
                   (lag_total  >= 50 AND lag_matches::float  / NULLIF(lag_total, 0)  >= 0.90) AS is_backward,
                   (lead_total >= 50 AND lead_matches::float / NULLIF(lead_total, 0) >= 0.90) AS is_forward
            FROM stats
        ),
        distinct_dates AS (SELECT DISTINCT date FROM prices),
        adjacency AS (
            SELECT date, LEAD(date) OVER (ORDER BY date) AS next_date FROM distinct_dates
        )
        DELETE FROM prices WHERE date IN (
            SELECT f.date
            FROM flagged f
            LEFT JOIN adjacency a      ON a.date = f.date
            LEFT JOIN flagged   f_next ON f_next.date = a.next_date
            WHERE f.is_backward
               OR (f.is_forward AND NOT COALESCE(f_next.is_backward, false))
        )
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            total_deleted = cur.rowcount or 0
    if total_deleted:
        logger.info("cleanup_ghost_dates: removed %d rows for market-closed dates", total_deleted)
    return total_deleted


def get_sector_price_data() -> list[dict]:
    sql = """
        SELECT s.symbol, s.sector, p.date,
               COALESCE(p.open, p.close)  AS open,
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


def get_sector_price_data_1y() -> list[dict]:
    """Sector x prices, last 365 calendar days.
    Used by History page (load_sector_history)."""
    sql = """
        SELECT s.symbol, s.sector, p.date,
               COALESCE(p.open, p.close)  AS open,
               COALESCE(p.high, p.close)  AS high,
               COALESCE(p.low,  p.close)  AS low,
               p.close,
               COALESCE(p.volume, 0)      AS volume
        FROM sectors s
        JOIN prices p ON p.symbol = s.symbol
        WHERE p.date >= CURRENT_DATE - INTERVAL '365 days'
        ORDER BY s.symbol, p.date
    """
    with get_conn() as conn:
        return _fetchall(conn, sql)


def get_sector_price_data_60d() -> list[dict]:
    """Sector x prices, last 90 calendar days (approx 60 trading days).
    Used by STM screener display."""
    sql = """
        SELECT s.symbol, s.sector, p.date,
               COALESCE(p.open, p.close)  AS open,
               COALESCE(p.high, p.close)  AS high,
               COALESCE(p.low,  p.close)  AS low,
               p.close,
               COALESCE(p.volume, 0)      AS volume
        FROM sectors s
        JOIN prices p ON p.symbol = s.symbol
        WHERE p.date >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY s.symbol, p.date
    """
    with get_conn() as conn:
        return _fetchall(conn, sql)


def get_sector_price_data_300d_active() -> list[dict]:
    """Sector x prices, active symbols only, last 420 calendar days (approx 300 trading days).
    Used by signal_engine.run_recovery_signals()."""
    sql = """
        SELECT s.symbol, s.sector, p.date,
               COALESCE(p.open, p.close)  AS open,
               COALESCE(p.high, p.close)  AS high,
               COALESCE(p.low,  p.close)  AS low,
               p.close,
               COALESCE(p.volume, 0)      AS volume
        FROM sectors s
        JOIN prices p  ON p.symbol  = s.symbol
        JOIN stock_metadata sm ON sm.symbol = s.symbol
        WHERE sm.is_active = TRUE
        AND p.date >= CURRENT_DATE - INTERVAL '420 days'
        ORDER BY s.symbol, p.date
    """
    with get_conn() as conn:
        return _fetchall(conn, sql)


def get_sector_price_data_60d_active() -> list[dict]:
    """Sector x prices, active symbols only, last 90 calendar days (approx 60 trading days).
    Used by signal_engine.run_stm_signals()."""
    sql = """
        SELECT s.symbol, s.sector, p.date,
               COALESCE(p.open, p.close)  AS open,
               COALESCE(p.high, p.close)  AS high,
               COALESCE(p.low,  p.close)  AS low,
               p.close,
               COALESCE(p.volume, 0)      AS volume
        FROM sectors s
        JOIN prices p  ON p.symbol  = s.symbol
        JOIN stock_metadata sm ON sm.symbol = s.symbol
        WHERE sm.is_active = TRUE
        AND p.date >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY s.symbol, p.date
    """
    with get_conn() as conn:
        return _fetchall(conn, sql)


def get_prices_for_breadth() -> list[dict]:
    """Return symbol/date/close rows for Weinstein breadth computation.

    Restricted to stock_metadata's tracked-equity universe -- see the
    SQLite sibling's docstring (database.py) for why: prices also contains
    futures contracts and govt paper, which inflated Long/Short counts by
    ~150/day before this filter, confirmed on this backend too.
    """
    with get_conn() as conn:
        return _fetchall(
            conn,
            """SELECT symbol, date, close FROM prices
               WHERE symbol IN (SELECT symbol FROM stock_metadata)
               ORDER BY symbol, date""",
        )


def get_prices_for_breadth_recent(days: int = 700) -> list[dict]:
    """PG sibling of database.py's get_prices_for_breadth_recent() -- same
    700-day rationale documented there (verified by direct comparison
    against the unfiltered query: 480 days left signal_line/z_histogram
    off by up to 0.034 from insufficient EMA/z-score warmup; 700 days
    converges to ~1e-12, pure float roundoff). Cutoff computed in Python so the
    query text (date >= %s) needs no dialect-specific date arithmetic.
    close is NUMERIC here -- comes back as Decimal via _fetchall's
    RealDictCursor, same as get_prices_for_breadth() above; load_weinstein_
    data() already runs pd.to_numeric() on this column for every caller
    regardless of backend, so this is a safe uniform-column coercion, not
    a Decimal/float64 arithmetic mix. Restricted to stock_metadata's
    tracked-equity universe, same as get_prices_for_breadth() above."""
    from datetime import date as _date, timedelta as _timedelta

    with get_conn() as conn:
        max_date = _fetchone(conn, "SELECT MAX(date) AS d FROM prices")
        max_date = max_date["d"] if max_date else None
        if not max_date:
            return []
        max_date_obj = max_date if isinstance(max_date, _date) else _date.fromisoformat(max_date)
        cutoff = (max_date_obj - _timedelta(days=days)).isoformat()
        return _fetchall(
            conn,
            """SELECT symbol, date, close FROM prices
               WHERE date >= %s AND symbol IN (SELECT symbol FROM stock_metadata)
               ORDER BY symbol, date""",
            (cutoff,),
        )


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

def _get_regime_context(conn, entry_date: str) -> tuple:
    """
    Return (regime_at_entry, days_since_last_transition) for entry_date.

    days_since_last_transition is CAUSAL: it only looks backward from entry_date,
    so it is safe to populate at entry time in a live trading context.

    days_to_nearest_transition is NOT computed here because it requires knowledge
    of future regime transitions and cannot be known at entry time. It must be
    backfilled retrospectively once enough future data has accumulated.

    Returns (None, None) if entry_date is not yet in market_regime.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT regime FROM market_regime WHERE date = %s", (entry_date,))
        row = cur.fetchone()
        if row is None:
            return None, None
        regime_at_entry = row[0]

        # Most recent transition on or before entry_date
        cur.execute(
            """
            SELECT cur.date
            FROM market_regime cur
            JOIN market_regime prev
              ON prev.date = (
                  SELECT MAX(date) FROM market_regime WHERE date < cur.date
              )
            WHERE cur.regime != prev.regime
              AND cur.date <= %s
            ORDER BY cur.date DESC
            LIMIT 1
            """,
            (entry_date,),
        )
        transition = cur.fetchone()

        if transition is None:
            cur.execute(
                "SELECT COUNT(*) FROM market_regime WHERE date <= %s", (entry_date,)
            )
            days_since = cur.fetchone()[0] - 1
        else:
            cur.execute(
                "SELECT COUNT(*) FROM market_regime WHERE date > %s AND date <= %s",
                (transition[0], entry_date),
            )
            days_since = cur.fetchone()[0]

    return regime_at_entry, days_since


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
            source, trade_execution,
            regime_at_entry, days_since_last_transition
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """
    # days_to_nearest_transition requires future data — left NULL at insert time
    # _n(): cast numpy scalars to native Python so psycopg2 can serialize them.
    def _n(v): return v.item() if hasattr(v, "item") else v
    with get_conn() as conn:
        regime_at_entry, days_since = _get_regime_context(conn, s["created_date"])
        with conn.cursor() as cur:
            cur.execute(sql, (
                s["created_date"], s["direction"], s["symbol"], s["sector"],
                s.get("sector_momentum", "—"),
                _n(s.get("stock_perf_30d", 0.0)), _n(s.get("stock_perf_10d", 0.0)),
                _n(s.get("latest_close", 0.0)),
                _n(s.get("support_level")), _n(s.get("resistance_level")),
                _n(s["entry_price"]), _n(s["stop_loss"]),
                _n(s.get("target_1r", 0.0)), _n(s.get("target_2r", 0.0)),
                _n(s.get("risk_pct", 0.0)), _n(s.get("atr_pct", 0.0)),
                s.get("status", "Pending"), s.get("notes", ""),
                _n(s.get("quality_score", 0)),
                json.dumps(s.get("quality_checks", {}), default=str),
                _n(s.get("range_width_pct")), _n(s.get("range_window")),
                _n(s.get("sector_rank")), _n(s.get("breadth_score")),
                s.get("source", "System"),
                s.get("trade_execution", "Paper"),
                regime_at_entry, days_since,
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
    actual_pl_pkr_override: float | None = None,
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

        if actual_pl_pkr_override is not None:
            pl_pkr = actual_pl_pkr_override

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
            "SELECT 1 FROM trade_setups WHERE symbol=%s AND direction=%s AND source='System' AND status IN ('Pending','Active') LIMIT 1",
            (symbol, direction),
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


def auto_save_setups_with_source(setups: list[dict], source: str = "System") -> int:
    """PG version of auto_save_setups_with_source.
    Saves new system setups with explicit source label,
    skipping duplicates. Returns count saved."""
    saved = 0
    for s in setups:
        if not setup_already_saved(s["symbol"], s["direction"], s["created_date"]):
            s_with_source = dict(s, source=source)
            save_trade_setup(s_with_source)
            saved += 1
    if saved:
        logger.info("Auto-saved %d new system setup(s) (source=%s).", saved, source)
    return saved


def stm_pick_already_saved(symbol: str, date: str) -> bool:
    with get_conn() as conn:
        row = _fetchone(
            conn,
            "SELECT 1 FROM trade_setups WHERE symbol=%s AND source='STM' AND status IN ('Pending','Active') LIMIT 1",
            (symbol,),
        )
    return row is not None


def auto_save_stm_picks(picks: list[dict]) -> int:
    saved = 0
    for p in picks:
        date_str = str(p["created_date"])[:10]
        if not stm_pick_already_saved(p["symbol"], date_str):
            save_trade_setup(p)
            saved += 1
    if saved:
        logger.info("Auto-saved %d new STM pick(s).", saved)
    return saved


def get_sim_portfolio_data() -> list[dict]:
    """Return all rows from sim_portfolio_trades, or [] if table absent."""
    try:
        with get_conn() as conn:
            return _fetchall(
                conn,
                "SELECT * FROM sim_portfolio_trades ORDER BY setup_date, symbol",
            )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Portfolio Transactions & Values — manual end-of-month updates
# ---------------------------------------------------------------------------

def add_portfolio_transaction(date: str, tx_type: str, amount: float, notes: str = "") -> int:
    """Add a portfolio transaction (deposit, withdrawal, dividend)."""
    sql = """
        INSERT INTO portfolio_transactions (date, type, amount, notes)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """
    with get_conn() as conn:
        row = _fetchone(conn, sql, (date, tx_type, amount, notes))
    return row["id"] if row else 0


def get_portfolio_transactions() -> list[dict]:
    """Get all portfolio transactions, sorted by date."""
    with get_conn() as conn:
        return _fetchall(
            conn,
            "SELECT id, date, type, amount, notes, created_at FROM portfolio_transactions ORDER BY date DESC",
        )


def delete_portfolio_transaction(tx_id: int):
    """Delete a portfolio transaction by ID."""
    with get_conn() as conn:
        _exec(conn, "DELETE FROM portfolio_transactions WHERE id = %s", (tx_id,))


# ---------------------------------------------------------------------------
# Flows Signal Log
# ---------------------------------------------------------------------------

def init_flows_signal_log():
    """Create flows_signal_log table if it doesn't exist (idempotent)."""
    ddl = """
        CREATE TABLE IF NOT EXISTS flows_signal_log (
            id              SERIAL PRIMARY KEY,
            date            TEXT    NOT NULL,
            sector          TEXT    NOT NULL,
            signal_type     TEXT    NOT NULL,
            action          TEXT,
            strength        TEXT,
            trigger         TEXT,
            buy_ratio       DOUBLE PRECISION,
            buy_ratio_3d    DOUBLE PRECISION,
            consec_buy_days DOUBLE PRECISION,
            vol_zscore      DOUBLE PRECISION,
            ret_5d_pct      DOUBLE PRECISION,
            outcome         TEXT    DEFAULT 'PENDING',
            fwd_5d_actual   DOUBLE PRECISION,
            fwd_10d_actual  DOUBLE PRECISION,
            description     TEXT,
            smart_net_vol   DOUBLE PRECISION,
            confidence_note TEXT,
            UNIQUE(date, sector, signal_type)
        )
    """
    with get_conn() as conn:
        _exec(conn, ddl)


def upsert_flow_signals(signals: list[dict]):
    """Insert new signals — silently skips duplicates (date+sector+signal_type)."""
    if not signals:
        return
    sql = """
        INSERT INTO flows_signal_log
            (date, sector, signal_type, action, strength, trigger,
             buy_ratio, buy_ratio_3d, consec_buy_days, vol_zscore,
             ret_5d_pct, outcome, fwd_5d_actual)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (date, sector, signal_type) DO NOTHING
    """
    with get_conn() as conn:
        import psycopg2.extras
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur,
                sql,
                [
                    (
                        s["date"], s["sector"], s["signal_type"],
                        s.get("action"), s.get("strength"), s.get("trigger"),
                        s.get("buy_ratio"), s.get("buy_ratio_3d"),
                        s.get("consec_buy_days"), s.get("vol_zscore"),
                        s.get("ret_5d_pct"),
                        s.get("outcome", "PENDING"), s.get("fwd_5d_actual"),
                    )
                    for s in signals
                ],
            )


def get_flow_signal_journal() -> list[dict]:
    """Return all rows from flows_signal_log, newest first."""
    with get_conn() as conn:
        return _fetchall(
            conn,
            "SELECT * FROM flows_signal_log ORDER BY date DESC, sector",
        )


def update_flow_signal_outcome(row_id: int, fwd_5d_actual: float, outcome: str):
    """Write validated outcome back to a signal row."""
    with get_conn() as conn:
        _exec(
            conn,
            "UPDATE flows_signal_log SET fwd_5d_actual=%s, outcome=%s WHERE id=%s",
            (fwd_5d_actual, outcome, row_id),
        )


def add_portfolio_value(date: str, value: float, notes: str = "") -> int:
    """Add or update a portfolio value entry for a specific date."""
    sql = """
        INSERT INTO portfolio_values (date, value, notes)
        VALUES (%s, %s, %s)
        ON CONFLICT (date) DO UPDATE SET value = EXCLUDED.value, notes = EXCLUDED.notes
        RETURNING id
    """
    with get_conn() as conn:
        row = _fetchone(conn, sql, (date, value, notes))
    return row["id"] if row else 0


def get_portfolio_values() -> list[dict]:
    """Get all portfolio values, sorted by date."""
    with get_conn() as conn:
        return _fetchall(
            conn,
            "SELECT id, date, value, notes, created_at FROM portfolio_values ORDER BY date DESC",
        )


def delete_portfolio_value(val_id: int):
    """Delete a portfolio value entry by ID."""
    with get_conn() as conn:
        _exec(conn, "DELETE FROM portfolio_values WHERE id = %s", (val_id,))


def evaluate_paper_trades() -> dict:
    """
    Auto-evaluate pending paper trades against price history.
    Finds SL/TP hits based on daily closes and updates outcome.
    Returns: {"evaluated": count, "wins": count, "losses": count}
    """
    with get_conn() as conn:
        pending_paper = _fetchall(
            conn,
            """SELECT id, symbol, direction, created_date, entry_price, stop_loss, target_2r
               FROM trade_setups
               WHERE trade_execution='Paper' AND status='Pending' AND outcome IS NULL
               ORDER BY created_date ASC"""
        )

    if not pending_paper:
        return {"evaluated": 0, "wins": 0, "losses": 0}

    results = {"evaluated": 0, "wins": 0, "losses": 0}

    for trade in pending_paper:
        setup_id = trade["id"]
        symbol = trade["symbol"]
        direction = trade["direction"]
        entry_date = trade["created_date"]
        entry_price = float(trade["entry_price"])
        stop_loss = float(trade["stop_loss"])
        target = float(trade["target_2r"])

        with get_conn() as conn:
            prices = _fetchall(
                conn,
                """SELECT date, close FROM prices
                   WHERE symbol=%s AND date > %s
                   ORDER BY date ASC""",
                (symbol, entry_date)
            )

        outcome = None
        actual_exit = None
        exit_date = None
        holding_days = None
        actual_pl_pct = None
        status = "Pending"

        for price_row in prices:
            close = float(price_row["close"])
            current_date = str(price_row["date"])  # psycopg2 returns datetime.date; callers need str

            if direction == "LONG":
                if close <= stop_loss:
                    outcome = "LOSS"
                    status = "Hit SL"
                    actual_exit = stop_loss
                    exit_date = current_date
                    break
                elif close >= target:
                    outcome = "WIN"
                    status = "Hit Target"
                    actual_exit = target
                    exit_date = current_date
                    break
            else:
                if close >= stop_loss:
                    outcome = "LOSS"
                    status = "Hit SL"
                    actual_exit = stop_loss
                    exit_date = current_date
                    break
                elif close <= target:
                    outcome = "WIN"
                    status = "Hit Target"
                    actual_exit = target
                    exit_date = current_date
                    break

        if outcome:
            if exit_date and entry_date:
                from datetime import datetime
                exit_dt = datetime.fromisoformat(exit_date)
                entry_dt = datetime.fromisoformat(entry_date)
                holding_days = (exit_dt - entry_dt).days

            if actual_exit and entry_price > 0:
                if direction == "LONG":
                    actual_pl_pct = round((actual_exit - entry_price) / entry_price * 100, 2)
                else:
                    actual_pl_pct = round((entry_price - actual_exit) / entry_price * 100, 2)

            with get_conn() as conn:
                _exec(
                    conn,
                    """UPDATE trade_setups
                       SET outcome=%s, status=%s, actual_exit=%s,
                           exit_date=%s, holding_days=%s, actual_pl_pct=%s
                       WHERE id=%s""",
                    (outcome, status, actual_exit, exit_date, holding_days, actual_pl_pct, setup_id)
                )

            results["evaluated"] += 1
            if outcome == "WIN":
                results["wins"] += 1
            else:
                results["losses"] += 1

    return results


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL ENGINE — PG WRITE HELPERS
# Called by signal_engine.py when SUPABASE_DB_URL is set.
# ══════════════════════════════════════════════════════════════════════════════

def get_sector_signals_latest() -> list[dict]:
    """Latest date's rows from sector_signals. Used by run_portfolio_signals.
    composite_score cast to DOUBLE PRECISION so pandas quantile() works without Decimal errors."""
    sql = """
        SELECT date, sector, rs_rank,
               CAST(composite_score AS DOUBLE PRECISION) AS composite_score
        FROM sector_signals
        WHERE date = (SELECT MAX(date) FROM sector_signals)
        ORDER BY rs_rank
    """
    with get_conn() as conn:
        return _fetchall(conn, sql)


def write_recovery_signals(rows: list[dict], as_of_date: str) -> int:
    """DELETE existing rows for as_of_date, then batch-INSERT new ones. Returns row count.
    Converts numpy scalars to native Python types so psycopg2 can serialize them."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    _bool_cols = {"fresh", "kse_regime_ok"}

    def _py(col, v):
        """numpy scalar → native Python; int → bool for BOOLEAN PG columns."""
        v = v.item() if hasattr(v, "item") else v
        if col in _bool_cols and v is not None:
            return bool(v)
        return v

    cols = [
        "as_of_date", "symbol", "sector", "list_type",
        "close", "drawdown_pct", "base_days", "base_range_pct", "vol_ratio_today",
        "base_high", "dist_pct", "avg_vol_m", "triggered_date", "fresh",
        "trigger_close", "trigger_vol_x", "current_close", "move_pct",
        "pre_high", "kse_regime_ok",
    ]
    sql_ins = f"INSERT INTO recovery_signals ({', '.join(cols)}) VALUES %s"
    # as_of_date is not in the row dicts — use the explicit parameter for that column
    vals = [
        tuple(as_of_date if c == "as_of_date" else _py(c, r.get(c)) for c in cols)
        for r in rows
    ]
    with get_conn() as conn:
        _exec(conn, "DELETE FROM recovery_signals WHERE as_of_date = %s", (as_of_date,))
        with conn.cursor() as cur:
            execute_values(cur, sql_ins, vals)
    return len(vals)


def write_portfolio_signals(rows: list[dict], as_of_date: str) -> int:
    """DELETE existing rows for as_of_date, then batch-INSERT new ones. Returns row count.
    Converts numpy scalars to native Python types so psycopg2 can serialize them."""
    if not rows:
        return 0
    from psycopg2.extras import execute_values

    def _py(v):
        return v.item() if hasattr(v, "item") else v

    cols = [
        "as_of_date", "symbol", "sector", "latest_close", "latest_date",
        "ma10w", "ma30w", "dist_from_30w_pct", "stage", "stage_label",
        "rs_30d", "rs_10d", "rs_trend", "sector_rank", "sector_momentum",
        "composite_score", "recommendation", "rank",
    ]
    sql_ins = f"INSERT INTO portfolio_signals ({', '.join(cols)}) VALUES %s"
    vals = [tuple(_py(r.get(c)) for c in cols) for r in rows]
    with get_conn() as conn:
        _exec(conn, "DELETE FROM portfolio_signals WHERE as_of_date = %s", (as_of_date,))
        with conn.cursor() as cur:
            execute_values(cur, sql_ins, vals)
    return len(vals)


# ══════════════════════════════════════════════════════════════════════════════
# REGIME HOOK — PG HELPERS
# Called by regime.py when DATABASE_URL / SUPABASE_DB_URL is set.
# ══════════════════════════════════════════════════════════════════════════════

def get_kse100_for_regime(warmup: int = 250) -> tuple[int, list[dict]]:
    """Return (total_kse100_rows, last <warmup> rows ordered ASC) for regime computation."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM index_prices WHERE symbol = 'KSE-100'")
        total = cur.fetchone()[0]
        rows = _fetchall(
            conn,
            """
            SELECT date::text AS date, high, low, close
            FROM index_prices
            WHERE symbol = 'KSE-100'
            ORDER BY date DESC
            LIMIT %s
            """,
            (warmup,),
        )
    # _fetchall returns rows DESC; reverse so _compute_indicators sees ASC order
    return total, list(reversed(rows))


def get_latest_market_regime() -> tuple[str, int] | None:
    """Return (regime, regime_days) of the most recent market_regime row, or None."""
    with get_conn() as conn:
        row = _fetchone(
            conn,
            "SELECT regime, regime_days FROM market_regime ORDER BY date DESC LIMIT 1",
        )
    return (row["regime"], row["regime_days"]) if row else None


def get_latest_market_regime_date() -> str | None:
    """Return the date ('YYYY-MM-DD') of the most recent market_regime row, or None.

    Used by the backfill loop in regime.py to find where to resume after a
    gap, separately from get_latest_market_regime()'s (regime, regime_days).
    """
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date)::text AS d FROM market_regime")
    if row and row["d"]:
        d = row["d"]
        return d.isoformat() if hasattr(d, "isoformat") else str(d)
    return None


def get_kse100_full_for_regime() -> list[dict]:
    """Return every KSE-100 index_prices row (date, high, low, close), ascending.

    Regime classification needs a fully continuous KSE-100 series to compute
    correct EWM/ATR/return_20d indicators; a bounded 'last N rows' window
    (the old get_kse100_for_regime(warmup) behaviour) only ever supports
    writing the single latest date. Full history is a few thousand rows for
    KSE-100 -- cheap to pull every run -- and lets the backfill loop in
    regime.py recompute every missing date's indicators correctly in one pass.
    """
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            """
            SELECT date::text AS date, high, low, close
            FROM index_prices
            WHERE symbol = 'KSE-100'
            ORDER BY date
            """,
        )
    return rows


def write_market_regime(
    date_str: str,
    close: float,
    ema_20: float,
    ema_50: float,
    ema_200: float,
    atr_20: float | None,
    atr_pct: float | None,
    return_20d: float | None,
    regime: str,
    regime_days: int,
) -> None:
    """Upsert one row into market_regime. ON CONFLICT (date) DO UPDATE overwrites all indicators."""
    sql = """
        INSERT INTO market_regime
            (date, close, ema_20, ema_50, ema_200,
             atr_20, atr_pct, return_20d, regime, regime_days, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
        ON CONFLICT (date) DO UPDATE
            SET close      = EXCLUDED.close,
                ema_20     = EXCLUDED.ema_20,
                ema_50     = EXCLUDED.ema_50,
                ema_200    = EXCLUDED.ema_200,
                atr_20     = EXCLUDED.atr_20,
                atr_pct    = EXCLUDED.atr_pct,
                return_20d = EXCLUDED.return_20d,
                regime     = EXCLUDED.regime,
                regime_days= EXCLUDED.regime_days
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (
                date_str, close, ema_20, ema_50, ema_200,
                atr_20, atr_pct, return_20d, regime, regime_days,
            ))


# ══════════════════════════════════════════════════════════════════════════════
# DAYS_TO_NEAREST_TRANSITION BACKFILL — PG HELPERS
# Called by backfill_regime_columns.py when DATABASE_URL / SUPABASE_DB_URL is set.
# ══════════════════════════════════════════════════════════════════════════════

def get_market_regime_series_pg() -> list[tuple[str, str]]:
    """Return [(date_str, regime), ...] for every market_regime row, ordered ASC."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT date::text, regime FROM market_regime ORDER BY date")
        return cur.fetchall()


def get_pending_days_to_nearest_pg() -> list[tuple[int, str]]:
    """Return [(id, created_date), ...] for trade_setups rows still missing
    days_to_nearest_transition but with regime_at_entry already populated
    (i.e. created_date is known to exist in market_regime)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, created_date::text FROM trade_setups
            WHERE days_to_nearest_transition IS NULL
              AND regime_at_entry IS NOT NULL
            """
        )
        return cur.fetchall()


def update_days_to_nearest_batch_pg(updates: list[tuple[int, int]]) -> int:
    """Batch-update trade_setups.days_to_nearest_transition.
    updates: [(days_nearest, id), ...]. Returns the actual number of rows
    affected per psycopg2's cur.rowcount (verified reliable for executemany
    on this single-table UPDATE shape), not just len(updates)."""
    if not updates:
        return 0
    sql = "UPDATE trade_setups SET days_to_nearest_transition = %s WHERE id = %s"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, updates)
            return cur.rowcount


# ── STOCK SIGNALS — PG READ/WRITE HELPERS ────────────────────────────────────

def get_universe_pg() -> dict:
    """Returns {symbol: sector} for all rows in stock_metadata."""
    with get_conn() as conn:
        rows = _fetchall(conn, "SELECT symbol, sector FROM stock_metadata")
    return {r["symbol"]: r["sector"] for r in rows}


def get_kse100_for_signals(from_date: str, to_date: str) -> list:
    """Returns [(date_str, close_float), ...] ordered by date ASC."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT date::text AS date, CAST(close AS DOUBLE PRECISION) AS close "
            "FROM index_prices WHERE symbol = 'KSE-100' "
            "AND date BETWEEN %s AND %s ORDER BY date",
            (from_date, to_date),
        )
    return [(r["date"], r["close"]) for r in rows]


def get_prices_adjusted_for_signals(symbols: set, from_date: str, to_date: str) -> dict:
    """Returns {symbol: [(date_str, close_float), ...]} ordered by date ASC per symbol."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT symbol, date::text AS date, CAST(close AS DOUBLE PRECISION) AS close "
            "FROM prices_adjusted WHERE symbol = ANY(%s) "
            "AND date BETWEEN %s AND %s ORDER BY symbol, date",
            (list(symbols), from_date, to_date),
        )
    result: dict = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in result:
            result[sym] = []
        result[sym].append((r["date"], r["close"]))
    return result


def get_prices_adjusted_with_volume(symbols: set, from_date: str, to_date: str) -> dict:
    """Returns {symbol: [(date_str, close_float, volume, high_float), ...]} ordered by date ASC."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT symbol, date::text AS date, "
            "CAST(close AS DOUBLE PRECISION) AS close, volume, "
            "CAST(high AS DOUBLE PRECISION) AS high "
            "FROM prices_adjusted WHERE symbol = ANY(%s) "
            "AND date BETWEEN %s AND %s ORDER BY symbol, date",
            (list(symbols), from_date, to_date),
        )
    result: dict = {}
    for r in rows:
        sym = r["symbol"]
        if sym not in result:
            result[sym] = []
        result[sym].append((r["date"], r["close"], r["volume"], r["high"]))
    return result


def get_stock_signals_max_date_pg() -> str | None:
    """Returns MAX(date) from stock_signals as 'YYYY-MM-DD' string, or None."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date)::text AS d FROM stock_signals")
    if row and row["d"]:
        d = row["d"]
        return d.isoformat() if hasattr(d, "isoformat") else str(d)
    return None


def get_prices_adjusted_max_date_universe_pg() -> str | None:
    """Returns MAX(date) from prices_adjusted for universe symbols, or None."""
    with get_conn() as conn:
        row = _fetchone(
            conn,
            "SELECT MAX(date)::text AS d FROM prices_adjusted "
            "WHERE symbol IN (SELECT symbol FROM stock_metadata)",
        )
    if row and row["d"]:
        d = row["d"]
        return d.isoformat() if hasattr(d, "isoformat") else str(d)
    return None


def get_stock_signals_prev_ranks_pg(date_str: str) -> dict:
    """Returns {symbol: rs_rank} for the given date."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT symbol, rs_rank FROM stock_signals WHERE date = %s",
            (date_str,),
        )
    return {r["symbol"]: r["rs_rank"] for r in rows}


def get_stock_signals_seeds_pg(date_str: str) -> dict:
    """Returns {symbol: (base_duration, near_pivot_days)} for accumulation seeds."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT symbol, base_duration, near_pivot_days FROM stock_signals WHERE date = %s",
            (date_str,),
        )
    return {r["symbol"]: (r["base_duration"] or 0, r["near_pivot_days"] or 0) for r in rows}


_SS_BOOL_COLS = frozenset({9, 14, 15, 16, 18, 20, 21})
# Indices of BOOLEAN columns in the 22-column stock_signals tuple:
# 9=bos_flag, 14=stage2_bull, 15=close_above_ema50, 16=ema50_slope_pos,
# 18=overhead_clear, 20=close_above_ema150, 21=ema150_slope_pos


def write_stock_signals_batch(batch: list) -> int:
    """Batch-upsert a list of 22-column stock_signals tuples via execute_values. Returns count."""
    if not batch:
        return 0
    # Supabase stores these as BOOLEAN; psycopg2 rejects int 0/1 for boolean cols.
    def _norm(row):
        row = list(row)
        for i in _SS_BOOL_COLS:
            if row[i] is not None:
                row[i] = bool(row[i])
        return tuple(row)
    batch = [_norm(r) for r in batch]
    from psycopg2.extras import execute_values
    sql = """
        INSERT INTO stock_signals
            (date, symbol, rs_score_20, rs_score_50, rs_rank, rs_rank_prev,
             rank_change, sector_rs_rank, base_tightness, bos_flag, vol_contraction, avg_vol_10d,
             pivot_high, pivot_distance_pct, stage2_bull,
             close_above_ema50, ema50_slope_pos, base_duration, overhead_clear, near_pivot_days,
             close_above_ema150, ema150_slope_pos)
        VALUES %s
        ON CONFLICT (date, symbol) DO UPDATE SET
            rs_score_20        = EXCLUDED.rs_score_20,
            rs_score_50        = EXCLUDED.rs_score_50,
            rs_rank            = EXCLUDED.rs_rank,
            rs_rank_prev       = EXCLUDED.rs_rank_prev,
            rank_change        = EXCLUDED.rank_change,
            sector_rs_rank     = EXCLUDED.sector_rs_rank,
            base_tightness     = EXCLUDED.base_tightness,
            bos_flag           = EXCLUDED.bos_flag,
            vol_contraction    = EXCLUDED.vol_contraction,
            avg_vol_10d        = EXCLUDED.avg_vol_10d,
            pivot_high         = EXCLUDED.pivot_high,
            pivot_distance_pct = EXCLUDED.pivot_distance_pct,
            stage2_bull        = EXCLUDED.stage2_bull,
            close_above_ema50  = EXCLUDED.close_above_ema50,
            ema50_slope_pos    = EXCLUDED.ema50_slope_pos,
            base_duration      = EXCLUDED.base_duration,
            overhead_clear     = EXCLUDED.overhead_clear,
            near_pivot_days    = EXCLUDED.near_pivot_days,
            close_above_ema150 = EXCLUDED.close_above_ema150,
            ema150_slope_pos   = EXCLUDED.ema150_slope_pos
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, batch)
    logger.debug("Upserted %d stock_signals rows", len(batch))
    return len(batch)


# ── SECTOR SIGNALS — PG READ/WRITE HELPERS ───────────────────────────────────

def get_prices_adjusted_max_date_pg() -> str | None:
    """Returns MAX(date) from prices_adjusted (all symbols), or None."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date)::text AS d FROM prices_adjusted")
    if row and row["d"]:
        d = row["d"]
        return d.isoformat() if hasattr(d, "isoformat") else str(d)
    return None


def get_sector_signals_count_for_date_pg(date_str: str) -> int:
    """Returns row count in sector_signals for the given date."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT COUNT(*) AS n FROM sector_signals WHERE date = %s", (date_str,))
    return row["n"] if row else 0


def get_sector_signals_max_date_pg() -> str | None:
    """Returns MAX(date) from sector_signals, or None."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT MAX(date)::text AS d FROM sector_signals")
    if row and row["d"]:
        d = row["d"]
        return d.isoformat() if hasattr(d, "isoformat") else str(d)
    return None


def get_prices_adjusted_dates_between_pg(since_date: str | None, until_date: str) -> list[str]:
    """Returns sorted distinct prices_adjusted dates in (since_date, until_date],
    or all dates <= until_date when since_date is None.

    Used by the sector_signals backfill loop to find exactly which trading
    dates are missing after a hook failure, rather than only ever recomputing
    the single latest date (see docs/KIRAN_CLEANUP_AUDIT.md, 2026-08-07 gap).

    Both queries must ORDER BY the output column `d`, not by the raw `date`
    column. SELECT DISTINCT applies to the projected expression (`date::text`),
    so Postgres rejects `ORDER BY date` -- the raw column is not in the select
    list -- with "for SELECT DISTINCT, ORDER BY expressions must appear in
    select list". SQLite accepts that form, which is why this only ever failed
    in production: the error was swallowed by main.py's Tier-1 hook handler and
    froze sector_signals at 2026-08-11. `d` is ISO YYYY-MM-DD, so lexical order
    matches chronological order and the loop's oldest-first contract holds.
    See docs/KIRAN_CLEANUP_AUDIT.md 29.10.
    """
    with get_conn() as conn:
        if since_date:
            rows = _fetchall(
                conn,
                "SELECT DISTINCT date::text AS d FROM prices_adjusted "
                "WHERE date > %s AND date <= %s ORDER BY d",
                (since_date, until_date),
            )
        else:
            rows = _fetchall(
                conn,
                "SELECT DISTINCT date::text AS d FROM prices_adjusted "
                "WHERE date <= %s ORDER BY d",
                (until_date,),
            )
    return [r["d"] for r in rows]


def get_prices_warmup_with_sector_pg(target_date: str) -> list:
    """Returns 60-trading-day price warmup joined with sector, as list of dicts.

    Columns: date (str), symbol, close (float), volume, sector.
    """
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            """
            SELECT pa.date::text AS date, pa.symbol,
                   CAST(pa.close AS DOUBLE PRECISION) AS close,
                   pa.volume, sm.sector
            FROM prices_adjusted pa
            JOIN stock_metadata sm ON pa.symbol = sm.symbol
            WHERE pa.date IN (
                SELECT DISTINCT date FROM prices_adjusted
                WHERE date <= %s
                ORDER BY date DESC
                LIMIT 60
            )
              AND pa.close IS NOT NULL
              AND pa.close > 0
              AND sm.sector IS NOT NULL
            ORDER BY pa.symbol, pa.date
            """,
            (target_date,),
        )
    return rows


def get_kse100_warmup_pg(target_date: str) -> list:
    """Returns KSE-100 closes for the same 60-day warmup window, as list of dicts.

    Columns: date (str), kse_close (float).
    """
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            """
            SELECT date::text AS date, CAST(close AS DOUBLE PRECISION) AS kse_close
            FROM index_prices
            WHERE symbol = 'KSE-100'
              AND date IN (
                  SELECT DISTINCT date FROM prices_adjusted
                  WHERE date <= %s
                  ORDER BY date DESC
                  LIMIT 60
              )
            ORDER BY date
            """,
            (target_date,),
        )
    return rows


def get_regime_for_date_pg(date_str: str) -> str | None:
    """Returns regime text for the given date, or None."""
    with get_conn() as conn:
        row = _fetchone(conn, "SELECT regime FROM market_regime WHERE date = %s", (date_str,))
    return row["regime"] if row else None


def get_market_cap_pg() -> dict:
    """Returns {symbol: market_cap_m} from stock_market_cap."""
    with get_conn() as conn:
        rows = _fetchall(conn, "SELECT symbol, market_cap_m FROM stock_market_cap")
    return {r["symbol"]: (float(r["market_cap_m"]) if r["market_cap_m"] is not None else 0.0)
            for r in rows}


def get_active_symbols_pg() -> set:
    """Returns set of active symbols from stock_metadata (is_active = TRUE).

    Note: active_stocks_on_date is not in Supabase — this is the correct fallback.
    """
    with get_conn() as conn:
        rows = _fetchall(conn, "SELECT symbol FROM stock_metadata WHERE is_active = TRUE")
    return {r["symbol"] for r in rows}


def get_sector_signals_prev_ranks_sector_pg(date_str: str) -> dict:
    """Returns {sector: rs_rank} from the most recent sector_signals date before date_str."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT sector, rs_rank FROM sector_signals "
            "WHERE date = (SELECT MAX(date) FROM sector_signals WHERE date < %s)",
            (date_str,),
        )
    return {r["sector"]: r["rs_rank"] for r in rows}


def get_sector_rs_history_pg(date_str: str) -> dict:
    """Returns {sector: max_rs_score_20} for the 30-day window ending the day before date_str."""
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT sector, MAX(CAST(rs_score_20 AS DOUBLE PRECISION)) AS max_rs "
            "FROM sector_signals "
            "WHERE date < %s AND date >= %s::date - INTERVAL '30 days' "
            "GROUP BY sector",
            (date_str, date_str),
        )
    return {
        r["sector"]: float(r["max_rs"]) if r["max_rs"] is not None else None
        for r in rows
    }


def write_sector_signals_batch_pg(rows: list) -> int:
    """Upsert sector_signals rows (18-column main insert). Returns count.

    Each row dict must have keys matching the 18 INSERT columns.
    flow_* columns are left untouched here; updated separately via
    update_sector_flow_signals_pg().
    """
    if not rows:
        return 0
    from psycopg2.extras import execute_values
    sql = """
        INSERT INTO sector_signals
            (date, sector, rs_score_20, rs_score_50, rs_rank, rs_rank_prev,
             breadth_score, adv_dec_ratio, vol_ratio, rs_inflection,
             regime, composite_score,
             sector_ema50, sector_above_ema, sector_ema_slope,
             sector_stage, sector_pivot_dist_pct, sector_rs_new_high)
        VALUES %s
        ON CONFLICT (date, sector) DO UPDATE SET
            rs_score_20           = EXCLUDED.rs_score_20,
            rs_score_50           = EXCLUDED.rs_score_50,
            rs_rank               = EXCLUDED.rs_rank,
            rs_rank_prev          = EXCLUDED.rs_rank_prev,
            breadth_score         = EXCLUDED.breadth_score,
            adv_dec_ratio         = EXCLUDED.adv_dec_ratio,
            vol_ratio             = EXCLUDED.vol_ratio,
            rs_inflection         = EXCLUDED.rs_inflection,
            regime                = EXCLUDED.regime,
            composite_score       = EXCLUDED.composite_score,
            sector_ema50          = EXCLUDED.sector_ema50,
            sector_above_ema      = EXCLUDED.sector_above_ema,
            sector_ema_slope      = EXCLUDED.sector_ema_slope,
            sector_stage          = EXCLUDED.sector_stage,
            sector_pivot_dist_pct = EXCLUDED.sector_pivot_dist_pct,
            sector_rs_new_high    = EXCLUDED.sector_rs_new_high
    """
    batch = [
        (
            r["date"], r["sector"],
            r.get("rs_score_20"), r.get("rs_score_50"),
            r.get("rs_rank"), r.get("rs_rank_prev"),
            r.get("breadth_score"), r.get("adv_dec_ratio"), r.get("vol_ratio"),
            int(r.get("rs_inflection", 0) or 0),
            r.get("regime"),
            float(r["composite_score"]) if r.get("composite_score") is not None else None,
            r.get("sector_ema50"), r.get("sector_above_ema"),
            r.get("sector_ema_slope"), r.get("sector_stage"),
            r.get("sector_pivot_dist_pct"),
            int(r.get("rs_new_high", 0) or 0),
        )
        for r in rows
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, batch)
    logger.debug("Upserted %d sector_signals rows", len(batch))
    return len(batch)


def get_market_flows_pg(date_str: str) -> list:
    """Returns market_flows rows (REGULAR market, up to date_str) for flow computation.

    Columns: date (str), sector, client_type, net_value (float).
    Empty list when market_flows has no data.
    """
    with get_conn() as conn:
        rows = _fetchall(
            conn,
            "SELECT date::text AS date, sector, client_type, "
            "CAST(net_value AS DOUBLE PRECISION) AS net_value "
            "FROM market_flows WHERE market_type = 'REGULAR' AND date <= %s ORDER BY date",
            (date_str,),
        )
    return rows


def update_sector_flow_signals_pg(date_str: str, flow_rows: list) -> None:
    """UPDATE flow_* columns in sector_signals for date_str.

    Each dict in flow_rows: {sector, flow_smart_net_5d, flow_smart_net_20d,
                              flow_retail_net_5d, flow_retail_net_20d, flow_direction}.
    """
    if not flow_rows:
        return
    sql = """
        UPDATE sector_signals
        SET flow_smart_net_5d   = %s,
            flow_smart_net_20d  = %s,
            flow_retail_net_5d  = %s,
            flow_retail_net_20d = %s,
            flow_direction      = %s
        WHERE date = %s AND sector = %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in flow_rows:
                cur.execute(sql, (
                    r["flow_smart_net_5d"],
                    r["flow_smart_net_20d"],
                    r["flow_retail_net_5d"],
                    r["flow_retail_net_20d"],
                    r["flow_direction"],
                    date_str,
                    r["sector"],
                ))


# ── MARKET FLOWS ──────────────────────────────────────────────────────────────

def upsert_flows_pg(rows: list[tuple]) -> None:
    """Upsert market_flows rows to Supabase.

    Each tuple must be 12-element, matching the SQLite upsert_flows() order:
      (date, flow_type, client_type, sector, market_type,
       buy_volume, buy_value, sell_volume, sell_value,
       net_volume, net_value, usd_net)

    UNIQUE constraint is (date, flow_type, client_type, sector, market_type).
    """
    if not rows:
        return
    # Deduplicate on unique key (date, flow_type, client_type, sector, market_type)
    # — keep last occurrence per key so ON CONFLICT DO UPDATE doesn't see the same
    # key twice within one execute_values batch (which PostgreSQL rejects).
    seen: dict[tuple, tuple] = {}
    for row in rows:
        key = (row[0], row[1], row[2], row[3], row[4])  # date/type/client/sector/market
        seen[key] = row
    rows = list(seen.values())

    from psycopg2.extras import execute_values
    sql = """
        INSERT INTO market_flows
            (date, flow_type, client_type, sector, market_type,
             buy_volume, buy_value, sell_volume, sell_value,
             net_volume, net_value, usd_net)
        VALUES %s
        ON CONFLICT (date, flow_type, client_type, sector, market_type)
        DO UPDATE SET
            buy_volume  = EXCLUDED.buy_volume,
            buy_value   = EXCLUDED.buy_value,
            sell_volume = EXCLUDED.sell_volume,
            sell_value  = EXCLUDED.sell_value,
            net_volume  = EXCLUDED.net_volume,
            net_value   = EXCLUDED.net_value,
            usd_net     = EXCLUDED.usd_net
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows)


# ── PRICES_ADJUSTED / CORPORATE ACTION SUSPECTS ───────────────────────────────

def ensure_suspects_table_pg() -> None:
    """No-op in PG mode — corporate_action_suspects already exists in Supabase."""
    pass


def append_new_prices_adjusted_pg() -> int:
    """Append new rows from prices into prices_adjusted (no adjustment applied).

    Uses a single INSERT...SELECT — both tables are in the same Postgres DB so
    no Python-level fetch+insert loop is needed.  Returns the number of rows
    appended (0 if already up to date).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date)::text FROM prices_adjusted")
            last_adjusted = cur.fetchone()[0]

            if last_adjusted is None:
                print("prices_adjusted is empty — skipping incremental append (run full rebuild first)")
                return 0

            cur.execute("SELECT COUNT(*) FROM prices WHERE date > %s", (last_adjusted,))
            count = cur.fetchone()[0]

            if count == 0:
                print("prices_adjusted is up to date")
                return 0

            cur.execute(
                "SELECT MIN(date)::text, MAX(date)::text FROM prices WHERE date > %s",
                (last_adjusted,),
            )
            min_date, max_date = cur.fetchone()

            cur.execute(
                "INSERT INTO prices_adjusted SELECT * FROM prices WHERE date > %s",
                (last_adjusted,),
            )

    print(f"Appended {count:,} rows for dates {min_date} to {max_date}")
    return count


def auto_detect_suspects_pg() -> int:
    """Scan newly appended prices_adjusted rows for corporate action suspects.

    Uses a LAG window function to compare each row's close to the previous
    trading day's close for the same symbol — equivalent to the SQLite loop
    in auto_detect_suspects().  Only symbols present in stock_metadata are
    scanned.  Existing (symbol, suspect_date) pairs are silently skipped via
    ON CONFLICT DO NOTHING.

    Returns the number of new suspect rows inserted.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(suspect_date)::text FROM corporate_action_suspects")
            last_flagged = cur.fetchone()[0]

            if last_flagged is None:
                # Safety net: scan the last 5 distinct trading dates
                cur.execute("""
                    SELECT date::text FROM (
                        SELECT DISTINCT date FROM prices_adjusted ORDER BY date DESC LIMIT 5
                    ) sub ORDER BY date ASC LIMIT 1
                """)
                row = cur.fetchone()
                scan_from = row[0] if row else None
            else:
                scan_from = last_flagged

            if scan_from is None:
                print("No data in prices_adjusted to scan.")
                return 0

            # LAG over the full window (including scan_from itself) so the first
            # date after scan_from has a valid prev_close to compare against.
            # Only INSERT suspects where date > scan_from.
            cur.execute("""
                WITH lookback AS (
                    SELECT pa.symbol, pa.date, pa.close,
                           LAG(pa.close) OVER (
                               PARTITION BY pa.symbol ORDER BY pa.date
                           ) AS prev_close
                    FROM prices_adjusted pa
                    JOIN stock_metadata sm ON pa.symbol = sm.symbol
                    WHERE pa.date >= %s
                ),
                suspects AS (
                    SELECT symbol, date,
                           prev_close   AS close_before,
                           close        AS close_after,
                           (close - prev_close) / prev_close * 100.0 AS drop_pct
                    FROM lookback
                    WHERE date > %s
                      AND prev_close IS NOT NULL
                      AND prev_close > 0
                      AND (close - prev_close) / prev_close * 100.0 < -12.0
                )
                INSERT INTO corporate_action_suspects
                    (symbol, suspect_date, close_before, close_after,
                     drop_pct, likely_category, status)
                SELECT
                    symbol, date, close_before, close_after, drop_pct,
                    CASE
                        WHEN drop_pct < -40 THEN 'DROP_50'
                        WHEN drop_pct < -28 THEN 'DROP_33'
                        WHEN drop_pct < -20 THEN 'DROP_25'
                        ELSE                     'DROP_OTHER'
                    END,
                    'PENDING'
                FROM suspects
                WHERE NOT EXISTS (
                    SELECT 1 FROM corporate_action_suspects cas
                    WHERE cas.symbol = suspects.symbol
                      AND cas.suspect_date = suspects.date
                )
            """, (scan_from, scan_from))

            new_suspects = cur.rowcount

    print(f"auto_detect_suspects_pg: {new_suspects} new suspect(s) flagged")
    return new_suspects


def rebuild_symbol_adjusted_pg(symbol: str, ex_date: str, adjustment_factor: float) -> int:
    """Applies a single corporate action factor to one symbol's pre-event rows.

    Postgres twin of apply_price_adjustments.rebuild_symbol_adjusted() -- %s
    placeholders instead of ?, no connection parameter (self-contained via
    get_conn(), matching append_new_prices_adjusted_pg / auto_detect_suspects_pg
    above). prices_adjusted.open/high/low/close are NUMERIC(18,6), not double
    precision, so unlike E10.3's get_regime_definitions_pg() fix, no ::numeric
    cast is needed before ROUND() -- verified directly against live Supabase:
    psycopg2 sends a plain Python float as an untyped numeric literal, so
    numeric_col * factor stays numeric and ROUND(numeric, 4) resolves as-is.
    Tested directly against live Supabase (backup/apply/verify/restore on a
    real symbol's price rows) -- this function itself is correct.

    NOT currently called from dashboard.py's Confirm button -- that button
    hard-blocks under _PG_URL instead (see CLAUDE.md "Known Gaps: Postgres
    parity") because recompute_symbol_signals() (stock_signals.py), which
    the Confirm button also needs to call, has no Postgres port and the
    nightly pipeline never revisits historical stock_signals rows. This
    function is left in place, tested and ready, for whenever that gap
    closes and the hard block can be lifted.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE prices_adjusted
                SET open  = ROUND(open  * %s, 4),
                    high  = ROUND(high  * %s, 4),
                    low   = ROUND(low   * %s, 4),
                    close = ROUND(close * %s, 4)
                WHERE symbol = %s AND date < %s
            """, (adjustment_factor, adjustment_factor, adjustment_factor, adjustment_factor,
                  symbol, ex_date))
            rows_updated = cur.rowcount

    print(f"{symbol} — {rows_updated:,} rows adjusted "
          f"(factor={adjustment_factor:.4f}, ex_date={ex_date})")
    return rows_updated


# ── ROLLING TRIM ───────────────────────────────────────────────────────────────

# Confirmed date columns (verified against Supabase schema 2026-07-08):
_TRIM_TABLES: list[tuple[str, str]] = [
    ("prices",              "date"),
    ("prices_adjusted",     "date"),
    ("stock_signals",       "date"),
    ("setup_log",           "setup_date"),
    ("symbol_active_dates", "date"),
]


def trim_old_rows_pg() -> dict[str, int]:
    """Delete rows older than 2 years from the five large Supabase tables.

    Uses CURRENT_DATE - INTERVAL '2 years' as the cutoff so the window
    rolls forward automatically each night.  Each table is trimmed in its
    own transaction; a failure on one table does not affect the others.

    Returns a dict of {table_name: rows_deleted}.
    Local SQLite (psx_data.db) is the permanent full-history archive —
    these deletions only affect the rolling Supabase operational copy.
    """
    results: dict[str, int] = {}
    for tbl, date_col in _TRIM_TABLES:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {tbl}"
                        f" WHERE {date_col} < CURRENT_DATE - INTERVAL '2 years'"
                    )
                    results[tbl] = cur.rowcount
        except Exception as exc:
            results[tbl] = -1
            print(f"trim_old_rows_pg: error on {tbl}: {exc}")
    return results
