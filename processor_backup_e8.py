"""
Data processing: 30-day & 10-day stock performance, sector rankings,
market breadth gauge, momentum acceleration, and trade candidates.
"""

import logging

import pandas as pd

from config import EXCLUDED_SECTORS, DFC_SYMBOLS
from database import get_sector_price_data
from kse100_filter import KSE100Filter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stock-level performance
# ---------------------------------------------------------------------------

def compute_stock_performance(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """
    For each symbol:
        perf = (latest_close - close_N_trading_days_ago) / close_N_trading_days_ago * 100

    df must have columns: symbol, sector, date (str/datetime), close (float).
    Returns: symbol, sector, latest_date, latest_close, base_date, base_close, perf_pct
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])

    results = []
    for symbol, grp in df.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        if len(grp) < 2:
            continue

        latest_row = grp.iloc[-1]
        base_idx   = max(0, len(grp) - window - 1)
        base_row   = grp.iloc[base_idx]

        if base_row["close"] == 0:
            continue

        perf = (latest_row["close"] - base_row["close"]) / base_row["close"] * 100
        results.append({
            "symbol":       symbol,
            "sector":       latest_row["sector"],
            "latest_date":  latest_row["date"].date(),
            "latest_close": latest_row["close"],
            "base_date":    base_row["date"].date(),
            "base_close":   base_row["close"],
            "perf_pct":     round(perf, 2),
        })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Sector rankings + momentum
# ---------------------------------------------------------------------------

def compute_sector_rankings(
    stock_30d: pd.DataFrame,
    stock_10d: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build sector ranking table merging 30-day and 10-day performance.

    Momentum label (vs 30d baseline):
        Heating Up   — 10d > 30d and both positive         (acceleration, long bias)
        Cooling Down — 10d < 30d and both positive         (deceleration, watch for exit)
        Recovering   — 10d > 0 but 30d < 0                 (turnaround candidate)
        Rolling Over — 10d < 0 but 30d > 0                 (distribution, short watch)
        Falling      — both negative, 10d worse than 30d   (confirmed downtrend)
        Stabilising  — both negative, 10d better than 30d  (possible floor)
    """
    if stock_30d.empty:
        return pd.DataFrame()

    # Build 10d median per sector (robust to corporate actions: rights issues, splits, etc)
    perf_10d = {}
    if not stock_10d.empty:
        for sector, grp in stock_10d.groupby("sector"):
            perf_10d[sector] = round(grp["perf_pct"].median(), 2)

    rows = []
    for sector, grp in stock_30d.groupby("sector"):
        avg_30d  = round(grp["perf_pct"].median(), 2)
        avg_10d  = perf_10d.get(sector, None)
        best     = grp.loc[grp["perf_pct"].idxmax()]
        worst    = grp.loc[grp["perf_pct"].idxmin()]

        # 4-Stage momentum label (Weinstein-based)
        if avg_10d is not None:
            if avg_30d >= 0 and avg_10d >= 0:
                # Both positive = Uptrend phase
                label = "Stage 2: Advancing" if avg_10d > avg_30d else "Stage 3: Topping"
            elif avg_30d < 0 and avg_10d >= 0:
                # Transitioning from down to up = Early Advancing
                label = "Stage 2: Advancing"
            elif avg_30d >= 0 and avg_10d < 0:
                # Transitioning from up to down = Late Topping
                label = "Stage 3: Topping"
            else:  # both negative or near zero
                # Downtrend or flat = Declining or Basing
                label = "Stage 4: Declining" if avg_10d < avg_30d else "Stage 1: Basing"
        else:
            label = "—"

        rows.append({
            "sector":         sector,
            "avg_perf_pct":   avg_30d,
            "avg_10d_pct":    avg_10d,
            "momentum":       label,
            "stock_count":    len(grp),
            "best_stock":     best["symbol"],
            "best_perf_pct":  best["perf_pct"],
            "worst_stock":    worst["symbol"],
            "worst_perf_pct": worst["perf_pct"],
        })

    result = pd.DataFrame(rows).sort_values("avg_perf_pct", ascending=False)
    result.insert(0, "rank", range(1, len(result) + 1))
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Market breadth
# ---------------------------------------------------------------------------

def compute_market_breadth(stock_30d: pd.DataFrame, sector_df: pd.DataFrame) -> dict:
    """
    Derive a market-wide condition from breadth metrics.

    Returns a dict with:
        condition       : "Bullish" | "Leaning Bullish" | "Ranging" |
                          "Leaning Bearish" | "Bearish"
        stock_pct_pos   : % of stocks with positive 30d perf
        sector_pct_pos  : % of sectors with positive 30d perf
        avg_sector_perf : average of all sector 30d performances
        breadth_score   : 0–100 composite score (>60 bullish, <40 bearish)
        color           : hex colour for the condition label
        emoji           : quick visual cue
    """
    if stock_30d.empty or sector_df.empty:
        return {}

    total_stocks  = len(stock_30d)
    pos_stocks    = (stock_30d["perf_pct"] > 0).sum()
    stock_pct_pos = round(pos_stocks / total_stocks * 100, 1) if total_stocks else 0

    total_sectors  = len(sector_df)
    pos_sectors    = (sector_df["avg_perf_pct"] > 0).sum()
    sector_pct_pos = round(pos_sectors / total_sectors * 100, 1) if total_sectors else 0

    avg_sector_perf = round(sector_df["avg_perf_pct"].median(), 2)

    # Composite breadth score: blend stock breadth + sector breadth
    breadth_score = round(stock_pct_pos * 0.6 + sector_pct_pos * 0.4, 1)

    if breadth_score >= 70:
        condition, color, emoji = "Bullish",         "#22c55e", "🟢"
    elif breadth_score >= 57:
        condition, color, emoji = "Leaning Bullish", "#86efac", "🟡"
    elif breadth_score >= 43:
        condition, color, emoji = "Ranging",         "#fbbf24", "🟡"
    elif breadth_score >= 30:
        condition, color, emoji = "Leaning Bearish", "#fca5a5", "🔴"
    else:
        condition, color, emoji = "Bearish",         "#ef4444", "🔴"

    return {
        "condition":       condition,
        "stock_pct_pos":   stock_pct_pos,
        "sector_pct_pos":  sector_pct_pos,
        "avg_sector_perf": avg_sector_perf,
        "breadth_score":   breadth_score,
        "color":           color,
        "emoji":           emoji,
    }


# ---------------------------------------------------------------------------
# Trade candidates
# ---------------------------------------------------------------------------

def compute_trade_candidates(
    stock_30d: pd.DataFrame,
    sector_df: pd.DataFrame,
    top_n_sectors: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Long candidates  — strongest stocks from the top N sectors by 30d perf.
    Short candidates — weakest stocks from the bottom N sectors by 30d perf.

    Returns (long_df, short_df).
    """
    if stock_30d.empty or sector_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    top_sectors    = sector_df.head(top_n_sectors)["sector"].tolist()
    bottom_sectors = sector_df.tail(top_n_sectors)["sector"].tolist()

    def best_per_sector(sectors, ascending=False):
        rows = []
        for sec in sectors:
            grp = stock_30d[stock_30d["sector"] == sec]
            if grp.empty:
                continue
            pick = grp.sort_values("perf_pct", ascending=ascending).iloc[0]
            rank = sector_df.loc[sector_df["sector"] == sec, "rank"].values[0]
            rows.append({
                "Sector Rank":   int(rank),
                "Sector":        sec,
                "Symbol":        pick["symbol"],
                "30d Perf %":    pick["perf_pct"],
                "Latest Close":  round(pick["latest_close"], 2),
            })
        return pd.DataFrame(rows)

    long_df  = best_per_sector(top_sectors,    ascending=False)
    short_df = best_per_sector(bottom_sectors, ascending=True)

    return long_df, short_df


# ---------------------------------------------------------------------------
# ATR% and price-action helpers
# ---------------------------------------------------------------------------

def compute_atr_pct(closes: list, period: int = 14) -> float:
    """Average absolute daily % change over `period` days — close-only ATR proxy."""
    if len(closes) < 2:
        return 0.0
    changes = [
        abs(closes[i] - closes[i - 1]) / closes[i - 1] * 100
        for i in range(max(1, len(closes) - period), len(closes))
    ]
    return round(sum(changes) / len(changes), 2) if changes else 0.0



# ---------------------------------------------------------------------------
# Support Reversal Detection
# ---------------------------------------------------------------------------

def generate_support_reversal_setups(
    raw_prices: pd.DataFrame,
    sector_map: dict,
    breadth: dict = None,
    sector_rank_map: dict = None,
) -> list[dict]:
    """
    Detect support reversal setups on latest candle:
    - 200-MA uptrend: close > 200-MA × 1.01
    - Recovery ratio > 75%: (Close - Low) / (High - Low) > 0.75
    - Lower wick ratio > 60%: (min(Open,Close) - Low) / (High - Low) > 0.60
    - Low touches pivot support level (within 1 point)
    - Entry: high + 1 point
    - Stop loss: entry × 0.94 (-6%)
    - Trailing stop: trail by 2% from peak
    - ML prediction: includes kiran_model features for quality scoring

    Returns list of setup dicts with source='Support Reversal'
    """
    from datetime import date as date_cls

    if raw_prices.empty:
        return []

    rp = raw_prices.copy()
    rp["date"] = pd.to_datetime(rp["date"])

    setups = []
    today_str = date_cls.today().isoformat()

    # Defaults
    breadth = breadth or {}
    sector_rank_map = sector_rank_map or {}
    breadth_score = breadth.get("breadth_score", 50)

    # Group by symbol
    for symbol, grp in rp.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)

        # Need at least 200 bars for 200-MA + some history for support calc
        if len(grp) < 210:
            continue

        # Calculate 200-day SMA
        grp["ma200"] = grp["close"].rolling(200, min_periods=1).mean()
        grp["atr"] = compute_atr_pct(grp["close"].tolist())

        # Get latest candle (most recent)
        latest_idx = len(grp) - 1
        latest = grp.iloc[latest_idx]

        close = latest["close"]
        open_p = latest.get("open", close)
        high = latest.get("high", close)
        low = latest.get("low", close)
        ma200 = latest["ma200"]
        atr_pct = latest.get("atr", 0)

        # Skip if missing OHLC
        if pd.isna([close, high, low, ma200]).any():
            continue

        # Skip if high == low (no range)
        if high == low:
            continue

        # ── 200-MA Uptrend Filter ──
        if close <= ma200 * 1.01:
            continue  # Not in uptrend

        # ── Recovery Ratio > 75% ──
        recovery_ratio = (close - low) / (high - low)
        if recovery_ratio <= 0.75:
            continue  # Not enough recovery

        # ── Lower Wick Ratio > 60% ──
        wick_bottom = min(open_p, close)
        lower_wick_ratio = (wick_bottom - low) / (high - low)
        if lower_wick_ratio <= 0.60:
            continue  # Not strong rejection

        # ── Pivot Support Detection ──
        # Need previous day's OHLC for pivot calculation
        if latest_idx < 1:
            continue

        prev = grp.iloc[latest_idx - 1]
        prev_high = prev.get("high", prev["close"])
        prev_low = prev.get("low", prev["close"])
        prev_close = prev["close"]

        if pd.isna([prev_high, prev_low, prev_close]).any():
            continue

        # Pivot point calculation
        # Pivot = (H + L + C) / 3
        # Support1 = (Pivot × 2) - H
        pivot = (prev_high + prev_low + prev_close) / 3
        support1 = (pivot * 2) - prev_high

        # Low must touch support within 1 point tolerance
        # Assuming PSX prices typically 20-500, 1 point = 1 unit
        if low > support1 + 1:
            continue  # Low didn't touch support

        # ── Calculate stock performance (for ML features) ──
        # 30-day performance
        if latest_idx >= 30:
            close_30d_ago = grp.iloc[max(0, latest_idx - 30)]["close"]
            stock_perf_30d = ((close - close_30d_ago) / close_30d_ago * 100) if close_30d_ago > 0 else 0
        else:
            stock_perf_30d = 0

        # 10-day performance
        if latest_idx >= 10:
            close_10d_ago = grp.iloc[max(0, latest_idx - 10)]["close"]
            stock_perf_10d = ((close - close_10d_ago) / close_10d_ago * 100) if close_10d_ago > 0 else 0
        else:
            stock_perf_10d = 0

        # 10-day average volume
        vol_slice = grp.iloc[max(0, latest_idx - 10):latest_idx + 1].get("volume", pd.Series([0] * 11))
        avg_vol_10d = vol_slice.mean() if len(vol_slice) > 0 else 0

        # ── Entry & Stop Loss ──
        entry = high + 1.0
        stop_loss = entry * 0.94  # -6% hard stop
        risk_pct = ((entry - stop_loss) / entry) * 100

        # Get sector
        sector = sector_map.get(symbol, "Unknown")
        sector_rank = sector_rank_map.get(sector, 12)  # Default to middle rank

        setups.append({
            "created_date":     today_str,
            "direction":        "LONG",
            "symbol":           symbol,
            "sector":           sector,
            "sector_momentum":  "—",  # Not computed for this pattern
            "stock_perf_30d":   round(stock_perf_30d, 2),
            "stock_perf_10d":   round(stock_perf_10d, 2),
            "latest_close":     close,
            "support_level":    round(support1, 2),
            "resistance_level": None,
            "entry_price":      round(entry, 2),
            "stop_loss":        round(stop_loss, 2),
            "target_1r":        round(entry + (entry - stop_loss), 2),
            "target_2r":        round(entry + 2 * (entry - stop_loss), 2),
            "risk_pct":         round(risk_pct, 2),
            "atr_pct":          round(atr_pct, 2),
            "status":           "Pending",
            "notes":            f"Recovery {recovery_ratio:.1%} | Wick {lower_wick_ratio:.1%} | 200-MA {ma200:.2f}",
            "quality_score":    (
                (1 if recovery_ratio > 0.75 else 0) +
                (1 if lower_wick_ratio > 0.60 else 0) +
                (1 if close > ma200 * 1.01 else 0)
            ),
            "quality_checks":   {
                "Recovery > 75%": recovery_ratio > 0.75,
                "Wick > 60%": lower_wick_ratio > 0.60,
                "200-MA uptrend": close > ma200 * 1.01,
            },
            "range_width_pct":  None,
            "range_window":     None,
            "sector_rank":      int(sector_rank),
            "breadth_score":    breadth_score,
            "avg_vol_10d":      round(avg_vol_10d),
            "source":           "Support Reversal",
        })

    return setups


# ---------------------------------------------------------------------------
# Main analysis entry point
# ---------------------------------------------------------------------------

def run_analysis() -> dict:
    """
    Full pipeline analysis.  Returns a dict with keys:
        stock_30d, stock_10d, sector_df, breadth, kse100,
        long_candidates, short_candidates
    """
    raw = get_sector_price_data()
    if not raw:
        logger.warning("No price data in database — run initial load first.")
        return {}

    df = pd.DataFrame(raw)
    df = df[~df["sector"].isin(EXCLUDED_SECTORS)]

    stock_30d  = compute_stock_performance(df, window=30)
    stock_10d  = compute_stock_performance(df, window=10)
    sector_df  = compute_sector_rankings(stock_30d, stock_10d)
    breadth    = compute_market_breadth(stock_30d, sector_df)
    long_c, short_c = compute_trade_candidates(stock_30d, sector_df)

    # KSE-100 50-day MA trend filter — shared between live screener and dashboard display
    kse_filter  = KSE100Filter()
    kse_summary = kse_filter.kse100_summary()
    logger.info(
        "KSE-100: close=%.0f  MA50=%s  above_MA50=%s",
        kse_summary.get("close", 0),
        kse_summary.get("ma50", "n/a"),
        kse_summary.get("above_ma50"),
    )

    # Generate support reversal setups
    sector_map = dict(zip(df["symbol"], df["sector"]))
    sector_rank_map = dict(zip(sector_df["sector"], sector_df["rank"]))
    support_setups = generate_support_reversal_setups(
        df, sector_map, breadth=breadth, sector_rank_map=sector_rank_map
    )
    logger.info(f"Generated {len(support_setups)} support reversal setups")

    return {
        "stock_30d":        stock_30d,
        "stock_10d":        stock_10d,
        "sector_df":        sector_df,
        "breadth":          breadth,
        "kse100":           kse_summary,
        "long_candidates":  long_c,
        "short_candidates": short_c,
        "support_reversal_setups": support_setups,
    }


# ---------------------------------------------------------------------------
# CLI report
# ---------------------------------------------------------------------------

def print_sector_report(sector_df: pd.DataFrame):
    if sector_df.empty:
        print("No data available. Run: python main.py --init")
        return

    print("\n" + "=" * 90)
    print(f"{'PSX SECTOR PERFORMANCE — 30-DAY ROLLING WINDOW':^90}")
    print("=" * 90)
    print(
        f"{'Rank':<5} {'Sector':<38} {'30d%':>7} {'10d%':>7} "
        f"{'Momentum':<14} {'Stocks':>6} {'Best%':>7} {'Worst%':>7}"
    )
    print("-" * 90)

    for _, row in sector_df.iterrows():
        sign = "+" if row["avg_perf_pct"] >= 0 else ""
        d10  = f"{row['avg_10d_pct']:+.2f}" if row["avg_10d_pct"] is not None else "  —  "
        print(
            f"{int(row['rank']):<5} {row['sector']:<38} "
            f"{sign}{row['avg_perf_pct']:>6.2f}% "
            f"{d10:>7}% "
            f"{row['momentum']:<14} "
            f"{int(row['stock_count']):>6} "
            f"{row['best_perf_pct']:>+7.2f}% "
            f"{row['worst_perf_pct']:>+7.2f}%"
        )

    print("=" * 90)
