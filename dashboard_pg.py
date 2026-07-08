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
  - E10.3 (7 functions below): none of these cast any date value to text
    either -- traced every "latest date" scalar each function returns and
    confirmed each one is either passed through fmt_date() or interpolated
    directly into an f-string (which calls str() on it implicitly, giving
    the same ISO-format result for a datetime.date as for a SQLite string).
    None of the DataFrames these functions return include a raw `date`
    column that reaches the UI. get_rotation_radar_data_pg() also replaces
    SQLite's date(?, '-N days') with `%s::date - INTERVAL 'N days'` and
    converts the SQLite named-parameter style (:price_date) to psycopg2's
    %(price_date)s -- genuine dialect differences the original Task 0 audit's
    grep missed (it only checked for julianday/printf/GROUP_CONCAT/
    datetime('now')/strftime, not SQLite's date() function).
  - E10.4 (Data Health page): get_dh_summary_pg()'s "Confirmed This Year"
    count cannot reuse the SQLite query's `confirmed_at >= ?` with a bare
    year string ("2026") -- corporate_action_suspects.confirmed_at is
    TIMESTAMP in Postgres (TEXT in SQLite), and Postgres rejects "2026" as
    an invalid timestamp literal. Verified live: fails with bare year,
    succeeds with "{year}-01-01". suspect_date/confirmed_at are cast to
    ::text in the DataFrame-returning queries to match the plain strings
    the SQLite path already produces (same convention as get_kv_latest_pg
    etc. above); close_before/close_after/drop_pct/adjustment_factor are
    coerced to float64 via _coerce_numeric for the same reason.
    mark_dh_false_positive_pg() / mark_dh_confirmed_pg()'s confirmed_at
    param is set from datetime.now().isoformat() by the caller -- its
    'T'-separated ISO 8601 format is accepted natively as a Postgres
    timestamp literal, no fix needed (unlike the bare-year case above).
    The Confirm button's rebuild_symbol_adjusted_pg() (the harder half of
    this stage -- a function signature change, not a dashboard query) lives
    in database_pg.py alongside its sibling append_new_prices_adjusted_pg /
    auto_detect_suspects_pg, not here -- see that file for its notes.
    recompute_symbol_signals() (stock_signals.py), also called by the
    Confirm button, is NOT ported here -- it's 100% SQLite-only with its
    own internal pipeline (_load_kse100, _process_trading_dates, etc.) and
    no Postgres port anywhere yet. dashboard.py isolates that call in its
    own try/except so a real, committed adjustment doesn't read as a
    failure just because the signal recompute can't run under Postgres.
"""

from datetime import datetime

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


# ── E10.3 PG siblings ────────────────────────────────────────────────────────

def get_market_gates_sectors_pg():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM sector_signals")
        latest = cur.fetchone()[0]
        cur.execute(
            """
            SELECT sector, rs_rank, rs_score_20, composite_score,
                   breadth_score, rs_inflection
            FROM sector_signals
            WHERE date = %s
              AND rs_rank IS NOT NULL
            ORDER BY rs_rank ASC
            """,
            (latest,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    sectors = pd.DataFrame(rows, columns=cols)
    return latest, sectors


def get_rotation_radar_data_pg():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT MAX(date) FROM sector_signals")
        latest_rr = cur.fetchone()[0]

        cur.execute(
            "SELECT MAX(date) FROM sector_signals WHERE flow_direction IS NOT NULL"
        )
        latest_flow = cur.fetchone()[0]

        cur.execute(
            """
            SELECT
                ss.sector,
                ss.rs_score_20, ss.rs_score_50, ss.rs_rank,
                ss.breadth_score, ss.adv_dec_ratio, ss.vol_ratio,
                ss.rs_inflection, ss.composite_score, ss.regime,
                ss.sector_stage, ss.sector_above_ema,
                ss.sector_ema_slope, ss.sector_pivot_dist_pct,
                COALESCE(sf.flow_direction,     NULL) AS flow_direction,
                COALESCE(sf.flow_smart_net_5d,  NULL) AS flow_smart_net_5d,
                COALESCE(sf.flow_smart_net_20d, NULL) AS flow_smart_net_20d
            FROM sector_signals ss
            LEFT JOIN sector_signals sf
                ON sf.sector = ss.sector
               AND sf.date   = %(flow_date)s
            WHERE ss.date = %(price_date)s
            ORDER BY ss.composite_score DESC
            """,
            {"price_date": latest_rr, "flow_date": latest_flow or latest_rr},
        )
        rr_rows = cur.fetchall()
        rr_cols = [d[0] for d in cur.description]

        # rr_hist: dead data (see module docstring) -- ported faithfully for
        # parity with the pre-extraction SQLite behavior, not because it's
        # displayed anywhere.
        cur.execute(
            """
            SELECT date, sector, rs_score_20, rs_rank
            FROM sector_signals
            WHERE date >= %s::date - INTERVAL '30 days'
            ORDER BY sector, date
            """,
            (latest_rr,),
        )
        hist_rows = cur.fetchall()
        hist_cols = [d[0] for d in cur.description]

        cur.execute(
            """
            SELECT sector, rs_rank as rank_10d
            FROM sector_signals
            WHERE date = (
                SELECT date FROM sector_signals
                WHERE date <= %s::date - INTERVAL '10 days'
                ORDER BY date DESC LIMIT 1
            )
            """,
            (latest_rr,),
        )
        rank_10d_rows = cur.fetchall()
        rank_10d_cols = [d[0] for d in cur.description]

    rr_df = pd.DataFrame(rr_rows, columns=rr_cols)
    rr_hist = pd.DataFrame(hist_rows, columns=hist_cols)
    rank_10d_ago = pd.DataFrame(rank_10d_rows, columns=rank_10d_cols)
    return latest_rr, latest_flow, rr_df, rr_hist, rank_10d_ago


def get_history_sector_ranks_pg():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM sector_signals")
        latest = cur.fetchone()[0]
        cur.execute(
            """
            SELECT sector, rs_rank, composite_score
            FROM sector_signals
            WHERE date = %s AND rs_rank IS NOT NULL
            ORDER BY rs_rank ASC
            """,
            (latest,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    ranks = pd.DataFrame(rows, columns=cols)
    return latest, ranks


def get_history_symbol_sectors_pg():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT symbol, sector FROM sectors WHERE sector IS NOT NULL")
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def get_regime_analysis_pg():
    sql = """
        WITH labeled AS (
            SELECT
                CASE
                    WHEN regime_at_entry = 'TRENDING_UP'
                         AND (days_since_last_transition IS NULL OR days_since_last_transition >= 6)
                         THEN 'Stable uptrend — favorable conditions'
                    WHEN regime_at_entry = 'TRENDING_UP'
                         AND days_since_last_transition BETWEEN 3 AND 5
                         THEN 'Uptrend settling — moderate caution'
                    WHEN regime_at_entry = 'TRENDING_UP'
                         AND days_since_last_transition <= 2
                         THEN 'Uptrend just started — proceed carefully'
                    WHEN regime_at_entry = 'VOLATILE'
                         THEN 'Choppy conditions — selective only'
                    WHEN regime_at_entry = 'RANGING'
                         THEN 'Narrow range — low activity expected'
                    WHEN regime_at_entry = 'TRENDING_DOWN'
                         THEN 'Down / Short setups only'
                END AS condition_label,
                outcome,
                actual_pl_pct,
                actual_pl_pkr
            FROM trade_setups
            WHERE source = 'Actual'
              AND outcome IN ('Win', 'Loss', 'Breakeven')
        )
        SELECT
            condition_label                                                              AS "Conditions",
            COUNT(*)                                                                     AS "Trades",
            SUM(CASE WHEN outcome = 'Win'  THEN 1 ELSE 0 END)                           AS "Wins",
            SUM(CASE WHEN outcome = 'Loss' THEN 1 ELSE 0 END)                           AS "Losses",
            ROUND(
                100.0 * SUM(CASE WHEN outcome = 'Win' THEN 1 ELSE 0 END)
                / NULLIF(SUM(CASE WHEN outcome IN ('Win','Loss') THEN 1 ELSE 0 END), 0),
                1
            )                                                                            AS "Win Rate %",
            ROUND(AVG(actual_pl_pct), 2)                                                AS "Avg Return %",
            ROUND(SUM(COALESCE(actual_pl_pkr, 0)), 0)                                   AS "Net PnL (PKR)"
        FROM labeled
        WHERE condition_label IS NOT NULL
        GROUP BY condition_label
        ORDER BY "Trades" DESC
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def get_regime_definitions_pg():
    sql = """
        WITH labeled AS (
            SELECT
                CASE
                    WHEN ts.regime_at_entry = 'TRENDING_UP'
                         AND (ts.days_since_last_transition IS NULL
                              OR ts.days_since_last_transition >= 6)
                         THEN 'Stable uptrend — favorable conditions'
                    WHEN ts.regime_at_entry = 'TRENDING_UP'
                         AND ts.days_since_last_transition BETWEEN 3 AND 5
                         THEN 'Uptrend settling — moderate caution'
                    WHEN ts.regime_at_entry = 'TRENDING_UP'
                         AND ts.days_since_last_transition <= 2
                         THEN 'Uptrend just started — proceed carefully'
                    WHEN ts.regime_at_entry = 'VOLATILE'
                         THEN 'Choppy conditions — selective only'
                    WHEN ts.regime_at_entry = 'RANGING'
                         THEN 'Narrow range — low activity expected'
                    WHEN ts.regime_at_entry = 'TRENDING_DOWN'
                         THEN 'Down / Short setups only'
                END                           AS condition_label,
                ts.regime_at_entry,
                ts.days_since_last_transition,
                mr.ema_20,
                mr.ema_50,
                mr.ema_200,
                mr.atr_pct,
                mr.return_20d
            FROM trade_setups ts
            LEFT JOIN market_regime mr ON ts.created_date = mr.date
            WHERE ts.source = 'Actual'
              AND ts.regime_at_entry IS NOT NULL
        )
        SELECT
            condition_label,
            regime_at_entry,
            MIN(CASE WHEN days_since_last_transition IS NOT NULL
                     THEN days_since_last_transition END)                AS min_days,
            MAX(days_since_last_transition)                               AS max_days,
            SUM(CASE WHEN days_since_last_transition IS NULL
                     THEN 1 ELSE 0 END)                                  AS null_days_n,
            ROUND(AVG(CASE WHEN ema_20 IS NOT NULL AND ema_50 IS NOT NULL
                           THEN (ema_20 - ema_50) / ema_50 * 100 END)::numeric, 2) AS avg_ema20_vs_50_pct,
            ROUND(AVG(CASE WHEN ema_50 IS NOT NULL AND ema_200 IS NOT NULL
                           THEN (ema_50 - ema_200) / ema_200 * 100 END)::numeric, 2) AS avg_ema50_vs_200_pct,
            ROUND(AVG(atr_pct),    2)                                    AS avg_atr_pct,
            ROUND(AVG(return_20d), 2)                                    AS avg_return_20d,
            COUNT(*)                                                      AS n
        FROM labeled
        WHERE condition_label IS NOT NULL
        GROUP BY condition_label, regime_at_entry
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def get_explorer_data_pg():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM stock_signals")
        latest = cur.fetchone()[0]

        cur.execute(
            """
            WITH date_5ago AS (
                SELECT date FROM sector_signals
                WHERE date < %s
                ORDER BY date DESC
                LIMIT 1 OFFSET 4
            ),
            sec_5d AS (
                SELECT sector, rs_rank AS rs_rank_5d
                FROM sector_signals
                WHERE date = (SELECT date FROM date_5ago)
            )
            SELECT ss.symbol, s.sector,
                   ss.rs_score_20, ss.rs_rank, ss.rs_rank_prev, ss.rank_change,
                   ss.sector_rs_rank, ss.base_tightness, ss.pivot_distance_pct,
                   ss.bos_flag, ss.avg_vol_10d, ss.vol_contraction, ss.pivot_high,
                   ss.stage2_bull,
                   ss.close_above_ema50, ss.ema50_slope_pos,
                   ss.close_above_ema150, ss.ema150_slope_pos,
                   ss.base_duration, ss.overhead_clear, ss.near_pivot_days,
                   p.close AS current_close,
                   sec.rs_rank              AS sec_global_rank,
                   sec.sector_stage         AS sec_stage,
                   sec.sector_above_ema     AS sec_above_ema,
                   sec.sector_ema_slope     AS sec_ema_slope,
                   sec.sector_pivot_dist_pct AS sec_pivot_dist,
                   sec.rs_inflection        AS sec_rs_inflection,
                   sec.sector_rs_new_high   AS sec_rs_new_high,
                   sec5.rs_rank_5d          AS sec_rs_rank_5d
            FROM stock_signals ss
            JOIN sectors s ON ss.symbol = s.symbol
            LEFT JOIN prices p
                ON p.symbol = ss.symbol AND p.date = ss.date
            LEFT JOIN sector_signals sec
                ON sec.date = ss.date AND sec.sector = s.sector
            LEFT JOIN sec_5d sec5 ON sec5.sector = s.sector
            WHERE ss.date = %s
            ORDER BY ss.rs_rank ASC
            """,
            (latest, latest),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    ex_df = pd.DataFrame(rows, columns=cols)
    return latest, ex_df


# ── E10.4: Data Health page ────────────────────────────────────────────────────

def get_dh_summary_pg() -> tuple[int, int, str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM corporate_action_suspects WHERE status = 'PENDING'"
        )
        pending = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM corporate_action_suspects "
            "WHERE status = 'CONFIRMED' AND confirmed_at >= %s",
            (f"{datetime.now().year}-01-01",),
        )
        confirmed = cur.fetchone()[0]

        cur.execute("SELECT MAX(suspect_date)::text FROM corporate_action_suspects")
        last_checked = cur.fetchone()[0] or "—"

    return pending, confirmed, last_checked


def get_dh_pending_df_pg() -> pd.DataFrame:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol, suspect_date::text AS suspect_date,
                   close_before, close_after, drop_pct, likely_category
            FROM corporate_action_suspects
            WHERE status = 'PENDING'
            ORDER BY suspect_date DESC
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    df = pd.DataFrame(rows, columns=cols)
    df = _coerce_numeric(df, ["close_before", "close_after", "drop_pct"])
    return df


def get_dh_history_df_pg() -> pd.DataFrame:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, suspect_date::text AS suspect_date, drop_pct, likely_category,
                   confirmed_action, adjustment_factor, confirmed_at::text AS confirmed_at, status
            FROM corporate_action_suspects
            WHERE status IN ('CONFIRMED', 'FALSE_POSITIVE')
            ORDER BY confirmed_at DESC
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    df = pd.DataFrame(rows, columns=cols)
    df = _coerce_numeric(df, ["drop_pct", "adjustment_factor"])
    return df


def mark_dh_false_positive_pg(symbol: str, ex_date: str, confirmed_at: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE corporate_action_suspects
                SET status = 'FALSE_POSITIVE',
                    confirmed_at = %s
                WHERE symbol = %s AND suspect_date = %s
            """, (confirmed_at, symbol, ex_date))


def mark_dh_confirmed_pg(symbol: str, ex_date: str, action: str,
                          factor: float, confirmed_at: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE corporate_action_suspects
                SET status = 'CONFIRMED',
                    confirmed_action = %s,
                    adjustment_factor = %s,
                    confirmed_at = %s
                WHERE symbol = %s AND suspect_date = %s
            """, (action, factor, confirmed_at, symbol, ex_date))
