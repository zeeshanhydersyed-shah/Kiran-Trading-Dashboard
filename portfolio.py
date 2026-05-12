"""
Weinstein Stage 2 Portfolio Screener.

Computes stage classification, RS vs KSE-100, and a composite portfolio
score for every stock with sufficient history. Used by the Portfolio page
in dashboard.py.

Stage rules (Weinstein):
  Stage 1  — Basing:    price ~MA30w, MA30w flat
  Stage 2  — Advancing: price > MA30w, MA30w rising
  Stage 3  — Topping:   price > MA30w but MA30w flattening/turning down
  Stage 4  — Declining: price < MA30w, MA30w falling

Portfolio candidates are Stage 2 stocks ranked by composite score:
  RS rank vs KSE-100 (40pts) + stage clarity (30pts) +
  sector strength (20pts) + RS trend (10pts)
"""

import logging
import pandas as pd
import numpy as np
from collections import defaultdict

from database import get_conn
from config import EXCLUDED_SECTORS

logger = logging.getLogger(__name__)

MA30W = 150    # 30-week MA in trading days (~5 days × 30 weeks)
MA10W = 50     # 10-week MA
MA4W  = 20     # 4-week ago snapshot for MA direction
MIN_HISTORY = MA30W + MA4W    # minimum rows needed per symbol


def _get_price_history() -> pd.DataFrame:
    """Fetch full price history joined to sectors, excluded sectors removed."""
    excl_ph = ",".join(["?"] * len(EXCLUDED_SECTORS))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT p.symbol, s.sector, p.date, p.close
                FROM prices p
                JOIN sectors s ON s.symbol = p.symbol
                WHERE s.sector NOT IN ({excl_ph})
                  AND p.close IS NOT NULL AND p.close > 0
                ORDER BY p.symbol, p.date""",
            list(EXCLUDED_SECTORS),
        ).fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "sector", "date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _get_index_history() -> pd.Series:
    """Fetch KSE-100 daily closes, indexed by date."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, close FROM index_prices "
            "WHERE symbol='KSE-100' AND close IS NOT NULL ORDER BY date"
        ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"]


def _classify_stage(close: float, ma30w: float, ma30w_4wk: float,
                    ma10w: float) -> tuple[int, str]:
    """
    Returns (stage_int, stage_label).
    ma30w_4wk is the MA30w value 4 weeks ago (MA direction proxy).
    """
    ma_rising  = ma30w > ma30w_4wk * 1.005   # MA must be up >0.5% over 4wks
    ma_falling = ma30w < ma30w_4wk * 0.995
    above_ma   = close > ma30w
    pct_above  = (close - ma30w) / ma30w * 100

    if above_ma and ma_rising:
        return 2, "Stage 2 — Advancing"
    if above_ma and not ma_falling:
        return 3, "Stage 3 — Topping"
    if above_ma and ma_falling:
        return 3, "Stage 3 — Rolling Over"
    if not above_ma and ma_falling:
        return 4, "Stage 4 — Declining"
    # price below MA but MA flat or starting to rise → basing
    return 1, "Stage 1 — Basing"


def compute_portfolio_candidates(sector_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Main entry point. Returns a ranked DataFrame of all scoreable stocks.

    Columns returned:
        symbol, sector, latest_close, latest_date,
        ma10w, ma30w, dist_from_30w_pct,
        stage, stage_label,
        rs_30d, rs_10d, rs_trend,
        sector_rank, sector_momentum,
        composite_score, recommendation
    """
    prices   = _get_price_history()
    kse100   = _get_index_history()

    if prices.empty or kse100.empty:
        logger.warning("portfolio.py: insufficient data")
        return pd.DataFrame()

    # KSE-100 RS base values
    kse_latest   = kse100.iloc[-1]
    kse_30d_base = kse100.iloc[max(0, len(kse100) - 31)] if len(kse100) >= 31 else kse100.iloc[0]
    kse_10d_base = kse100.iloc[max(0, len(kse100) - 11)] if len(kse100) >= 11 else kse100.iloc[0]
    kse_rs_30d   = (kse_latest - kse_30d_base) / kse_30d_base * 100
    kse_rs_10d   = (kse_latest - kse_10d_base) / kse_10d_base * 100

    # Sector lookup from sector_df if provided
    sec_rank_map = {}
    sec_mom_map  = {}
    if sector_df is not None and not sector_df.empty:
        for _, row in sector_df.iterrows():
            sec_rank_map[row["sector"]] = int(row["rank"])
            sec_mom_map[row["sector"]]  = str(row.get("momentum", ""))

    n_sectors = len(sec_rank_map) or 1

    records = []

    for symbol, grp in prices.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        if len(grp) < MIN_HISTORY:
            continue

        closes       = grp["close"].values
        dates        = grp["date"].values
        latest_close = float(closes[-1])
        latest_date  = pd.Timestamp(dates[-1])
        sector       = grp["sector"].iloc[-1]

        ma30w      = float(np.mean(closes[-MA30W:]))
        ma10w      = float(np.mean(closes[-MA10W:]))
        ma30w_4wk  = float(np.mean(closes[-(MA30W + MA4W):-MA4W]))

        stage, stage_label = _classify_stage(latest_close, ma30w, ma30w_4wk, ma10w)
        dist_from_30w = round((latest_close - ma30w) / ma30w * 100, 2)

        # RS vs KSE-100
        base_30d   = float(closes[max(0, len(closes) - 31)])
        base_10d   = float(closes[max(0, len(closes) - 11)])
        stock_rs30 = (latest_close - base_30d) / base_30d * 100 if base_30d > 0 else 0.0
        stock_rs10 = (latest_close - base_10d) / base_10d * 100 if base_10d > 0 else 0.0
        rs_30d     = round(stock_rs30 - kse_rs_30d, 2)
        rs_10d     = round(stock_rs10 - kse_rs_10d, 2)
        rs_trend   = "Improving" if rs_10d > rs_30d else "Weakening"

        sec_rank = sec_rank_map.get(sector, n_sectors)
        sec_mom  = sec_mom_map.get(sector, "")

        records.append({
            "symbol":           symbol,
            "sector":           sector,
            "latest_close":     round(latest_close, 2),
            "latest_date":      latest_date.date(),
            "ma10w":            round(ma10w, 2),
            "ma30w":            round(ma30w, 2),
            "dist_from_30w_pct": dist_from_30w,
            "stage":            stage,
            "stage_label":      stage_label,
            "rs_30d":           rs_30d,
            "rs_10d":           rs_10d,
            "rs_trend":         rs_trend,
            "sector_rank":      sec_rank,
            "sector_momentum":  sec_mom,
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # ── Composite score (0–100) ───────────────────────────────────────────────
    # RS rank component (40 pts): percentile rank of rs_30d
    df["_rs_rank_pct"] = df["rs_30d"].rank(pct=True)
    rs_pts = (df["_rs_rank_pct"] * 40).round(1)

    # Stage clarity component (30 pts)
    # Stage 2 above MA: more points for being firmly above (up to 15% above = full pts)
    # Stage 2 gets 30 pts, Stage 1 gets 15 pts, Stage 3 gets 5 pts, Stage 4 gets 0 pts
    stage_base = df["stage"].map({2: 30, 1: 15, 3: 5, 4: 0}).fillna(0)
    # Bonus for firmly in Stage 2 (distance 2–15% = full; <2% or >15% = partial)
    dist_bonus = df.apply(
        lambda r: min(r["dist_from_30w_pct"] / 15, 1.0) * 5
        if r["stage"] == 2 and r["dist_from_30w_pct"] > 0 else 0,
        axis=1,
    )
    stage_pts = (stage_base + dist_bonus).clip(0, 30)

    # Sector strength component (20 pts): inverse of rank
    n_s = max(df["sector_rank"].max(), 1)
    sector_pts = ((1 - (df["sector_rank"] - 1) / n_s) * 20).round(1)

    # RS trend component (10 pts)
    trend_pts = df["rs_trend"].map({"Improving": 10, "Weakening": 0}).fillna(5)

    df["composite_score"] = (rs_pts + stage_pts + sector_pts + trend_pts).round(1)

    # ── Recommendation ────────────────────────────────────────────────────────
    def recommend(row):
        if row["stage"] == 4:
            return "❌ Avoid"
        if row["stage"] == 3:
            return "⚠️ Exit / Caution"
        if row["stage"] == 1:
            return "👀 Watch"
        # Stage 2
        if row["rs_30d"] < 0:
            return "⚠️ Weak RS"
        if row["dist_from_30w_pct"] > 25:
            return "✋ Extended"
        if row["dist_from_30w_pct"] < 0:
            return "⚠️ Below MA"
        if row["sector_momentum"] in ("Heating Up",) and row["rs_trend"] == "Improving":
            return "🟢 Strong Buy"
        return "🔵 Hold / Add"

    df["recommendation"] = df.apply(recommend, axis=1)

    df = df.drop(columns=["_rs_rank_pct"])
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    return df
