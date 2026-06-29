"""
Kelly Criterion backend — position sizing for Kiran PSX dashboard.

Data pipeline:
  1. Capital base   → read from ASSET ALLOCATION.XLSX, sheet JOURNAL-2, cell B3
                      (manually updated daily; falls back to latest portfolio_values DB row)
  2. Trade history  → trade_setups WHERE source='Actual' AND outcome IN ('Win','Loss')
  3. Window         → strict rolling 30-trade lookback (most recent 30 resolved trades)
  4. Formula        → Full Kelly f* = W - (1-W)/R  (can be negative — informational only)
  5. Operational    → Half Kelly = f* / 2  (floored at 0 for position sizing; raw value preserved)

Public API:
    get_capital_pkr(excel_path)      → float | None
    compute_kelly(trades_df)         → KellyResult
    kelly_position_pkr(result, cap)  → float
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
EXCEL_PATH   = r"D:\PERSONAL\Personal Sheets\ASSET ALLOCATION\ASSET ALLOCATION.XLSX"
EXCEL_SHEET  = "JOURNAL-2"
CAPITAL_CELL = "B3"          # single cell holding current portfolio value in PKR

ROLLING_WINDOW    = 30       # strict lookback — most recent N resolved (Win/Loss) trades
KELLY_DIVISOR     = 2        # Half Kelly
MIN_SAMPLE        = 10       # warn (not block) if resolved trades < this


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class KellyResult:
    # Sample
    n_resolved: int          # Win + Loss count in window
    n_wins: int
    n_losses: int
    window: int              # actual window size used (≤ ROLLING_WINDOW)

    # Edge metrics
    win_rate: float          # W  (0–1)
    avg_win_pct: float       # average % gain on winning trades
    avg_loss_pct: float      # average % loss on losing trades (negative number)
    payoff_ratio: float      # R = abs(avg_win / avg_loss)

    # Kelly outputs
    full_kelly_pct: float    # f* as a percentage (can be negative)
    half_kelly_pct: float    # f* / 2 as a percentage (can be negative)
    operational_pct: float   # max(0, half_kelly_pct) — used for sizing; 0 when edge absent

    # Flags
    low_sample: bool         # True if n_resolved < MIN_SAMPLE
    negative_edge: bool      # True if full_kelly_pct < 0

    # Capital
    capital_pkr: Optional[float] = None       # base capital used for sizing
    capital_source: str = "unknown"           # "excel" | "db" | "none"

    # Derived sizing (populated by kelly_position_pkr)
    position_pkr: Optional[float] = None      # capital × operational_pct/100
    risk_pkr: Optional[float] = None          # position_pkr × avg_risk_pct/100 (if available)

    # Per-trade sequence used (chronological, most recent last)
    trades_used: list[dict] = field(default_factory=list)


# ── 1. Capital reader ─────────────────────────────────────────────────────────
def get_capital_pkr(
    excel_path: str = EXCEL_PATH,
    db_path: Optional[str] = None,
) -> tuple[Optional[float], str]:
    """
    Read current portfolio value (PKR) from the Excel file first,
    falling back to the latest row in portfolio_values if Excel is unavailable.

    Returns (value, source) where source is "excel", "db", or "none".

    Excel reads cell B3 on JOURNAL-2 directly using openpyxl (data_only=True).
    This avoids loading the full sheet and respects cached formula values.
    """
    # ── Primary: Excel cell B3 ────────────────────────────────────────────────
    if os.path.exists(excel_path):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
            ws = wb[EXCEL_SHEET]
            raw = ws[CAPITAL_CELL].value
            wb.close()
            if raw is not None:
                val = float(raw)
                if val > 0:
                    logger.info("Capital from Excel %s!%s: PKR %.0f", EXCEL_SHEET, CAPITAL_CELL, val)
                    return val, "excel"
                logger.warning("Excel cell %s is zero or negative (%s) — falling back to DB", CAPITAL_CELL, raw)
        except Exception as exc:
            logger.warning("Could not read Excel capital: %s", exc)
    else:
        logger.info("Excel not found at %s — falling back to DB", excel_path)

    # ── Fallback: latest portfolio_values row in DB (SQLite or Supabase) ────────
    try:
        from database import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM portfolio_values ORDER BY date DESC LIMIT 1"
            ).fetchone()
        if row and row[0]:
            val = float(row[0])
            logger.info("Capital from DB portfolio_values: PKR %.0f", val)
            return val, "db"
    except Exception as exc:
        logger.warning("Could not read capital from DB: %s", exc)

    logger.error("No capital source available — Excel missing and DB fallback failed")
    return None, "none"


# ── 2. Kelly calculation ───────────────────────────────────────────────────────
def compute_kelly(
    trades_df: pd.DataFrame,
    window: int = ROLLING_WINDOW,
    divisor: int = KELLY_DIVISOR,
) -> KellyResult:
    """
    Compute Kelly metrics from a DataFrame of closed actual trades.

    Expected columns: outcome ('Win'|'Loss'), actual_pl_pct (float),
                      exit_date or created_date (for ordering).
    Trades must be pre-filtered to source='Actual'.

    The function:
    - Takes the most recent `window` resolved (Win/Loss) trades chronologically.
    - Computes W, R, f*, f*/divisor.
    - Never raises — returns a result with negative_edge=True if edge is absent.
    """
    # ── Resolve ordering column ────────────────────────────────────────────────
    if "exit_date" in trades_df.columns and trades_df["exit_date"].notna().any():
        sort_col = "exit_date"
    else:
        sort_col = "created_date"

    resolved = (
        trades_df[trades_df["outcome"].isin(["Win", "Loss"])]
        .copy()
        .sort_values(sort_col, na_position="first")
        .tail(window)          # strict rolling: most recent N resolved trades
        .reset_index(drop=True)
    )

    n = len(resolved)
    n_wins   = int((resolved["outcome"] == "Win").sum())
    n_losses = int((resolved["outcome"] == "Loss").sum())

    # ── Guard: need at least one win and one loss to compute R ────────────────
    if n == 0 or n_wins == 0 or n_losses == 0:
        return KellyResult(
            n_resolved=n, n_wins=n_wins, n_losses=n_losses, window=window,
            win_rate=n_wins/n if n else 0.0,
            avg_win_pct=0.0, avg_loss_pct=0.0, payoff_ratio=0.0,
            full_kelly_pct=0.0, half_kelly_pct=0.0, operational_pct=0.0,
            low_sample=True, negative_edge=True,
            trades_used=resolved.to_dict("records"),
        )

    # ── Core math ─────────────────────────────────────────────────────────────
    W = n_wins / n

    win_pcts  = resolved.loc[resolved["outcome"] == "Win",  "actual_pl_pct"].dropna()
    loss_pcts = resolved.loc[resolved["outcome"] == "Loss", "actual_pl_pct"].dropna()

    avg_win  = float(win_pcts.mean())    # positive
    avg_loss = float(loss_pcts.mean())   # negative

    # Integrity guard: avg_loss must be negative
    if avg_loss >= 0:
        logger.error("avg_loss is non-negative (%.4f) — data integrity issue", avg_loss)
        avg_loss = -abs(avg_win) * 0.01  # fallback to prevent division issues; flags negative_edge

    R = abs(avg_win / avg_loss)          # payoff ratio (positive)

    # Kelly formula: f* = W - (1-W)/R
    f_star        = W - (1 - W) / R
    f_half        = f_star / divisor
    operational   = max(0.0, f_half)     # 0 when edge is absent; never negative for sizing

    # ── Build result ──────────────────────────────────────────────────────────
    trades_seq = resolved[["outcome", "actual_pl_pct", sort_col]].rename(
        columns={sort_col: "date"}
    ).to_dict("records")

    return KellyResult(
        n_resolved=n,
        n_wins=n_wins,
        n_losses=n_losses,
        window=window,
        win_rate=W,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        payoff_ratio=R,
        full_kelly_pct=round(f_star * 100, 4),
        half_kelly_pct=round(f_half * 100, 4),
        operational_pct=round(operational * 100, 4),
        low_sample=(n < MIN_SAMPLE),
        negative_edge=(f_star < 0),
        trades_used=trades_seq,
    )


# ── 3. Position sizing ─────────────────────────────────────────────────────────
def kelly_position_pkr(
    result: KellyResult,
    capital_pkr: float,
    avg_risk_pct: Optional[float] = None,
) -> KellyResult:
    """
    Attach PKR position size to an existing KellyResult.

    position_pkr  = capital_pkr × operational_pct / 100
                    (0 when Kelly is negative — no sizing output, not an error)

    risk_pkr      = position_pkr × avg_risk_pct / 100
                    Only set if avg_risk_pct is provided (e.g. from mean risk_pct
                    of the last 30 trades). Represents max expected loss at SL.

    Mutates result in-place and returns it.
    """
    result.capital_pkr  = capital_pkr
    result.position_pkr = round(capital_pkr * result.operational_pct / 100, 0)

    if avg_risk_pct is not None and avg_risk_pct > 0 and result.position_pkr > 0:
        result.risk_pkr = round(result.position_pkr * avg_risk_pct / 100, 0)

    return result


# ── 4. Convenience: full pipeline in one call ─────────────────────────────────
def build_kelly_snapshot(
    db_path: Optional[str] = None,
    excel_path: str = EXCEL_PATH,
    window: int = ROLLING_WINDOW,
    divisor: int = KELLY_DIVISOR,
) -> KellyResult:
    """
    End-to-end: read trades from DB, read capital from Excel (with DB fallback),
    compute Kelly, attach position size. Returns a fully populated KellyResult.

    Uses database.get_conn() so it works transparently against both local SQLite
    (development) and Supabase PostgreSQL (Streamlit Cloud production).
    db_path is accepted for CLI use only; the cloud path ignores it.

    Example:
        from kelly import build_kelly_snapshot
        snap = build_kelly_snapshot()
        print(snap.full_kelly_pct, snap.position_pkr)
    """
    # ── Load closed Actual trades via database.get_conn() (SQLite or Supabase) ──
    try:
        from database import get_conn
        with get_conn() as conn:
            trades_df = pd.read_sql_query(
                """
                SELECT id, created_date, exit_date, symbol, outcome,
                       actual_pl_pct, actual_pl_pkr, risk_pct
                FROM trade_setups
                WHERE source  = 'Actual'
                  AND outcome IN ('Win', 'Loss')
                ORDER BY COALESCE(exit_date, created_date) ASC
                """,
                conn,
            )
    except Exception as exc:
        logger.error("Could not load trades from DB: %s", exc)
        trades_df = pd.DataFrame()

    # ── Compute Kelly metrics ──────────────────────────────────────────────────
    result = compute_kelly(trades_df, window=window, divisor=divisor)

    # ── Capital ────────────────────────────────────────────────────────────────
    capital, source = get_capital_pkr(excel_path=excel_path, db_path=db_path)
    result.capital_source = source

    if capital:
        # avg_risk_pct from the same rolling window trades
        avg_risk = None
        if not trades_df.empty and "risk_pct" in trades_df.columns:
            window_trades = trades_df.tail(window)
            avg_risk_series = window_trades["risk_pct"].dropna()
            if not avg_risk_series.empty:
                avg_risk = float(avg_risk_series.mean())

        kelly_position_pkr(result, capital, avg_risk_pct=avg_risk)

    return result


# ── 5. Quick CLI diagnostic ───────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Lenovo\psx_pipeline\psx_data.db"
    snap = build_kelly_snapshot(db)

    print(f"\n{'='*50}")
    print(f"KELLY SNAPSHOT  (window={snap.window}, divisor={KELLY_DIVISOR}x)")
    print(f"{'='*50}")
    print(f"Sample          : {snap.n_resolved} resolved  ({snap.n_wins}W / {snap.n_losses}L)")
    print(f"Win rate  W     : {snap.win_rate*100:.2f}%")
    print(f"Avg win         : +{snap.avg_win_pct:.2f}%")
    print(f"Avg loss        : {snap.avg_loss_pct:.2f}%")
    print(f"Payoff ratio R  : {snap.payoff_ratio:.4f}")
    print(f"Full Kelly f*   : {snap.full_kelly_pct:+.2f}%")
    print(f"Half Kelly      : {snap.half_kelly_pct:+.2f}%")
    print(f"Operational     : {snap.operational_pct:.2f}%  {'(NEGATIVE EDGE — no sizing)' if snap.negative_edge else ''}")
    print(f"Low sample warn : {snap.low_sample}")
    if snap.capital_pkr:
        print(f"\nCapital ({snap.capital_source}): PKR {snap.capital_pkr:,.0f}")
        print(f"Position size   : PKR {snap.position_pkr:,.0f}")
        if snap.risk_pkr:
            print(f"Risk at SL      : PKR {snap.risk_pkr:,.0f}")
    print(f"{'='*50}")
    print(f"\nLast {snap.window} trades (chronological):")
    for t in snap.trades_used:
        marker = "W" if t["outcome"] == "Win" else "L"
        print(f"  {marker}  {str(t.get('date',''))[:10]}  {t['outcome']:5s}  {t['actual_pl_pct']:+.2f}%")
