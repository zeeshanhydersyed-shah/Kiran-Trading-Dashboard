"""
PostgreSQL read functions for dashboard.py's E10.1-ported connection sites.

Separate from database_pg.py by deliberate decision -- that file is already
overgrown and due its own cleanup pass later. This file holds only
dashboard-specific reads, imports database_pg.get_conn() for the actual
connection mechanics (single source of truth for URL parsing), and follows
the same _pg-suffixed naming / %s-placeholder convention.

Each function here is a drop-in replacement for the matching SQLite block in
dashboard.py, with one deliberate difference where the SQLite path's output
shape must be matched exactly to avoid breaking untouched downstream code:

  - get_kv_latest_pg(): casts ts/market_date to text. dashboard.py's consumer
    does `_kv_row["ts"][:16]` string slicing -- would raise TypeError on a
    native datetime.datetime object.
  - get_recovery_signals_pg() / get_portfolio_signals_pg(): casts
    MAX(as_of_date) to text (consumers compare it against a plain
    date.today().isoformat() string with `!=` -- comparing a date object to
    a string never raises, it's just always True, so the staleness warning
    would silently show every render) and coerces known NUMERIC-typed
    columns to float64 (consumers call .mean()/.sum() directly on them,
    e.g. move_pct, without the explicit float() guard the setup_log-reading
    functions below already have).
  - get_regime_status_pg() (E10.2): deliberately does NOT cast `date` to
    text -- verified (not assumed) that both dashboard.py call sites pass
    the returned date through fmt_date(), which wraps its argument in
    str(d) before parsing, so a native datetime.date round-trips exactly
    like a SQLite string. No other code path touches this value.
"""

import pandas as pd

from database_pg import get_conn


def get_corporate_action_count_pg() -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM corporate_action_suspects WHERE status = 'PENDING'"
        )
        return cur.fetchone()[0]


def get_kv_latest_pg() -> dict | None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ts::text, market_date::text, trigger_type, stance, response "
            "FROM agent_memory ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    if not row:
        return None
    cols = ["ts", "market_date", "trigger_type", "stance", "response"]
    return dict(zip(cols, row))


def get_sh_filter_opts_pg() -> tuple[list, list]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT regime FROM setup_log "
            "WHERE regime IS NOT NULL ORDER BY regime"
        )
        regimes = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT sector FROM setup_log "
            "WHERE sector IS NOT NULL ORDER BY sector"
        )
        sectors = [r[0] for r in cur.fetchall()]
    return regimes, sectors


def get_sh_perf_pg(regime, sector, setup_type) -> list:
    q = """
        SELECT
            setup_type, regime, sector,
            COUNT(*) AS total,
            SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END) AS winners,
            SUM(CASE WHEN outcome_label='LOSER'  THEN 1 ELSE 0 END) AS losers,
            SUM(CASE WHEN outcome_label='BREAKEVEN' THEN 1 ELSE 0 END) AS breakevens,
            ROUND(AVG(fwd_return_5d), 2)  AS avg_5d,
            ROUND(AVG(fwd_return_10d), 2) AS avg_10d,
            ROUND(AVG(fwd_return_20d), 2) AS avg_20d,
            ROUND(
                SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END)
                * 100.0 / COUNT(*), 1
            ) AS win_pct
        FROM setup_log
        WHERE outcome_label IS NOT NULL
    """
    params = []
    if regime != 'All':
        q += " AND regime = %s"
        params.append(regime)
    if sector != 'All':
        q += " AND sector = %s"
        params.append(sector)
    if setup_type != 'All':
        q += " AND setup_type = %s"
        params.append(setup_type)
    q += " GROUP BY setup_type, regime, sector ORDER BY win_pct DESC"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        return cur.fetchall()


def get_sh_symbol_pg(symbol) -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_appearances,
                SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END) AS winners,
                SUM(CASE WHEN outcome_label='LOSER'  THEN 1 ELSE 0 END) AS losers,
                SUM(CASE WHEN outcome_label='BREAKEVEN' THEN 1 ELSE 0 END) AS breakevens,
                ROUND(AVG(fwd_return_10d), 2) AS avg_10d,
                ROUND(
                    SUM(CASE WHEN outcome_label='WINNER' THEN 1 ELSE 0 END)
                    * 100.0 /
                    NULLIF(COUNT(CASE WHEN outcome_label IS NOT NULL THEN 1 END), 0),
                    1
                ) AS win_pct
            FROM setup_log
            WHERE symbol = %s AND outcome_label IS NOT NULL
            """,
            (symbol,)
        )
        summary = cur.fetchone()
        cur.execute(
            """
            SELECT
                setup_date, setup_type, regime, sector,
                rs_rank, sector_rs_rank, rank_change,
                rs_score_20, base_tightness, pivot_distance_pct,
                bos_flag, fwd_return_5d, fwd_return_10d,
                fwd_return_20d, outcome_label
            FROM setup_log
            WHERE symbol = %s
            ORDER BY setup_date DESC
            LIMIT 500
            """,
            (symbol,)
        )
        rows = cur.fetchall()
    return summary, rows


def _coerce_numeric(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """Force known NUMERIC/DECIMAL-typed Postgres columns to float64, matching
    the dtype SQLite would already produce natively. NULLs correctly become
    NaN (errors='coerce' only affects genuinely non-numeric values, not
    None -- pd.to_numeric maps None/NULL to NaN without raising)."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


_RECOVERY_NUMERIC_COLS = [
    "close", "drawdown_pct", "base_range_pct", "vol_ratio_today",
    "base_high", "dist_pct", "trigger_close", "current_close",
    "move_pct", "pre_high",
]

_PORTFOLIO_NUMERIC_COLS = ["latest_close", "dist_from_30w_pct", "composite_score"]


def get_recovery_signals_pg() -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(as_of_date)::text FROM recovery_signals")
        latest = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM recovery_signals WHERE as_of_date = %s", (latest,)
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    df = _coerce_numeric(df, _RECOVERY_NUMERIC_COLS)
    return df, latest


def get_portfolio_signals_pg() -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(as_of_date)::text FROM portfolio_signals")
        latest = cur.fetchone()[0]
        cur.execute(
            "SELECT * FROM portfolio_signals WHERE as_of_date = %s ORDER BY rank",
            (latest,)
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    df = _coerce_numeric(df, _PORTFOLIO_NUMERIC_COLS)
    return df, latest


def get_regime_status_pg() -> tuple | None:
    """PG sibling of dashboard.py's _get_regime_status() (E10.2 merge).
    Returns (current_regime, latest_date, days_since) or None.

    Deliberately recomputes from full history rather than reading
    market_regime.regime_days -- that column is currently non-idempotent
    across same-date re-runs (confirmed ~2x inflated on both Supabase and
    local) and must not be trusted until regime.py's increment logic is
    fixed separately.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT date, regime FROM market_regime ORDER BY date")
        rows = cur.fetchall()

    if not rows:
        return None

    dates   = [r[0] for r in rows]
    regimes = [r[1] for r in rows]
    last_transition_idx = None
    for i in range(len(regimes) - 1, 0, -1):
        if regimes[i] != regimes[i - 1]:
            last_transition_idx = i
            break
    days_since = (
        len(dates) - 1 - last_transition_idx
        if last_transition_idx is not None else len(dates) - 1
    )
    return regimes[-1], dates[-1], days_since
