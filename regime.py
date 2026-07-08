"""
Daily regime hook for the PSX pipeline.

append_latest_regime() is called from cmd_update() in main.py after
index_prices is updated. It pulls the last 250 rows of KSE-100 (enough
for EWM warm-up), recomputes indicators, and upserts a single row for
the latest date into market_regime.
"""

import logging
import os
import sqlite3

import pandas as pd

DB = "psx_data.db"
logger = logging.getLogger(__name__)

WARMUP = 250  # rows pulled for EWM warm-up; only the last row is written

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


def append_latest_regime() -> None:
    if _PG_URL:
        _append_latest_regime_pg()
    else:
        _append_latest_regime_sqlite()


def _append_latest_regime_pg() -> None:
    from database_pg import get_kse100_for_regime, get_latest_market_regime, write_market_regime

    total_rows, kse_rows = get_kse100_for_regime(WARMUP)
    if not kse_rows:
        logger.warning("Regime hook (PG): no KSE-100 data found.")
        return

    df = pd.DataFrame(kse_rows)
    df["date"] = pd.to_datetime(df["date"])
    df["high"]  = df["high"].astype(float)
    df["low"]   = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df = _compute_indicators(df)

    row = df.iloc[-1]
    date_str = row["date"].strftime("%Y-%m-%d")

    position = total_rows - 1
    regime = _classify(row, position)

    prev = get_latest_market_regime()
    if prev and prev[0] == regime:
        regime_days = prev[1] + 1
    else:
        regime_days = 1

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
    logger.info("Regime logged (PG): %s -> %s (day %d)", date_str, regime, regime_days)


def _append_latest_regime_sqlite() -> None:
    conn = sqlite3.connect(DB)
    try:
        # Total KSE-100 rows — needed to determine whether we're still in
        # the INSUFFICIENT_DATA warmup period relative to full history.
        total_rows = conn.execute(
            "SELECT COUNT(*) FROM index_prices WHERE symbol = 'KSE-100'"
        ).fetchone()[0]

        # Pull last WARMUP rows for indicator computation
        df = pd.read_sql(
            f"""
            SELECT date, high, low, close
            FROM index_prices
            WHERE symbol = 'KSE-100'
            ORDER BY date DESC
            LIMIT {WARMUP}
            """,
            conn,
        )
        if df.empty:
            logger.warning("Regime hook: no KSE-100 data found.")
            return

        df["date"] = pd.to_datetime(df["date"])
        df = _compute_indicators(df)

        row = df.iloc[-1]
        date_str = row["date"].strftime("%Y-%m-%d")

        # position_in_full_history: index of this row across the entire history
        position = total_rows - 1
        regime = _classify(row, position)

        # regime_days: look up the previous row in market_regime and continue
        # the streak if the regime matches, else start at 1.
        prev = conn.execute(
            "SELECT regime, regime_days FROM market_regime ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if prev and prev[0] == regime:
            regime_days = prev[1] + 1
        else:
            regime_days = 1

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
        conn.commit()
        logger.info("Regime logged: %s -> %s (day %d)", date_str, regime, regime_days)

    finally:
        conn.close()
