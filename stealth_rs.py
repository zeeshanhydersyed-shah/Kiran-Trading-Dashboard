"""
stealth_rs.py — Stealth Relative Strength, single locked source of truth.

Extracted from dashboard.py (2026-07-10) so the definition is computed
identically regardless of backend — compute_stealth_rs() branches
internally on _PG_URL (SQLite locally, Postgres on Cloud), both doing the
same live per-page-load query. No separate precomputed table or batch job:
Cloud follows exactly what local SQLite does, per explicit PI decision.
Locked definition from PRE_BREAKOUT_Specification_v1.0.md Section 12/13 —
do not modify or re-derive this here.

Status: DEAD on the locked confirmatory Validation+OOS test (Section 12.8-
12.13); a follow-up exploratory (non-confirmatory) re-test found the effect
recovers outside "runaway bull" regime (Section 13) — watch-only, not a
validated signal, not scheduled for re-test until fresh post-2026-07 data
accrues (PI target: year-end).

Deliberately NOT wired into leaders_scan.py, kiran_voice.py, or agent.py —
this module's only caller is dashboard.py's Explorer toggle. No scoring/
ranking logic here.
"""

import os
import sqlite3

import pandas as pd

_STEALTH_ADVERSE_THRESH = -1.5   # KSE-100 daily return <= this = adverse day
_STEALTH_WINDOW = 20             # trailing trading days, inclusive of today

_PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


def compute_stealth_rs(latest_date, symbols, db_path=None):
    """Live, point-in-time stealth count (as of latest_date only) per symbol.
    Branches on _PG_URL — SQLite locally, Postgres in production/Cloud."""
    if not symbols:
        return {}
    if _PG_URL:
        return _compute_stealth_rs_pg(latest_date, symbols)
    return _compute_stealth_rs_sqlite(latest_date, symbols, db_path)


def _compute_stealth_rs_sqlite(latest_date, symbols, db_path=None):
    if db_path is None:
        import config
        db_path = config.DB_PATH

    conn = sqlite3.connect(db_path)
    try:
        idx_df = pd.read_sql_query(
            "SELECT date, close FROM index_prices WHERE symbol='KSE-100' AND date <= ? "
            "ORDER BY date DESC LIMIT ?",
            conn, params=(latest_date, _STEALTH_WINDOW + 10),
        ).sort_values("date").reset_index(drop=True)
        idx_df["ret"] = idx_df["close"].pct_change() * 100
        window_dates = idx_df["date"].tolist()[-_STEALTH_WINDOW:]
        adverse_in_window = set(
            idx_df.loc[idx_df["ret"] < _STEALTH_ADVERSE_THRESH, "date"]
        ) & set(window_dates)

        if not adverse_in_window:
            return {s: 0 for s in symbols}

        placeholders = ",".join("?" for _ in symbols)
        lo_bound_date = idx_df["date"].iloc[0]  # covers the full fetched window

        prices = pd.read_sql_query(
            f"SELECT symbol, date, close FROM prices_adjusted "
            f"WHERE symbol IN ({placeholders}) AND date >= ? AND date <= ? "
            f"ORDER BY symbol, date",
            conn, params=list(symbols) + [lo_bound_date, latest_date],
        )

        adv_placeholders = ",".join("?" for _ in adverse_in_window)
        ss = pd.read_sql_query(
            f"SELECT symbol, date, avg_vol_10d FROM stock_signals "
            f"WHERE symbol IN ({placeholders}) AND date IN ({adv_placeholders})",
            conn, params=list(symbols) + list(adverse_in_window),
        )
    finally:
        conn.close()

    return _reduce_to_counts(prices, ss, adverse_in_window, latest_date, symbols)


def _compute_stealth_rs_pg(latest_date, symbols):
    """PG-backed equivalent — same logic, psycopg2 RealDictCursor + %s
    placeholders. latest_date/index dates are normalized to plain ISO
    strings throughout (index_prices/prices_adjusted/stock_signals.date are
    native DATE columns on Postgres; comparing/keying on plain strings keeps
    this identical in behavior to the SQLite path's string-keyed dates)."""
    import psycopg2.extras
    from database_pg import get_conn

    latest_date = str(latest_date)

    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            "SELECT date, close FROM index_prices WHERE symbol='KSE-100' AND date <= %s "
            "ORDER BY date DESC LIMIT %s",
            (latest_date, _STEALTH_WINDOW + 10),
        )
        idx_rows = cur.fetchall()
        if not idx_rows:
            return {s: 0 for s in symbols}
        idx_df = pd.DataFrame(idx_rows)
        idx_df["date"] = idx_df["date"].astype(str)
        idx_df = idx_df.sort_values("date").reset_index(drop=True)
        idx_df["ret"] = idx_df["close"].pct_change() * 100
        window_dates = idx_df["date"].tolist()[-_STEALTH_WINDOW:]
        adverse_in_window = set(
            idx_df.loc[idx_df["ret"] < _STEALTH_ADVERSE_THRESH, "date"]
        ) & set(window_dates)

        if not adverse_in_window:
            return {s: 0 for s in symbols}

        lo_bound_date = idx_df["date"].iloc[0]

        cur.execute(
            "SELECT symbol, date, close FROM prices_adjusted "
            "WHERE symbol = ANY(%s) AND date >= %s::date AND date <= %s::date "
            "ORDER BY symbol, date",
            (list(symbols), lo_bound_date, latest_date),
        )
        prices_rows = cur.fetchall()
        prices = pd.DataFrame(prices_rows)
        if not prices.empty:
            prices["date"] = prices["date"].astype(str)

        cur.execute(
            "SELECT symbol, date, avg_vol_10d FROM stock_signals "
            "WHERE symbol = ANY(%s) AND date = ANY(%s::date[])",
            (list(symbols), list(adverse_in_window)),
        )
        ss_rows = cur.fetchall()
        ss = pd.DataFrame(ss_rows)
        if not ss.empty:
            ss["date"] = ss["date"].astype(str)

    return _reduce_to_counts(prices, ss, adverse_in_window, latest_date, symbols)


def _reduce_to_counts(prices, ss, adverse_in_window, latest_date, symbols):
    """Shared reduction step — identical for both backends once prices/ss
    are plain DataFrames with string-typed 'date' columns."""
    if prices.empty:
        return {s: 0 for s in symbols}

    ss_lookup = {(r.symbol, r.date): r.avg_vol_10d for r in ss.itertuples()} if not ss.empty else {}

    counts = {}
    for sym, g in prices.groupby("symbol"):
        g = g.sort_values("date")
        g["ret"] = g["close"].pct_change() * 100
        g = g[g["date"] <= latest_date].tail(_STEALTH_WINDOW)
        cnt = 0
        for _, row in g.iterrows():
            d = row["date"]
            if d not in adverse_in_window:
                continue
            r = row["ret"]
            if r is None or pd.isna(r) or r < 0:
                continue
            av = ss_lookup.get((sym, d))
            if av is None or pd.isna(av):
                continue
            cnt += 1
        counts[sym] = cnt

    for s in symbols:
        counts.setdefault(s, 0)
    return counts
