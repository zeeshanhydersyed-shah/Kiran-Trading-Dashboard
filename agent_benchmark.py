"""
KSE-100 Benchmark Engine — measures every agent opportunity against the index.

For each closed agent opportunity:
  alpha_pct = agent_pl_pct - kse100_return_pct (same holding period)

Positive alpha = agent beat the market on that trade.
Negative alpha = you would have done better just holding the index.

Monthly scoreboard, rolling windows, and inception-to-date summary are all
computed here and read directly by the dashboard.

No Claude API calls — pure DB math.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Optional

from config import DB_PATH

logger = logging.getLogger(__name__)

KSE100 = "KSE-100"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

@contextmanager
def _conn():
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


# ---------------------------------------------------------------------------
# Schema migration — adds benchmark columns to agent_opportunities
# ---------------------------------------------------------------------------

BENCHMARK_MIGRATIONS = [
    "ALTER TABLE agent_opportunities ADD COLUMN kse100_entry_close REAL",
    "ALTER TABLE agent_opportunities ADD COLUMN kse100_exit_close  REAL",
    "ALTER TABLE agent_opportunities ADD COLUMN kse100_return_pct  REAL",
    "ALTER TABLE agent_opportunities ADD COLUMN alpha_pct          REAL",
]


def init_benchmark_columns():
    """Add KSE-100 benchmark columns to agent_opportunities (safe to repeat)."""
    with _conn() as conn:
        for sql in BENCHMARK_MIGRATIONS:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists


# ---------------------------------------------------------------------------
# KSE-100 price lookup
# ---------------------------------------------------------------------------

def get_kse100_close(date_str: str) -> Optional[float]:
    """
    Return KSE-100 closing price for a given date.
    If the exact date is missing (holiday / weekend), walks back up to 5 days
    to find the nearest previous trading session.
    """
    with _conn() as conn:
        for offset in range(6):
            try:
                d = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=offset)).strftime("%Y-%m-%d")
            except Exception:
                break
            row = conn.execute(
                "SELECT close FROM index_prices WHERE symbol=? AND date=? LIMIT 1",
                (KSE100, d),
            ).fetchone()
            if row and row["close"]:
                return float(row["close"])
    return None


def get_kse100_return(from_date: str, to_date: str) -> Optional[float]:
    """
    KSE-100 % return between two dates.
    Returns None if either price is unavailable.
    """
    entry = get_kse100_close(from_date)
    exit_ = get_kse100_close(to_date)
    if entry and exit_ and entry > 0:
        return round((exit_ - entry) / entry * 100, 2)
    return None


def get_kse100_series(from_date: str, to_date: str) -> list[dict]:
    """Return daily KSE-100 closes between two dates, oldest first."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT date, close FROM index_prices
               WHERE symbol=? AND date>=? AND date<=?
               ORDER BY date ASC""",
            (KSE100, from_date, to_date),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Per-opportunity benchmark fill
# ---------------------------------------------------------------------------

def fill_benchmark_for_opportunity(opp_id: int, run_date: str, exit_date: str,
                                   agent_pl_pct: Optional[float]) -> dict:
    """
    Calculate and store KSE-100 benchmark data for one opportunity.
    Returns dict with kse100_return_pct and alpha_pct.
    """
    entry_close = get_kse100_close(run_date)
    exit_close  = get_kse100_close(exit_date) if exit_date else None

    kse_return = None
    alpha      = None

    if entry_close and exit_close and entry_close > 0:
        kse_return = round((exit_close - entry_close) / entry_close * 100, 2)
        if agent_pl_pct is not None:
            alpha = round(agent_pl_pct - kse_return, 2)

    with _conn() as conn:
        conn.execute(
            """UPDATE agent_opportunities
               SET kse100_entry_close = ?,
                   kse100_exit_close  = ?,
                   kse100_return_pct  = ?,
                   alpha_pct          = ?
               WHERE id = ?""",
            (entry_close, exit_close, kse_return, alpha, opp_id),
        )

    return {
        "opp_id":           opp_id,
        "kse100_entry":     entry_close,
        "kse100_exit":      exit_close,
        "kse100_return_pct": kse_return,
        "alpha_pct":        alpha,
    }


def backfill_all_benchmarks() -> int:
    """
    Fill benchmark columns for every closed opportunity that is missing them.
    Runs automatically each daily agent cycle.
    Returns count of records updated.
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, run_date, exit_date, actual_pl_pct
               FROM agent_opportunities
               WHERE exit_date IS NOT NULL
                 AND outcome  IS NOT NULL
                 AND (kse100_return_pct IS NULL OR alpha_pct IS NULL)""",
        ).fetchall()

    updated = 0
    for row in rows:
        try:
            fill_benchmark_for_opportunity(
                opp_id=row["id"],
                run_date=row["run_date"],
                exit_date=row["exit_date"],
                agent_pl_pct=row["actual_pl_pct"],
            )
            updated += 1
        except Exception as e:
            logger.warning("Benchmark fill failed for opp %d: %s", row["id"], e)

    if updated:
        logger.info("Backfilled benchmark data for %d opportunities.", updated)
    return updated


# ---------------------------------------------------------------------------
# Inception-to-date summary
# ---------------------------------------------------------------------------

def get_inception_summary() -> dict:
    """
    Overall performance of ALL closed agent opportunities vs KSE-100
    since the first agent run.

    Returns:
      total_closed      : int
      taken_count       : int  (status was 'Taken')
      skipped_count     : int  (status was 'Skipped' / 'Expired')
      avg_agent_return  : float  (avg actual_pl_pct across closed opps)
      avg_kse100_return : float  (avg KSE-100 return over same holding periods)
      avg_alpha         : float  (avg alpha per trade)
      total_alpha       : float  (sum of alpha — cumulative edge)
      win_count         : int
      loss_count        : int
      win_rate          : float
      what_if_return    : float  (avg return if ALL suggestions had been taken)
      first_run_date    : str
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, status, outcome, actual_pl_pct,
                      kse100_return_pct, alpha_pct, run_date, exit_date
               FROM agent_opportunities
               WHERE outcome IS NOT NULL
                 AND actual_pl_pct IS NOT NULL""",
        ).fetchall()

    if not rows:
        return {}

    rows = [dict(r) for r in rows]

    closed      = rows
    taken       = [r for r in rows if r["status"] == "Taken"]
    skipped     = [r for r in rows if r["status"] in ("Skipped", "Expired")]
    wins        = [r for r in rows if r["outcome"] == "Win"]
    losses      = [r for r in rows if r["outcome"] == "Loss"]

    with_alpha  = [r for r in rows if r["alpha_pct"] is not None]
    with_kse    = [r for r in rows if r["kse100_return_pct"] is not None]

    def _avg(lst, key):
        vals = [r[key] for r in lst if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    first_date = min((r["run_date"] for r in rows), default=None)

    return {
        "total_closed":       len(closed),
        "taken_count":        len(taken),
        "skipped_count":      len(skipped),
        "avg_agent_return":   _avg(closed, "actual_pl_pct"),
        "avg_kse100_return":  _avg(with_kse, "kse100_return_pct"),
        "avg_alpha":          _avg(with_alpha, "alpha_pct"),
        "total_alpha":        round(sum(r["alpha_pct"] for r in with_alpha), 2) if with_alpha else None,
        "win_count":          len(wins),
        "loss_count":         len(losses),
        "win_rate":           round(len(wins) / len(closed) * 100, 1) if closed else None,
        "what_if_return":     _avg(closed, "actual_pl_pct"),   # all suggestions equal-weighted
        "first_run_date":     first_date,
    }


# ---------------------------------------------------------------------------
# Monthly scoreboard
# ---------------------------------------------------------------------------

def get_monthly_scorecard() -> list[dict]:
    """
    Month-by-month comparison: agent suggestions vs KSE-100.

    Each row:
      month             : "2026-05"
      opp_count         : how many closed opps that month
      avg_agent_return  : avg actual_pl_pct for opps that closed that month
      kse100_month_return: KSE-100 return for the calendar month
      avg_alpha         : avg alpha per trade
      win_rate          : wins / total
      verdict           : "✅ Beat" | "❌ Lagged" | "—"
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, exit_date, actual_pl_pct, kse100_return_pct, alpha_pct, outcome
               FROM agent_opportunities
               WHERE exit_date IS NOT NULL
                 AND outcome IS NOT NULL
                 AND actual_pl_pct IS NOT NULL
               ORDER BY exit_date ASC""",
        ).fetchall()

    if not rows:
        return []

    # Group by exit month
    from collections import defaultdict
    monthly: dict[str, list] = defaultdict(list)
    for r in rows:
        month = str(r["exit_date"])[:7]  # "2026-05"
        monthly[month].append(dict(r))

    result = []
    for month in sorted(monthly.keys()):
        opps = monthly[month]
        wins = sum(1 for o in opps if o.get("outcome") == "Win")
        with_alpha = [o for o in opps if o.get("alpha_pct") is not None]
        with_kse   = [o for o in opps if o.get("kse100_return_pct") is not None]

        # KSE-100 return for the calendar month
        month_start = month + "-01"
        # last day of month: find next month's first day minus 1
        y, m = int(month[:4]), int(month[5:7])
        if m == 12:
            month_end = f"{y+1}-01-01"
        else:
            month_end = f"{y}-{m+1:02d}-01"
        # walk back to find last trading day
        kse_month = get_kse100_return(month_start, month_end)

        avg_agent  = round(sum(o["actual_pl_pct"] for o in opps) / len(opps), 2)
        avg_alpha  = round(sum(o["alpha_pct"] for o in with_alpha) / len(with_alpha), 2) if with_alpha else None
        win_rate   = round(wins / len(opps) * 100, 1)

        if avg_alpha is not None:
            verdict = "✅ Beat market" if avg_alpha > 0 else "❌ Lagged market"
        else:
            verdict = "—"

        result.append({
            "month":              month,
            "opp_count":          len(opps),
            "avg_agent_return":   avg_agent,
            "kse100_month_return": kse_month,
            "avg_alpha":          avg_alpha,
            "win_rate":           win_rate,
            "verdict":            verdict,
        })

    return result


# ---------------------------------------------------------------------------
# Rolling window comparison (30d / 90d / 180d)
# ---------------------------------------------------------------------------

def get_rolling_comparison(days: int = 30) -> dict:
    """
    Agent performance vs KSE-100 over the last N calendar days.

    Returns dict:
      period_days       : int
      from_date         : str
      opp_count         : int
      avg_agent_return  : float
      kse100_period_return : float  (index return over same window)
      avg_alpha         : float
      win_rate          : float
      verdict           : str
    """
    to_date   = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()

    with _conn() as conn:
        rows = conn.execute(
            """SELECT actual_pl_pct, kse100_return_pct, alpha_pct, outcome
               FROM agent_opportunities
               WHERE exit_date >= ?
                 AND exit_date <= ?
                 AND outcome IS NOT NULL
                 AND actual_pl_pct IS NOT NULL""",
            (from_date, to_date),
        ).fetchall()

    rows = [dict(r) for r in rows]
    if not rows:
        return {
            "period_days": days,
            "from_date": from_date,
            "opp_count": 0,
            "avg_agent_return": None,
            "kse100_period_return": get_kse100_return(from_date, to_date),
            "avg_alpha": None,
            "win_rate": None,
            "verdict": "Insufficient data",
        }

    wins       = sum(1 for r in rows if r.get("outcome") == "Win")
    with_alpha = [r for r in rows if r.get("alpha_pct") is not None]
    avg_agent  = round(sum(r["actual_pl_pct"] for r in rows) / len(rows), 2)
    avg_alpha  = round(sum(r["alpha_pct"] for r in with_alpha) / len(with_alpha), 2) if with_alpha else None
    kse_period = get_kse100_return(from_date, to_date)
    win_rate   = round(wins / len(rows) * 100, 1)

    if avg_alpha is not None:
        verdict = "✅ Beating market" if avg_alpha > 0 else "❌ Lagging market"
    else:
        verdict = "—"

    return {
        "period_days":          days,
        "from_date":            from_date,
        "opp_count":            len(rows),
        "avg_agent_return":     avg_agent,
        "kse100_period_return": kse_period,
        "avg_alpha":            avg_alpha,
        "win_rate":             win_rate,
        "verdict":              verdict,
    }


# ---------------------------------------------------------------------------
# Per-trade breakdown table
# ---------------------------------------------------------------------------

def get_per_trade_benchmark(limit: int = 50) -> list[dict]:
    """
    Full per-opportunity breakdown with KSE-100 comparison.
    Sorted newest-first. Used for the detail table in the dashboard.
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, run_date, exit_date, symbol, direction,
                      pattern_name, status, outcome,
                      entry_price, actual_exit, actual_pl_pct,
                      kse100_entry_close, kse100_exit_close,
                      kse100_return_pct, alpha_pct,
                      confidence_pct, reasoning
               FROM agent_opportunities
               WHERE outcome IS NOT NULL
               ORDER BY exit_date DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# "What-if" analysis
# ---------------------------------------------------------------------------

def get_what_if_analysis() -> dict:
    """
    Compares three scenarios for all agent suggestions:
      A) You took every suggestion (Taken)
      B) You skipped every suggestion (Skipped/Expired)
      C) You just held KSE-100 (equal-weighted across same holding periods)

    Returns dict with scenario returns, alpha, and verdict.
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT status, outcome, actual_pl_pct, kse100_return_pct, alpha_pct
               FROM agent_opportunities
               WHERE outcome IS NOT NULL AND actual_pl_pct IS NOT NULL""",
        ).fetchall()

    rows = [dict(r) for r in rows]
    if not rows:
        return {}

    taken   = [r for r in rows if r["status"] == "Taken"]
    skipped = [r for r in rows if r["status"] in ("Skipped", "Expired")]
    kse_vals = [r["kse100_return_pct"] for r in rows if r.get("kse100_return_pct") is not None]

    def _avg(lst, key="actual_pl_pct"):
        vals = [r[key] for r in lst if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    all_avg    = _avg(rows)
    taken_avg  = _avg(taken)
    skip_avg   = _avg(skipped)
    kse_avg    = round(sum(kse_vals) / len(kse_vals), 2) if kse_vals else None

    return {
        "all_suggestions_avg":    all_avg,
        "taken_only_avg":         taken_avg,
        "skipped_only_avg":       skip_avg,
        "kse100_avg":             kse_avg,
        "taken_count":            len(taken),
        "skipped_count":          len(skipped),
        "total_count":            len(rows),
        # Alpha vs KSE-100
        "all_alpha":   round(all_avg - kse_avg, 2)    if all_avg  and kse_avg else None,
        "taken_alpha": round(taken_avg - kse_avg, 2)  if taken_avg and kse_avg else None,
        "skip_alpha":  round(skip_avg - kse_avg, 2)   if skip_avg  and kse_avg else None,
    }


# ---------------------------------------------------------------------------
# 1.5% portfolio target tracker
# ---------------------------------------------------------------------------

def get_portfolio_target_progress(portfolio_value: float = 2_000_000,
                                  target_pct: float = 1.5,
                                  month: str = None) -> dict:
    """
    Tracks progress toward the 1.5% monthly portfolio return target.

    portfolio_value : current portfolio in PKR (default 2M as placeholder)
    target_pct      : monthly target % (default 1.5%)
    month           : "YYYY-MM" — defaults to current month

    For each TAKEN trade this month, calculates contribution to portfolio
    assuming 1% risk sizing per trade.

    Returns:
      target_pkr          : PKR target for the month
      achieved_pkr        : estimated PKR gained from taken trades
      achieved_pct        : as % of portfolio
      remaining_pkr       : how much more needed
      on_track            : bool
      taken_trades        : list of contributing trades
    """
    if month is None:
        month = date.today().strftime("%Y-%m")

    with _conn() as conn:
        rows = conn.execute(
            """SELECT symbol, direction, actual_pl_pct, entry_price, actual_exit,
                      run_date, exit_date, outcome
               FROM agent_opportunities
               WHERE status = 'Taken'
                 AND outcome IS NOT NULL
                 AND actual_pl_pct IS NOT NULL
                 AND strftime('%Y-%m', COALESCE(exit_date, run_date)) = ?""",
            (month,),
        ).fetchall()

    trades = [dict(r) for r in rows]

    # 1% risk per trade → at 1% SL that's 1% of portfolio per trade
    # Simplified: each trade P&L% × (1% of portfolio / risk%)
    # For now use equal 1% sizing as approximation
    risk_per_trade = portfolio_value * 0.01  # 1% of portfolio at risk per trade

    achieved_pkr = 0.0
    for t in trades:
        pl_pct = t.get("actual_pl_pct", 0) or 0
        # rough: 1% risk, so gain/loss = pl_pct / risk_pct × risk_pkr
        # if we don't have risk_pct per trade, assume 2% avg risk
        achieved_pkr += (pl_pct / 2.0) * risk_per_trade / 100

    target_pkr    = portfolio_value * target_pct / 100
    achieved_pct  = round(achieved_pkr / portfolio_value * 100, 2)
    remaining_pkr = max(0, target_pkr - achieved_pkr)
    on_track      = achieved_pkr >= target_pkr

    return {
        "month":          month,
        "target_pct":     target_pct,
        "target_pkr":     round(target_pkr),
        "achieved_pkr":   round(achieved_pkr),
        "achieved_pct":   achieved_pct,
        "remaining_pkr":  round(remaining_pkr),
        "on_track":       on_track,
        "taken_count":    len(trades),
        "taken_trades":   trades,
    }
