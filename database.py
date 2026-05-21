"""
Storage layer for PSX sector/price data.

Auto-selects backend at import time:
  • DATABASE_URL or SUPABASE_DB_URL set in environment  →  PostgreSQL (Supabase)
  • Otherwise                                            →  local SQLite

All other modules (dashboard, processor, scraper, …) just do:
    import database as db
and never need to know which backend is active.
"""

import sqlite3
import logging
import os
from contextlib import contextmanager
from config import DB_PATH

logger = logging.getLogger(__name__)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sectors (
                symbol  TEXT NOT NULL,
                sector  TEXT NOT NULL,
                PRIMARY KEY (symbol)
            );

            CREATE TABLE IF NOT EXISTS prices (
                symbol  TEXT NOT NULL,
                date    TEXT NOT NULL,
                close   REAL NOT NULL,
                PRIMARY KEY (symbol, date)
            );

            CREATE TABLE IF NOT EXISTS index_prices (
                symbol  TEXT NOT NULL,
                date    TEXT NOT NULL,
                high    REAL,
                low     REAL,
                close   REAL NOT NULL,
                PRIMARY KEY (symbol, date)
            );
            CREATE INDEX IF NOT EXISTS idx_idx_date ON index_prices (date);

            CREATE TABLE IF NOT EXISTS trade_setups (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                created_date     TEXT NOT NULL,
                direction        TEXT NOT NULL,   -- LONG | SHORT
                symbol           TEXT NOT NULL,
                sector           TEXT NOT NULL,
                sector_momentum  TEXT NOT NULL,
                stock_perf_30d   REAL NOT NULL,
                stock_perf_10d   REAL NOT NULL,
                latest_close     REAL NOT NULL,
                support_level    REAL,            -- breakdown level (shorts)
                resistance_level REAL,            -- breakout level  (longs)
                entry_price      REAL NOT NULL,
                stop_loss        REAL NOT NULL,
                target_1r        REAL NOT NULL,
                target_2r        REAL NOT NULL,
                risk_pct         REAL NOT NULL,
                atr_pct          REAL NOT NULL,
                status           TEXT NOT NULL DEFAULT 'Pending',
                outcome          TEXT,            -- Win | Loss | Breakeven
                notes            TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_prices_date    ON prices (date);
            CREATE INDEX IF NOT EXISTS idx_prices_symbol  ON prices (symbol);
            CREATE INDEX IF NOT EXISTS idx_setups_symbol  ON trade_setups (symbol);
            CREATE INDEX IF NOT EXISTS idx_setups_status  ON trade_setups (status);

            CREATE TABLE IF NOT EXISTS portfolio_transactions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                date       TEXT NOT NULL,
                type       TEXT NOT NULL,  -- deposit | withdrawal | dividend
                amount     REAL NOT NULL,
                notes      TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_tx_date ON portfolio_transactions (date);

            CREATE TABLE IF NOT EXISTS portfolio_values (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                date       TEXT NOT NULL UNIQUE,
                value      REAL NOT NULL,
                notes      TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_portfolio_val_date ON portfolio_values (date);
        """)

    # Non-destructive migrations — add new columns if they don't exist yet
    migrations = [
        "ALTER TABLE prices ADD COLUMN volume INTEGER",
        "ALTER TABLE prices ADD COLUMN high   REAL",
        "ALTER TABLE prices ADD COLUMN low    REAL",
        "ALTER TABLE trade_setups ADD COLUMN quality_score   INTEGER DEFAULT 0",
        "ALTER TABLE trade_setups ADD COLUMN quality_checks  TEXT    DEFAULT '{}'",
        "ALTER TABLE trade_setups ADD COLUMN range_width_pct REAL",
        "ALTER TABLE trade_setups ADD COLUMN range_window    INTEGER",
        "ALTER TABLE trade_setups ADD COLUMN sector_rank     INTEGER",
        "ALTER TABLE trade_setups ADD COLUMN breadth_score   REAL",
        "ALTER TABLE trade_setups ADD COLUMN source          TEXT    DEFAULT 'System'",
        "ALTER TABLE trade_setups ADD COLUMN actual_exit     REAL",
        "ALTER TABLE trade_setups ADD COLUMN actual_pl_pkr   REAL",
        "ALTER TABLE trade_setups ADD COLUMN actual_pl_pct   REAL",
        "ALTER TABLE trade_setups ADD COLUMN actual_rr       REAL",
        "ALTER TABLE trade_setups ADD COLUMN holding_days    INTEGER",
        "ALTER TABLE trade_setups ADD COLUMN exit_date       TEXT",
        "ALTER TABLE trade_setups ADD COLUMN actual_entry    REAL",  # user's actual fill
    ]
    with get_conn() as conn:
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists

    # Data migrations (safe to run multiple times)
    data_migrations = [
        "UPDATE trade_setups SET status='Closed' WHERE status IN ('Hit Target', 'Hit SL')",
    ]
    with get_conn() as conn:
        for sql in data_migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass

    logger.info("Database initialised at %s", DB_PATH)


def upsert_sectors(rows: list[tuple[str, str]]):
    """Insert or replace (symbol, sector) pairs."""
    with get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO sectors (symbol, sector) VALUES (?, ?)",
            rows,
        )
    logger.debug("Upserted %d sector rows", len(rows))


def upsert_prices(rows: list[tuple]):
    """
    Insert price rows.
    Accepts tuples of varying length:
      3-tuple : (symbol, date, close)
      4-tuple : (symbol, date, close, volume)             -- legacy
      6-tuple : (symbol, date, high, low, close, volume)  -- current format

    On conflict: fills in NULL high/low/volume but never overwrites existing
    close (close is the anchor price; scraper guarantees it is correct).
    """
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

    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO prices (symbol, date, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, date) DO UPDATE
                   SET high   = COALESCE(excluded.high,   prices.high),
                       low    = COALESCE(excluded.low,    prices.low),
                       volume = COALESCE(excluded.volume, prices.volume)""",
            normalised,
        )
    logger.debug("Upserted %d price rows", len(rows))


def upsert_index_prices(rows: list[tuple]):
    """
    Insert/update index OHLC rows.
    Accepts 5-tuples: (symbol, date, high, low, close)
    On conflict: fills NULL high/low but never overwrites close.
    """
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO index_prices (symbol, date, high, low, close)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(symbol, date) DO UPDATE
                   SET high  = COALESCE(excluded.high, index_prices.high),
                       low   = COALESCE(excluded.low,  index_prices.low)""",
            rows,
        )
    logger.debug("Upserted %d index price rows", len(rows))


def get_index_prices(symbol: str = "KSE-100") -> list[dict]:
    """Return all rows for an index symbol, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date, high, low, close FROM index_prices
               WHERE symbol = ? ORDER BY date""",
            (symbol,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_symbols() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT symbol FROM sectors ORDER BY symbol").fetchall()
    return [r["symbol"] for r in rows]


def get_all_sectors_df():
    """Return sectors table as a list of dicts."""
    with get_conn() as conn:
        rows = conn.execute("SELECT symbol, sector FROM sectors ORDER BY sector, symbol").fetchall()
    return [dict(r) for r in rows]


def get_prices_df(symbol: str, limit: int = 60) -> list[dict]:
    """Return the most recent `limit` price rows for a symbol, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT date, close FROM prices
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_scraped_date() -> str | None:
    """Return the most recent date that has price data, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(date) AS d FROM prices").fetchone()
    return row["d"] if row else None


def get_latest_prices() -> list[tuple]:
    """Return (symbol, date, high, low, close) rows for the most recent stored date."""
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(date) AS d FROM prices").fetchone()
        if not row or not row["d"]:
            return []
        rows = conn.execute(
            "SELECT symbol, date, high, low, close FROM prices WHERE date = ?",
            (row["d"],),
        ).fetchall()
    return [(r["symbol"], r["date"], r["high"], r["low"], r["close"]) for r in rows]


def cleanup_ghost_dates():
    """
    Delete market-wide holiday ghosts: dates where PSX returned the previous
    or next session's data for almost all symbols instead of real trading data.
    Two passes:
      - Backward ghost: THIS date matches its LAG  (holiday stored prev session)
      - Forward ghost:  THIS date matches its LEAD (closed day stored next session)
    Threshold: >=90% of symbols identical, minimum 50 symbols.
    """
    backward_sql = """
        DELETE FROM prices
        WHERE date IN (
            SELECT date FROM (
                SELECT date,
                       COUNT(*) AS total,
                       SUM(CASE WHEN high = ph AND low = pl AND close = pc THEN 1 ELSE 0 END) AS matches
                FROM (
                    SELECT symbol, date, high, low, close,
                           LAG(high)  OVER (PARTITION BY symbol ORDER BY date) AS ph,
                           LAG(low)   OVER (PARTITION BY symbol ORDER BY date) AS pl,
                           LAG(close) OVER (PARTITION BY symbol ORDER BY date) AS pc
                    FROM prices
                ) sub
                WHERE ph IS NOT NULL
                GROUP BY date
            )
            WHERE total >= 50 AND CAST(matches AS REAL) / total >= 0.90
        )
    """
    forward_sql = """
        DELETE FROM prices
        WHERE date IN (
            SELECT date FROM (
                SELECT date,
                       COUNT(*) AS total,
                       SUM(CASE WHEN high = nh AND low = nl AND close = nc THEN 1 ELSE 0 END) AS matches
                FROM (
                    SELECT symbol, date, high, low, close,
                           LEAD(high)  OVER (PARTITION BY symbol ORDER BY date) AS nh,
                           LEAD(low)   OVER (PARTITION BY symbol ORDER BY date) AS nl,
                           LEAD(close) OVER (PARTITION BY symbol ORDER BY date) AS nc
                    FROM prices
                ) sub
                WHERE nh IS NOT NULL
                GROUP BY date
            )
            WHERE total >= 50 AND CAST(matches AS REAL) / total >= 0.90
        )
    """
    total_deleted = 0
    with get_conn() as conn:
        # Forward pass first: removes ghost dates that stored the NEXT session's data.
        # Must run before backward pass so that the real data following a forward ghost
        # is not mistakenly flagged as a backward ghost (they share identical H/L/C).
        conn.execute(forward_sql)
        total_deleted += conn.execute("SELECT changes()").fetchone()[0]
        conn.execute(backward_sql)
        total_deleted += conn.execute("SELECT changes()").fetchone()[0]
    if total_deleted:
        logger.info("cleanup_ghost_dates: removed %d rows for market-closed dates", total_deleted)
    return total_deleted


def get_price_date_range() -> tuple[str | None, str | None]:
    with get_conn() as conn:
        row = conn.execute("SELECT MIN(date) AS mn, MAX(date) AS mx FROM prices").fetchone()
    return (row["mn"], row["mx"]) if row else (None, None)


def get_sector_price_data() -> list[dict]:
    """
    Join sectors × prices for the last 60 days.
    Returns rows: symbol, sector, date, high, low, close, volume — useful for processor.
    high/low fall back to close when not yet populated (legacy rows).
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.symbol, s.sector, p.date,
                   COALESCE(p.high, p.close) AS high,
                   COALESCE(p.low,  p.close) AS low,
                   p.close,
                   COALESCE(p.volume, 0)     AS volume
            FROM sectors s
            JOIN prices  p ON p.symbol = s.symbol
            ORDER BY s.symbol, p.date
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_prices_for_breadth() -> list[dict]:
    """Return all symbol/date/close rows for Weinstein breadth computation."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, date, close FROM prices ORDER BY symbol, date"
        ).fetchall()
    return [dict(r) for r in rows]


def count_prices() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]


def count_sectors() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM sectors").fetchone()[0]


# ---------------------------------------------------------------------------
# Trade setups
# ---------------------------------------------------------------------------

def save_trade_setup(s: dict) -> int:
    """Insert a new trade setup. Returns the new row id."""
    import json
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trade_setups (
                created_date, direction, symbol, sector, sector_momentum,
                stock_perf_30d, stock_perf_10d, latest_close,
                support_level, resistance_level,
                entry_price, stop_loss, target_1r, target_2r,
                risk_pct, atr_pct, status, notes,
                quality_score, quality_checks,
                range_width_pct, range_window, sector_rank, breadth_score,
                source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                s["created_date"], s["direction"], s["symbol"], s["sector"],
                s.get("sector_momentum", "—"),
                s.get("stock_perf_30d", 0.0), s.get("stock_perf_10d", 0.0),
                s.get("latest_close", 0.0),
                s.get("support_level"), s.get("resistance_level"),
                s["entry_price"], s["stop_loss"],
                s.get("target_1r", 0.0), s.get("target_2r", 0.0),
                s.get("risk_pct", 0.0), s.get("atr_pct", 0.0),
                s.get("status", "Pending"), s.get("notes", ""),
                s.get("quality_score", 0),
                json.dumps(s.get("quality_checks", {})),
                s.get("range_width_pct"), s.get("range_window"),
                s.get("sector_rank"), s.get("breadth_score"),
                s.get("source", "System"),
            ),
        )
        return cur.lastrowid


def get_trade_setups(status: str | None = None) -> list[dict]:
    """Return all setups, optionally filtered by status."""
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM trade_setups WHERE status=? ORDER BY created_date DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_setups ORDER BY created_date DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def update_trade_setup(setup_id: int, status: str, outcome: str | None = None, notes: str | None = None):
    """Update the status, outcome, and notes of an existing setup."""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE trade_setups
            SET status  = ?,
                outcome = COALESCE(?, outcome),
                notes   = COALESCE(?, notes)
            WHERE id = ?
            """,
            (status, outcome, notes, setup_id),
        )


def activate_trade_setup(
    setup_id: int,
    actual_entry: float | None = None,
    notes: str | None = None,
):
    """
    Mark a system setup as 'taken' by the trader.
    Sets status='Active', records the actual fill price and any notes.
    Does NOT create a new row — the existing system record is updated in-place.
    """
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE trade_setups
            SET status       = 'Active',
                actual_entry = COALESCE(?, actual_entry),
                notes        = COALESCE(?, notes)
            WHERE id = ?
            """,
            (actual_entry, notes, setup_id),
        )


def close_trade_setup(
    setup_id: int,
    exit_price: float,
    exit_date: str,
    status: str,
    outcome: str,
    notes: str | None = None,
    actual_pl_pkr_override: float | None = None,
):
    """
    Close an open position — fills exit_price, exit_date, calculates P&L%
    and holding_days, then updates status/outcome.
    Pass actual_pl_pkr_override with the real PKR amount (e.g. -15000) to
    record actual money made/lost; otherwise falls back to per-share difference.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT entry_price, actual_entry, direction, created_date FROM trade_setups WHERE id = ?",
            (setup_id,),
        ).fetchone()
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

        # holding days
        try:
            from datetime import date as _date
            d0 = _date.fromisoformat(open_date[:10])
            d1 = _date.fromisoformat(exit_date[:10])
            hold = (d1 - d0).days
        except Exception:
            hold = None

        conn.execute(
            """
            UPDATE trade_setups
            SET actual_exit   = ?,
                exit_date     = ?,
                actual_pl_pct = ?,
                actual_pl_pkr = ?,
                holding_days  = ?,
                status        = ?,
                outcome       = ?,
                notes         = COALESCE(?, notes)
            WHERE id = ?
            """,
            (exit_price, exit_date, round(pl_pct, 2), round(pl_pkr, 2), hold,
             status, outcome, notes, setup_id),
        )


def delete_trade_setup(setup_id: int):
    """Permanently remove a single trade setup row by ID."""
    with get_conn() as conn:
        conn.execute("DELETE FROM trade_setups WHERE id = ?", (setup_id,))


def setup_already_saved(symbol: str, direction: str, created_date: str) -> bool:
    """Prevent saving a setup when the same symbol+direction already has an open one."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM trade_setups
            WHERE symbol=? AND direction=? AND source='System' AND status IN ('Pending','Active')
            LIMIT 1
            """,
            (symbol, direction),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

def get_backtest_summary() -> list[dict]:
    """Return all rows from backtest_setups, or [] if table doesn't exist yet."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_setups ORDER BY as_of_date"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def auto_save_setups(setups: list[dict]) -> int:
    """
    Automatically persist system-generated setups.
    Skips any setup already recorded for the same symbol+direction+date.
    Returns the count of newly saved rows.
    """
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
    """
    Automatically persist setups while preserving their source.
    Skips any setup already recorded for the same symbol+direction+date.
    Returns the count of newly saved rows.
    """
    saved = 0
    for s in setups:
        if not setup_already_saved(s["symbol"], s["direction"], s["created_date"]):
            s_with_source = dict(s, source=source)
            save_trade_setup(s_with_source)
            saved += 1
    if saved:
        logger.info("Auto-saved %d new %s setup(s).", saved, source)
    return saved


def stm_pick_already_saved(symbol: str, date: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM trade_setups WHERE symbol=? AND source='STM' AND status IN ('Pending','Active') LIMIT 1",
            (symbol,),
        ).fetchone()
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


# ---------------------------------------------------------------------------
# Kiran Simulation (kiran_sim.py) — portfolio backtest with new entry rules
# ---------------------------------------------------------------------------

def get_sim_portfolio_data() -> list[dict]:
    """Return all rows from sim_portfolio_trades, or [] if table absent."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sim_portfolio_trades ORDER BY setup_date, symbol"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Portfolio Transactions & Values — manual end-of-month updates
# ---------------------------------------------------------------------------

def add_portfolio_transaction(date: str, tx_type: str, amount: float, notes: str = "") -> int:
    """Add a portfolio transaction (deposit, withdrawal, dividend)."""
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO portfolio_transactions (date, type, amount, notes)
               VALUES (?, ?, ?, ?)""",
            (date, tx_type, amount, notes)
        )
        return cursor.lastrowid


def get_portfolio_transactions() -> list[dict]:
    """Get all portfolio transactions, sorted by date."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_transactions ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_portfolio_transaction(tx_id: int):
    """Delete a portfolio transaction by ID."""
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_transactions WHERE id = ?", (tx_id,))


def add_portfolio_value(date: str, value: float, notes: str = "") -> int:
    """Add or update a portfolio value entry for a specific date."""
    with get_conn() as conn:
        cursor = conn.execute(
            """INSERT OR REPLACE INTO portfolio_values (date, value, notes)
               VALUES (?, ?, ?)""",
            (date, value, notes)
        )
        return cursor.lastrowid


def get_portfolio_values() -> list[dict]:
    """Get all portfolio values, sorted by date."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_values ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_portfolio_value(val_id: int):
    """Delete a portfolio value entry by ID."""
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_values WHERE id = ?", (val_id,))


def evaluate_paper_trades() -> dict:
    """
    Auto-evaluate pending paper trades against price history.
    Finds SL/TP hits based on daily closes and updates outcome.
    Returns: {"evaluated": count, "wins": count, "losses": count}
    """
    with get_conn() as conn:
        pending_paper = conn.execute(
            """SELECT id, symbol, direction, created_date, entry_price, stop_loss, target_2r
               FROM trade_setups
               WHERE trade_execution='Paper' AND status='Pending' AND outcome IS NULL
               ORDER BY created_date ASC"""
        ).fetchall()

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
            prices = conn.execute(
                """SELECT date, close FROM prices
                   WHERE symbol=? AND date > ?
                   ORDER BY date ASC""",
                (symbol, entry_date)
            ).fetchall()

        outcome = None
        actual_exit = None
        exit_date = None
        holding_days = None
        actual_pl_pct = None
        status = "Pending"

        for price_row in prices:
            close = float(price_row["close"])
            current_date = price_row["date"]

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
                conn.execute(
                    """UPDATE trade_setups
                       SET outcome=?, status=?, actual_exit=?,
                           exit_date=?, holding_days=?, actual_pl_pct=?
                       WHERE id=?""",
                    (outcome, status, actual_exit, exit_date, holding_days, actual_pl_pct, setup_id)
                )

    return results


# ---------------------------------------------------------------------------
# PostgreSQL override — runs LAST so PG functions replace SQLite ones
# when DATABASE_URL is available (Streamlit Cloud / GitHub Actions).
# ---------------------------------------------------------------------------
_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")

if _PG_URL:
    logger.info("DATABASE_URL detected — switching to PostgreSQL backend.")
    from database_pg import (           # noqa: F401  re-exports overwrite SQLite defs above
        get_conn,
        init_db,
        upsert_sectors,
        upsert_prices,
        upsert_index_prices,
        get_index_prices,
        get_all_symbols,
        get_all_sectors_df,
        get_prices_df,
        get_latest_scraped_date,
        get_price_date_range,
        get_sector_price_data,
        count_prices,
        count_sectors,
        save_trade_setup,
        get_trade_setups,
        update_trade_setup,
        activate_trade_setup,
        close_trade_setup,
        delete_trade_setup,
        setup_already_saved,
        get_backtest_summary,
        auto_save_setups,
        stm_pick_already_saved,
        auto_save_stm_picks,
        get_sim_portfolio_data,
        add_portfolio_transaction,
        get_portfolio_transactions,
        delete_portfolio_transaction,
        add_portfolio_value,
        get_portfolio_values,
        delete_portfolio_value,
        evaluate_paper_trades,
    )
