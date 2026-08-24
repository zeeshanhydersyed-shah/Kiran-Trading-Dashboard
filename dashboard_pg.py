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
    recompute_symbol_signals() (stock_signals.py), also needed by the
    Confirm button, is NOT ported here -- it's 100% SQLite-only with its
    own internal pipeline (_load_kse100, _process_trading_dates, etc.) and
    no Postgres port anywhere yet. Rather than let the button run a partial
    write (fix prices_adjusted, leave stock_signals stale indefinitely --
    the nightly pipeline never revisits historical stock_signals rows),
    dashboard.py hard-blocks Confirm entirely under _PG_URL and calls
    neither this function nor rebuild_symbol_adjusted_pg. See CLAUDE.md
    "Known Gaps: Postgres parity" for the full writeup. mark_dh_confirmed_pg
    below is untouched and tested, ready for when that gap closes.
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
    Returns (current_regime, latest_date, days_since, has_gap) or None.

    Deliberately recomputes from full history rather than reading
    market_regime.regime_days -- that column is currently non-idempotent
    across same-date re-runs (confirmed ~2x inflated on both Supabase and
    local) and must not be trusted until regime.py's increment logic is
    fixed separately.

    has_gap (added 2026-08-12): True if market_regime is missing one or
    more KSE-100 trading dates between the detected transition and the
    latest date. When True, days_since should not be trusted as exact --
    the transition it's counted from might not even be the real most
    recent one, if an undetected regime change is sitting inside the gap.
    This isn't hypothetical: backfilling a real gap on 2026-08-07 found a
    genuine one-day VOLATILE dip inside what otherwise looked like an
    unbroken TRENDING_UP streak (see docs/KIRAN_CLEANUP_AUDIT.md) -- days
    since the true (corrected) transition can end up smaller, larger, or
    coincidentally the same as the ungapped reading, so there's no single
    direction to "correct" for. Deliberately does NOT try to derive a
    better number from index_prices' trading-day count instead -- that
    would just trade one confidently-wrong number for a different one.
    Surfacing the uncertainty is the honest fix; regime.py's backfill (or
    a one-off historical repair) is what actually resolves it.
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
        transition_date = dates[last_transition_idx] if last_transition_idx is not None else dates[0]
        latest_date = dates[-1]

        cur.execute(
            "SELECT COUNT(*) FROM index_prices "
            "WHERE symbol = 'KSE-100' AND date > %s AND date <= %s",
            (transition_date, latest_date),
        )
        trading_days_in_window = cur.fetchone()[0]

    has_gap = trading_days_in_window > days_since
    return regimes[-1], latest_date, days_since, has_gap


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
            """
            SELECT
                ss.sector,
                ss.rs_score_20, ss.rs_score_50, ss.rs_rank,
                ss.breadth_score, ss.adv_dec_ratio, ss.vol_ratio,
                ss.rs_inflection, ss.composite_score, ss.regime,
                ss.sector_stage, ss.sector_above_ema,
                ss.sector_ema_slope, ss.sector_pivot_dist_pct
            FROM sector_signals ss
            WHERE ss.date = %(price_date)s
            ORDER BY ss.composite_score DESC
            """,
            {"price_date": latest_rr},
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
    return latest_rr, rr_df, rr_hist, rank_10d_ago


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

        # Heartbeat, not MAX(suspect_date) -- see the SQLite sibling in
        # dashboard.py for why that query could not detect a dead checker.
        #
        # TR-06 Tier 2 (2026-08-24): see dashboard.py's identical comment --
        # corporate_action_suspects_scan is the correct successor for this
        # specifically scan-focused "Last Checked" metric, not
        # corporate_action_append.
        try:
            cur.execute(
                "SELECT run_date, status FROM pipeline_runs "
                "WHERE hook_name = 'corporate_action_suspects_scan' "
                "ORDER BY run_date DESC LIMIT 1"
            )
            row = cur.fetchone()
            last_checked = (
                (row[0] if row[1] == "ok" else f"{row[0]} (failed)") if row else "never run"
            )
        except Exception:
            conn.rollback()
            last_checked = "never run"

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
    """Tested and correct, but NOT currently called by dashboard.py -- the
    Confirm button hard-blocks under _PG_URL instead. See module docstring
    above / CLAUDE.md "Known Gaps: Postgres parity" for why."""
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


# ── E10.5 batch A: Leaders page, RS Leaders tab ─────────────────────────────
# rs_score_20/rs_score_50 are NUMERIC in Postgres (confirmed live against
# information_schema.columns) -- coerced via _coerce_numeric to match the
# float64 dtype SQLite already produces, same convention as
# get_recovery_signals_pg() above. rs_rank/rank_change/sector_rs_rank are
# native integer and avg_vol_10d is double precision -- no coercion needed.
# `latest` is not cast to text: its only consumer is an f-string
# interpolation (str() implicit), same no-cast case as the E10.3 functions.

_LEADERS_RS_NUMERIC_COLS = ["rs_score_20", "rs_score_50"]


def get_leaders_rs_data_pg() -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM stock_signals")
        latest = cur.fetchone()[0]
        cur.execute(
            """
            SELECT ss.symbol, sm.sector,
                   ss.rs_score_20, ss.rs_score_50,
                   ss.rs_rank, ss.rank_change, ss.sector_rs_rank,
                   ss.avg_vol_10d
            FROM stock_signals ss
            JOIN stock_metadata sm ON ss.symbol = sm.symbol
            WHERE ss.date = %s
              AND ss.avg_vol_10d > 200000
              AND ss.rs_rank IS NOT NULL
            ORDER BY ss.rs_rank ASC
            """,
            (latest,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    df = _coerce_numeric(df, _LEADERS_RS_NUMERIC_COLS)
    return latest, df


# ── E10.5 batch B: Leaders page, Unified Watchlist tab ──────────────────────
# Three confirmed bugs fixed together here, per Task 0's audit and the live
# tests run before writing this function:
#   1. N+1: the SQLite path's per-symbol 3-query loop (3 x N_breakout_rows
#      queries) is collapsed into one CTE query that computes every BREAKOUT
#      symbol's streak-start date at once, using the same two-step "last
#      non-breakout date, then earliest breakout date after it" logic.
#      Verified byte-for-byte identical to the old loop's output against
#      local SQLite (21/21 BREAKOUT symbols matched).
#   2. boolean: stock_signals.bos_flag is a native boolean column in
#      Postgres (confirmed live) -- `bos_flag = 0/1` raises
#      "operator does not exist: boolean = integer" (reproduced live).
#      Fixed with `bos_flag = FALSE/TRUE`.
#   3. datetime.date vs str: stock_signals.date is `date` in Postgres but
#      leaders_scan.scan_date is `text` -- without a cast, breakout_date
#      comes back as datetime.date while scan_date is str, so
#      `_uw_status()`'s `breakout_date == scan_date` check is always False
#      (reproduced live: 0 "BROKE OUT TODAY" matches with real ones
#      present). Fixed with `MIN(ss.date)::text`, matching the str dtype
#      SQLite's TEXT date column already produces -- confirmed live this
#      produces the correct non-zero match count (7/40) and requires no
#      change to _uw_status() itself, which stays identical across backends.
# rs_score_20/base_tightness/pivot_high/pivot_distance_pct/vol_ratio_today/
# entry_trigger/stop_loss/sl_pct are NUMERIC in Postgres (confirmed live);
# avg_vol_10d/vol_contraction are double precision and sector_rank/rs_rank/
# final_score are integer -- no coercion needed for those.

_LEADERS_UNIFIED_NUMERIC_COLS = [
    "rs_score_20", "base_tightness", "pivot_high", "pivot_distance_pct",
    "vol_ratio_today", "entry_trigger", "stop_loss", "sl_pct",
]


def get_leaders_unified_data_pg() -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(scan_date) FROM leaders_scan")
        scan_date = cur.fetchone()[0]
        if not scan_date:
            return scan_date, pd.DataFrame(), {}

        cur.execute(
            """
            SELECT ls.symbol, ls.setup_type, ls.sector, ls.sector_rank,
                   ls.rs_rank, ls.rs_score_20, ls.avg_vol_10d,
                   ls.base_tightness, ls.pivot_high, ls.pivot_distance_pct,
                   ls.vol_ratio_today, ls.vol_contraction, ls.final_score, ls.flag,
                   ls.entry_trigger, ls.stop_loss, ls.sl_pct
            FROM leaders_scan ls
            WHERE ls.scan_date = %s
            ORDER BY ls.setup_type DESC, ls.final_score DESC
            """,
            (scan_date,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(rows, columns=cols)
        df = _coerce_numeric(df, _LEADERS_UNIFIED_NUMERIC_COLS)

        cur.execute(
            """
            WITH bo_symbols AS (
                SELECT symbol FROM leaders_scan
                WHERE scan_date = %s AND setup_type = 'BREAKOUT'
            ),
            last_zero AS (
                SELECT ss.symbol, MAX(ss.date) AS last_zero_date
                FROM stock_signals ss
                WHERE ss.symbol IN (SELECT symbol FROM bo_symbols)
                  AND ss.bos_flag = FALSE
                  AND ss.date <= %s
                GROUP BY ss.symbol
            )
            SELECT b.symbol, MIN(ss.date)::text AS breakout_date
            FROM bo_symbols b
            LEFT JOIN last_zero lz ON lz.symbol = b.symbol
            JOIN stock_signals ss
                ON ss.symbol = b.symbol
               AND ss.bos_flag = TRUE
               AND (lz.last_zero_date IS NULL OR ss.date > lz.last_zero_date)
            GROUP BY b.symbol
            """,
            (scan_date, scan_date),
        )
        bo_dates = dict(cur.fetchall())

    return scan_date, df, bo_dates


# ── E10.5 batch C: Leaders page, Deep Scan tab ──────────────────────────────
# Two confirmed bugs fixed, per Task 0's audit and the live tests run before
# writing this function:
#   1. date/text JOIN: sector_signals.date is `date` but
#      leaders_top_picks.scan_date is `text` -- `sec.date = lp.scan_date`
#      raises "operator does not exist: date = text" (reproduced live).
#      Fixed by casting the text side: `sec.date = lp.scan_date::date`.
#   2. SQLite dialect: `date('now', '-10 days')` doesn't exist in Postgres.
#      Replaced with `(CURRENT_DATE - INTERVAL '10 days')::date::text` --
#      the extra ::date strips the time component INTERVAL subtraction adds
#      (confirmed live: without it you get a timestamp-with-time string,
#      which still happens to compare correctly against plain-date text
#      values due to lexicographic prefix ordering, but that's fragile, not
#      a real fix -- the explicit ::date makes the cutoff an actual
#      'YYYY-MM-DD' string matching what scan_date (text) already holds).
# entry_trigger/stop_loss/sl_pct/vol_ratio_today (leaders_top_picks),
# rs_score_20/rs_score_50/base_tightness/nearest_overhead_pct/
# pivot_distance_pct (leaders_scan), and breadth_score (sector_signals) are
# all NUMERIC in Postgres (confirmed live) -- coerced via _coerce_numeric.
# fwd_return_5d/10d/20d (leaders_top_picks) are also NUMERIC -- same
# treatment for the audit query. avg_vol_10d is double precision;
# rank/sector_rank/rank_change/rs_inflection/vol_rejection_flag/
# final_score/triggered are all integer -- none of those need coercion.

_LEADERS_DEEPSCAN_PICKS_NUMERIC_COLS = [
    "entry_trigger", "stop_loss", "sl_pct", "vol_ratio_today",
    "rs_score_20", "rs_score_50", "base_tightness", "nearest_overhead_pct",
    "pivot_distance_pct", "breadth_score",
]

_LEADERS_DEEPSCAN_AUDIT_NUMERIC_COLS = [
    "entry_trigger", "sl_pct", "fwd_return_5d", "fwd_return_10d", "fwd_return_20d",
]


def get_leaders_deepscan_data_pg() -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(scan_date) FROM leaders_scan")
        scan_date = cur.fetchone()[0]
        if not scan_date:
            return scan_date, pd.DataFrame(), pd.DataFrame()

        cur.execute(
            """
            SELECT lp.rank, lp.setup_type, lp.symbol, lp.sector, lp.sector_rank,
                   lp.entry_trigger, lp.stop_loss, lp.sl_pct,
                   lp.vol_ratio_today, lp.key_reason, lp.flag,
                   ls.rs_score_20, ls.rs_score_50, ls.rank_change,
                   ls.base_tightness, ls.rs_inflection, ls.vol_rejection_flag,
                   ls.nearest_overhead_pct, ls.avg_vol_10d,
                   ls.pivot_distance_pct, ls.final_score,
                   sec.breadth_score
            FROM leaders_top_picks lp
            JOIN leaders_scan ls
                ON ls.scan_date = lp.scan_date
               AND ls.setup_type = lp.setup_type
               AND ls.symbol = lp.symbol
            LEFT JOIN sector_signals sec
                ON sec.sector = lp.sector AND sec.date = lp.scan_date::date
            WHERE lp.scan_date = %s
            ORDER BY lp.setup_type DESC, lp.rank ASC
            """,
            (scan_date,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        picks_df = pd.DataFrame(rows, columns=cols)
        picks_df = _coerce_numeric(picks_df, _LEADERS_DEEPSCAN_PICKS_NUMERIC_COLS)

        cur.execute(
            """
            SELECT scan_date, setup_type, rank, symbol, sector,
                   entry_trigger, sl_pct,
                   triggered, trigger_date,
                   fwd_return_5d, fwd_return_10d, fwd_return_20d,
                   outcome_label, key_reason, flag
            FROM leaders_top_picks
            WHERE scan_date <= (CURRENT_DATE - INTERVAL '10 days')::date::text
            ORDER BY scan_date DESC, setup_type, rank
            """
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        audit_df = pd.DataFrame(rows, columns=cols)
        audit_df = _coerce_numeric(audit_df, _LEADERS_DEEPSCAN_AUDIT_NUMERIC_COLS)

    return scan_date, picks_df, audit_df


# ── E10.5 batch D: Leaders page, Radar tab (minus _rd_trajectory) ───────────
# Same date/text JOIN bug as batch C, same fix, applied at all three sites
# in this batch that join sector_signals to a leaders_scan/leaders_top_picks
# scan_date column: sector_signals.date is `date`, leaders_scan.scan_date
# and leaders_top_picks.scan_date are both `text` (confirmed live) --
# `sec.date = ls.scan_date` / `sec.date = lp.scan_date` raise "operator
# does not exist: date = text". Fixed the same way, same direction, at all
# three sites: cast the text side (`::date`), not the date side -- kept
# consistent with batch C's get_leaders_deepscan_data_pg() rather than
# drifting to a different cast direction site to site.
# _rd_trajectory() itself (its own raw-cursor 30-day-history query, and the
# Decimal/float64 arithmetic bug inside it) is NOT touched here -- that's
# batch E, reviewed on its own as planned. sec_rows_df's `composite` column
# (sector_signals.composite_score) is still coerced to float64 below like
# every other NUMERIC column in this batch, since that's the correct
# foundation for batch E to build on -- but note this means the interim
# state between batch D and E has _rd_trajectory() CRASHING under _PG_URL,
# not degrading gracefully: verified live (sqlite3.connect() against a
# fresh/nonexistent path, same shape _ld_conn would have on Streamlit
# Cloud) that the query inside it raises
# "sqlite3.OperationalError: no such table: sector_signals" uncaught --
# there's no try/except around _ld_conn.execute() there, only
# `if not hist: return "—"` for the empty-*result* case, which is never
# reached because the exception fires first. This crashes the Step 2
# render (the .apply(_rd_trajectory, ...) call), not just the Trajectory
# column, until batch E ports that function too. Not a blocker for this
# batch -- nothing is deployed to Streamlit Cloud yet, E10 finishes before
# deployment starts -- but the fix lands in batch E, not here.
# rs_score_20/rs_score_50/base_tightness/pivot_distance_pct/pivot_high/
# vol_ratio_today/nearest_overhead_pct/entry_trigger/stop_loss/sl_pct
# (leaders_scan) and breadth_score/composite_score (sector_signals) are all
# NUMERIC in Postgres (confirmed live) -- coerced via _coerce_numeric.
# avg_vol_10d/sector_composite are double precision; sector_rank/rs_rank/
# sector_rs_rank/rank_change/vol_rejection_flag/rs_inflection/raw_score/
# penalty/final_score are integer, and RANK() OVER's rank_today is bigint
# -- none of those need coercion.

_LEADERS_RADAR_CANDS_NUMERIC_COLS = [
    "rs_score_20", "rs_score_50", "base_tightness", "pivot_distance_pct",
    "pivot_high", "vol_ratio_today", "nearest_overhead_pct",
    "entry_trigger", "stop_loss", "sl_pct", "breadth_score",
]

_LEADERS_RADAR_SEC_ROWS_NUMERIC_COLS = ["composite", "breadth_score"]

_LEADERS_RADAR_TOP_PICKS_NUMERIC_COLS = _LEADERS_DEEPSCAN_PICKS_NUMERIC_COLS


def get_leaders_radar_data_pg() -> tuple:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(scan_date) FROM leaders_scan")
        rd_date = cur.fetchone()[0]
        if not rd_date:
            return rd_date, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        cur.execute(
            """
            SELECT ls.symbol, ls.sector, ls.sector_rank, ls.rs_rank,
                   ls.sector_rs_rank, ls.rs_score_20, ls.rs_score_50,
                   ls.rank_change, ls.avg_vol_10d, ls.base_tightness,
                   ls.pivot_distance_pct, ls.pivot_high, ls.vol_ratio_today,
                   ls.vol_rejection_flag, ls.rs_inflection, ls.nearest_overhead_pct,
                   ls.sector_composite, ls.raw_score, ls.penalty, ls.final_score,
                   ls.flag, ls.entry_trigger, ls.stop_loss, ls.sl_pct,
                   sec.breadth_score, sec.regime
            FROM leaders_scan ls
            LEFT JOIN sector_signals sec
                ON sec.sector = ls.sector AND sec.date = ls.scan_date::date
            WHERE ls.scan_date = %s AND ls.setup_type = 'PRE_BREAKOUT'
            ORDER BY ls.final_score DESC
            """,
            (rd_date,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        cands_df = pd.DataFrame(rows, columns=cols)
        cands_df = _coerce_numeric(cands_df, _LEADERS_RADAR_CANDS_NUMERIC_COLS)

        cur.execute(
            """
            SELECT ls.symbol, ls.sector, ls.sector_rank, ls.rs_rank,
                   ls.rs_score_20, ls.rs_score_50, ls.rank_change,
                   ls.avg_vol_10d, ls.base_tightness, ls.pivot_distance_pct,
                   ls.pivot_high, ls.vol_ratio_today, ls.vol_rejection_flag,
                   ls.rs_inflection, ls.nearest_overhead_pct,
                   ls.sector_composite, ls.final_score, ls.flag,
                   ls.entry_trigger, ls.stop_loss, ls.sl_pct,
                   sec.breadth_score, sec.regime
            FROM leaders_scan ls
            LEFT JOIN sector_signals sec
                ON sec.sector = ls.sector AND sec.date = ls.scan_date::date
            WHERE ls.scan_date = %s AND ls.setup_type = 'BREAKOUT'
            ORDER BY ls.final_score DESC
            """,
            (rd_date,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        bos_df = pd.DataFrame(rows, columns=cols)
        bos_df = _coerce_numeric(bos_df, _LEADERS_RADAR_CANDS_NUMERIC_COLS)

        cur.execute(
            """
            SELECT ss.sector, ss.composite_score AS composite, ss.breadth_score, ss.rs_rank,
                   ss.rs_inflection, ss.regime,
                   RANK() OVER (ORDER BY ss.composite_score DESC) AS rank_today
            FROM sector_signals ss
            WHERE ss.date = %s
            ORDER BY rank_today
            """,
            (rd_date,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        sec_rows_df = pd.DataFrame(rows, columns=cols)
        sec_rows_df = _coerce_numeric(sec_rows_df, _LEADERS_RADAR_SEC_ROWS_NUMERIC_COLS)

        cur.execute(
            """
            SELECT lp.rank, lp.setup_type, lp.symbol, lp.sector, lp.sector_rank,
                   lp.entry_trigger, lp.stop_loss, lp.sl_pct,
                   lp.vol_ratio_today, lp.key_reason, lp.flag,
                   ls.rs_score_20, ls.rs_score_50, ls.rank_change,
                   ls.base_tightness, ls.rs_inflection, ls.vol_rejection_flag,
                   ls.nearest_overhead_pct, ls.avg_vol_10d,
                   ls.pivot_distance_pct, ls.final_score,
                   sec.breadth_score
            FROM leaders_top_picks lp
            JOIN leaders_scan ls
                ON ls.scan_date = lp.scan_date
               AND ls.setup_type = lp.setup_type
               AND ls.symbol = lp.symbol
            LEFT JOIN sector_signals sec
                ON sec.sector = lp.sector AND sec.date = lp.scan_date::date
            WHERE lp.scan_date = %s
            ORDER BY lp.setup_type DESC, lp.rank ASC
            """,
            (rd_date,),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        top_picks_df = pd.DataFrame(rows, columns=cols)
        top_picks_df = _coerce_numeric(top_picks_df, _LEADERS_RADAR_TOP_PICKS_NUMERIC_COLS)

    return rd_date, cands_df, bos_df, sec_rows_df, top_picks_df


# ── E10.5 batch E: Leaders page, _rd_trajectory() -- the confirmed live bug ─
# The one bug this whole port started from: sector_signals.composite_score
# is NUMERIC in Postgres (confirmed live). Fetched via pd.read_sql_query
# (batch D's get_leaders_radar_data_pg(), sec_rows_df's `composite` column,
# coerced to float64 via _coerce_numeric) it becomes numpy.float64; fetched
# via a raw cursor with no cast (as _rd_trajectory()'s own history query did
# before this batch) it stays decimal.Decimal. `trend = composite_today -
# vals[0]` mixed the two and raised TypeError -- reproduced live before this
# fix existed, and confirmed via a second live test that the *comparisons*
# a few lines later (composite_today > avg30 / < avg30) do NOT also raise
# (numpy.float64 is a float subclass, and Decimal-vs-float comparison has
# been supported since Python 3.2 -- only Decimal arithmetic with float
# raises). So this is a genuinely single-line fix: only the subtraction
# line needed a type change, not the whole function.
# Fixed the same way database_pg.py's get_sector_signals_latest() already
# fixes the identical column for a different caller: CAST(composite_score
# AS DOUBLE PRECISION) in the query itself, so psycopg2 returns a native
# float directly -- no Decimal anywhere in the result, on either side of
# the eventual subtraction. Verified the cast expression is character-for-
# character identical to that existing function, not just equivalent.

def get_sector_composite_history_pg(sector: str, before_date: str) -> list:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT CAST(composite_score AS DOUBLE PRECISION)
            FROM sector_signals
            WHERE sector = %s AND date < %s
            ORDER BY date DESC LIMIT 30
            """,
            (sector, before_date),
        )
        return cur.fetchall()
