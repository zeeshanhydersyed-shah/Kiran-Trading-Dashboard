"""
Daily regime hook for the PSX pipeline.

append_latest_regime() is called from cmd_update() in main.py after
index_prices is updated. It pulls the full KSE-100 history, recomputes
indicators, and backfills every trading date since the last row written
to market_regime -- not just the single latest date.

Why "backfill every missing date" instead of just the latest one: this
hook is wrapped in its own try/except in main.py's cmd_update() so a
failure here can't take down the rest of the daily pipeline. Before this
fix, a transient failure on any one day (e.g. a Supabase connection
blip) meant that day's row was never written and never revisited -- the
next successful run just wrote whatever the new latest date was,
silently skipping the missed day forever. That happened for real on
2026-08-07 (see docs/KIRAN_CLEANUP_AUDIT.md): market_regime jumped
straight from 2026-08-06 to 2026-08-10 even though prices/index_prices
had 2026-08-07 the whole time, and the dashboard's "Market Regime"
widget stayed pinned to "as of 2026-08-06" until the next run happened
to succeed. stock_signals.py already backfills a date range this way;
this brings regime.py (and sector_signals.py) up to the same standard.
"""

import logging
import os
import sqlite3

import pandas as pd

DB = "psx_data.db"
logger = logging.getLogger(__name__)

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)

    df["ema_20"]  = df["close"].ewm(span=20,  adjust=False).mean()
    df["ema_50"]  = df["close"].ewm(span=50,  adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()

    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(
            r["high"] - r["low"],
            abs(r["high"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
            abs(r["low"]  - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
        ),
        axis=1,
    )
    df["atr_20"]  = df["tr"].rolling(20).mean()
    df["atr_pct"] = df["atr_20"] / df["close"] * 100
    df["return_20d"] = (df["close"] - df["close"].shift(20)) / df["close"].shift(20) * 100

    return df


def _classify(row: pd.Series, position_in_full_history: int) -> str:
    if position_in_full_history < 199:
        return "INSUFFICIENT_DATA"
    if pd.isna(row["return_20d"]) or pd.isna(row["atr_pct"]):
        return "INSUFFICIENT_DATA"

    e20, e50, e200 = row["ema_20"], row["ema_50"], row["ema_200"]
    c, r20, atr_pct = row["close"], row["return_20d"], row["atr_pct"]

    if e20 > e50 and e50 > e200 and c > e20 and r20 > 0:
        return "TRENDING_UP"
    if e20 < e50 and e50 < e200 and c < e20 and r20 < 0:
        return "TRENDING_DOWN"
    if atr_pct > 1.5:
        return "VOLATILE"
    return "RANGING"


def _pending_regime_rows(df: pd.DataFrame, total_rows: int, last_written_date, prev_regime, prev_days):
    """Pure generator: given the full, ascending, indicators-computed KSE-100
    dataframe and where market_regime currently leaves off, yields
    (date_str, row, regime, regime_days) for every date still needing a
    write, in chronological order, chaining regime_days across the run
    exactly as if each date had been written by its own successful daily run.

    No DB I/O here on purpose -- both backends share this, and it's directly
    unit-testable without a database.
    """
    pulled = len(df)
    for i in range(pulled):
        row = df.iloc[i]
        date_str = row["date"].strftime("%Y-%m-%d")
        if last_written_date is not None and date_str <= last_written_date:
            continue
        position = total_rows - pulled + i
        regime = _classify(row, position)
        regime_days = prev_days + 1 if prev_regime == regime else 1
        yield date_str, row, regime, regime_days
        prev_regime, prev_days = regime, regime_days


def append_latest_regime() -> None:
    if _PG_URL:
        _append_latest_regime_pg()
    else:
        _append_latest_regime_sqlite()


def _append_latest_regime_pg() -> None:
    from database_pg import (
        get_kse100_full_for_regime,
        get_latest_market_regime,
        get_latest_market_regime_date,
        write_market_regime,
    )

    kse_rows = get_kse100_full_for_regime()
    if not kse_rows:
        logger.warning("Regime hook (PG): no KSE-100 data found.")
        return

    df = pd.DataFrame(kse_rows)
    df["date"] = pd.to_datetime(df["date"])
    df["high"]  = df["high"].astype(float)
    df["low"]   = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df = _compute_indicators(df)
    total_rows = len(df)

    last_written_date = get_latest_market_regime_date()
    prev = get_latest_market_regime()
    prev_regime, prev_days = (prev[0], prev[1]) if prev else (None, 0)

    written = 0
    last_date = last_regime = last_days = None
    for date_str, row, regime, regime_days in _pending_regime_rows(
        df, total_rows, last_written_date, prev_regime, prev_days
    ):
        write_market_regime(
            date_str,
            float(row["close"]),
            float(row["ema_20"]),
            float(row["ema_50"]),
            float(row["ema_200"]),
            float(row["atr_20"])     if pd.notna(row["atr_20"])     else None,
            float(row["atr_pct"])    if pd.notna(row["atr_pct"])    else None,
            float(row["return_20d"]) if pd.notna(row["return_20d"]) else None,
            regime,
            regime_days,
        )
        written += 1
        last_date, last_regime, last_days = date_str, regime, regime_days

    if written == 0:
        logger.info("Regime hook (PG): already up to date at %s.", last_written_date)
    else:
        logger.info(
            "Regime backfilled (PG): %d date(s), through %s -> %s (day %d)",
            written, last_date, last_regime, last_days,
        )


def _append_latest_regime_sqlite() -> None:
    conn = sqlite3.connect(DB)
    try:
        df = pd.read_sql(
            """
            SELECT date, high, low, close
            FROM index_prices
            WHERE symbol = 'KSE-100'
            ORDER BY date
            """,
            conn,
        )
        if df.empty:
            logger.warning("Regime hook: no KSE-100 data found.")
            return

        df["date"] = pd.to_datetime(df["date"])
        df = _compute_indicators(df)
        total_rows = len(df)

        last_written_row = conn.execute("SELECT MAX(date) FROM market_regime").fetchone()
        last_written_date = last_written_row[0] if last_written_row else None

        prev_row = conn.execute(
            "SELECT regime, regime_days FROM market_regime ORDER BY date DESC LIMIT 1"
        ).fetchone()
        prev_regime, prev_days = (prev_row[0], prev_row[1]) if prev_row else (None, 0)

        written = 0
        last_date = last_regime = last_days = None
        for date_str, row, regime, regime_days in _pending_regime_rows(
            df, total_rows, last_written_date, prev_regime, prev_days
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO market_regime
                    (date, close, ema_20, ema_50, ema_200,
                     atr_20, atr_pct, return_20d, regime, regime_days, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    date_str,
                    float(row["close"]),
                    float(row["ema_20"]),
                    float(row["ema_50"]),
                    float(row["ema_200"]),
                    float(row["atr_20"])     if pd.notna(row["atr_20"])     else None,
                    float(row["atr_pct"])    if pd.notna(row["atr_pct"])    else None,
                    float(row["return_20d"]) if pd.notna(row["return_20d"]) else None,
                    regime,
                    regime_days,
                ),
            )
            written += 1
            last_date, last_regime, last_days = date_str, regime, regime_days
        conn.commit()

        if written == 0:
            logger.info("Regime hook: already up to date at %s.", last_written_date)
        else:
            logger.info(
                "Regime backfilled: %d date(s), through %s -> %s (day %d)",
                written, last_date, last_regime, last_days,
            )
    finally:
        conn.close()
