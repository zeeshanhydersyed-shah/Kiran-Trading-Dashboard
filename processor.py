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


def _find_consolidation(closes: list, highs: list = None, lows: list = None,
                        windows=(5, 7, 10), max_range_pct=12.0) -> dict | None:
    """
    Scan windows shortest → longest. Return the tightest qualifying window or None.

    Resistance = highest HIGH over the full window (candle wick — captures the real ceiling)
    Support    = lowest  LOW  over last 10 bars only (recent pivot low — avoids stale
                 crash wicks from weeks ago anchoring risk too wide)

    Splitting the lookback this way mirrors how a trader reads a chart:
      - Resistance level: wherever price was rejected in the whole base
      - Stop-loss level: just below the most recent swing low, not the all-time dip
      - This prevents the May-9 panic low from bloating risk calculations through July

    Falls back to close-based hi/lo when H/L data isn't yet available (legacy rows).
    """
    SUPPORT_BARS = 10   # only last N bars for support (recent swing low)

    best = None
    n = len(closes)
    use_hl = (highs and lows and len(highs) == n and len(lows) == n
              and any(h != c for h, c in zip(highs, closes)))

    for w in sorted(windows):
        if n < w + 1:
            continue
        recent_c = closes[-w:]

        # Resistance over the full window — where price has been rejected
        res = max(highs[-w:]) if use_hl else max(recent_c)

        # Support over only the most recent SUPPORT_BARS — the current swing low
        sup_bars = min(w, SUPPORT_BARS)
        sup = min(lows[-sup_bars:]) if use_hl else min(closes[-sup_bars:])

        if sup == 0:
            continue
        width = (res - sup) / sup * 100
        if width <= max_range_pct:
            if best is None or width < best["range_width"]:
                best = {
                    "window":      w,
                    "support":     round(sup, 2),
                    "resistance":  round(res, 2),
                    "range_width": round(width, 2),
                    "closes":      recent_c,
                }
    return best


def _count_resistance_tests(closes: list, resistance: float, tol_pct=2.0) -> int:
    """Days price came within tol_pct% of resistance WITHOUT closing above it."""
    lo = resistance * (1 - tol_pct / 100)
    return sum(1 for c in closes if lo <= c <= resistance)


def _count_support_tests(closes: list, support: float, tol_pct=2.0) -> int:
    """Days price came within tol_pct% of support WITHOUT closing below it."""
    hi = support * (1 + tol_pct / 100)
    return sum(1 for c in closes if support <= c <= hi)


def _has_declining_highs(closes: list) -> bool:
    """Second-half rolling high < first-half → coiling compression (bullish)."""
    if len(closes) < 4:
        return False
    mid = len(closes) // 2
    return max(closes[:mid]) > max(closes[mid:])


def _has_rising_lows(closes: list) -> bool:
    """Second-half rolling low > first-half → trapped sellers (bearish squeeze)."""
    if len(closes) < 4:
        return False
    mid = len(closes) // 2
    return min(closes[:mid]) < min(closes[mid:])


def _has_volatility_contraction(closes: list) -> bool:
    """ATR of last 5 days < ATR of prior 9 days."""
    if len(closes) < 7:
        return False

    def _atr(cs):
        ch = [abs(cs[i] - cs[i - 1]) / cs[i - 1] * 100 for i in range(1, len(cs))]
        return sum(ch) / len(ch) if ch else 0.0

    recent = _atr(closes[-6:])                                         # last 5 moves
    prior  = _atr(closes[-15:-5]) if len(closes) >= 15 else _atr(closes[:-5])
    return recent < prior


def _range_position(close: float, support: float, resistance: float) -> float:
    """0 = at support, 1 = at resistance."""
    rng = resistance - support
    return (close - support) / rng if rng else 0.5


# ---------------------------------------------------------------------------
# Trade setup generator
# ---------------------------------------------------------------------------

def generate_trade_setups(
    stock_30d: pd.DataFrame,
    stock_10d: pd.DataFrame,
    sector_df: pd.DataFrame,
    raw_prices: pd.DataFrame,
    breadth: dict,
    max_risk_pct: float = 12.0,      # raised from 6% — PSX large-caps need room (OGDC/DGKC style bases)
    reward_ratio: float = 2.0,
    max_range_pct: float = 12.0,
    min_quality: int = 2,
    entry_buffer_pct: float = 0.5,   # entry placed this % beyond the breakout/breakdown level
    sl_buffer_pct: float = 1.0,      # SL placed this % beyond the opposite wall of the range
    min_vol_10d: float = 500_000,    # 10-day avg volume floor — keeps illiquid stocks out
    kse_filter: "KSE100Filter | None" = None,  # KSE-100 50-day MA gate for LONGs
) -> list[dict]:
    """
    Top-down setup screener — range breakout/breakdown edition.

    Entry & SL placement (range-based, not ATR-based):
    ─────────────────────────────────────────────────────
    LONG  : entry  = resistance + entry_buffer%   (above current price — buy-stop)
             SL    = support    - sl_buffer%       (below the range floor — thesis broken
                                                    only if price traverses entire range)
    SHORT : entry  = support    - entry_buffer%   (below current price — sell-stop)
             SL    = resistance + sl_buffer%       (above the range ceiling — thesis broken
                                                    only if price traverses entire range)

    Guardrails:
    • LONG  entry must be > latest close  (never chase a breakout already in progress)
    • SHORT entry must be < latest close  (never chase a breakdown already in progress)
    • Risk (entry→SL) ≤ max_risk_pct — effectively caps max range width at ~4-5%

    ATR is still computed and reported (shows daily noise level) but is NOT used to
    place the SL, because an ATR-based SL sits inside the range and causes whipsaw.

    Hard filters:
    LONG  : KSE-100 ≥ 50-day MA, breadth ≥ 55, sector top 35%,
            momentum Heating Up/Cooling Down, 30d ≥ 15%
    SHORT : DFC-eligible, sector bottom 35%, momentum Rolling Over/Falling,
            10d < 0, (30d ≤ -15% OR 30d < 0 with 10d ≤ -10%)

    Quality score (0-4 per direction): min_quality to appear.
    """
    from datetime import date as date_cls

    SHORT_MOM = {"Rolling Over", "Falling"}
    LONG_MOM  = {"Heating Up", "Cooling Down"}

    total   = len(sector_df)
    top_cut = max(1, int(total * 0.35))           # e.g. top 8 of 23
    bot_cut = total - max(1, int(total * 0.35))   # e.g. bottom 8 of 23

    b_score  = breadth.get("breadth_score", 0) if breadth else 0
    sec_mom  = dict(zip(sector_df["sector"], sector_df["momentum"]))
    sec_rank = dict(zip(sector_df["sector"], sector_df["rank"]))

    p10_map = ({r["symbol"]: r["perf_pct"] for _, r in stock_10d.iterrows()}
               if not stock_10d.empty else {})

    # 60-day performance — computed directly from price_map after it is built below
    # (populated in the loop via closes list — avoids a second DB call)

    price_map: dict[str, list] = {}
    high_map:  dict[str, list] = {}
    low_map:   dict[str, list] = {}
    vol_map:   dict[str, float] = {}   # 10-day average volume per symbol
    if not raw_prices.empty:
        rp = raw_prices.copy()
        rp["date"] = pd.to_datetime(rp["date"])
        for sym, grp in rp.groupby("symbol"):
            g = grp.sort_values("date")
            price_map[sym] = g["close"].tolist()
            high_map[sym]  = g["high"].tolist()   if "high"   in g.columns else []
            low_map[sym]   = g["low"].tolist()    if "low"    in g.columns else []
            if "volume" in g.columns:
                vols = g["volume"].tolist()
                vol_map[sym] = float(sum(vols[-10:])) / max(len(vols[-10:]), 1)

    today_str = date_cls.today().isoformat()
    setups: list[dict] = []

    eb = entry_buffer_pct / 100   # fractional entry buffer
    sb = sl_buffer_pct    / 100   # fractional SL buffer

    for _, row in stock_30d.iterrows():
        sym    = row["symbol"]
        sector = row["sector"]
        p30    = row["perf_pct"]
        p10    = p10_map.get(sym)
        s_mom  = sec_mom.get(sector, "—")
        s_rank = sec_rank.get(sector, 999)
        closes   = price_map.get(sym, [])
        highs    = high_map.get(sym, [])
        lows     = low_map.get(sym, [])
        avg_vol  = vol_map.get(sym, 0.0)

        if p10 is None or len(closes) < 7:
            continue

        # Volume filter — skip thinly traded stocks (same threshold as backtest)
        if avg_vol < min_vol_10d:
            continue

        atr    = compute_atr_pct(closes)
        latest = closes[-1]

        # 60-day performance from raw price series (point-in-time correct)
        p60 = ((closes[-1] - closes[-61]) / closes[-61] * 100
               if len(closes) >= 61 else None)

        # LONG momentum gate: 30d ≥ 15% catches trending stocks.
        # 60d ≥ 20% catches post-spike bases (e.g. OGDC/DGKC) where the stock
        # ran hard 2 months ago, consolidated flat, and the 30d return is muted.
        perf_ok_long = (p30 >= 15.0) or (p60 is not None and p60 >= 20.0)

        # KSE-100 trend gate — only go long when index is above its 50-day MA.
        # If filter is unavailable, default to True (no suppression).
        kse_long_ok = kse_filter.long_allowed() if kse_filter is not None else True

        # ── LONG ──────────────────────────────────────────────────────────
        if (kse_long_ok
                and b_score >= 55
                and s_rank <= top_cut
                and s_mom in LONG_MOM
                and perf_ok_long):

            consol = _find_consolidation(closes, highs, lows, max_range_pct=max_range_pct)
            if not consol:
                continue

            resistance = consol["resistance"]
            support    = consol["support"]

            # Entry is a buy-stop above resistance — must be above latest close
            entry = round(resistance * (1 + eb), 2)
            if entry <= latest:
                continue        # price already at or past breakout level — skip

            # SL below the range floor — a full traversal of the range invalidates thesis
            sl       = round(support * (1 - sb), 2)
            risk_pct = round((entry - sl) / entry * 100, 2)
            if not (0 < risk_pct <= max_risk_pct):
                continue

            R  = entry - sl
            cc = consol["closes"]
            pos = _range_position(latest, support, resistance)

            checks = {
                "Resistance tested >=2x": _count_resistance_tests(cc, resistance) >= 2,
                "Declining highs":        _has_declining_highs(cc),
                "Volatility contracting": _has_volatility_contraction(closes),
                "Price pulled back":      0.25 <= pos <= 0.65,
            }
            score = sum(checks.values())
            if score < min_quality:
                continue

            setups.append({
                "created_date":     today_str,
                "direction":        "LONG",
                "symbol":           sym,
                "sector":           sector,
                "sector_rank":      int(s_rank),
                "sector_momentum":  s_mom,
                "stock_perf_30d":   p30,
                "stock_perf_60d":   round(p60, 2) if p60 is not None else None,
                "stock_perf_10d":   p10,
                "latest_close":     latest,
                "support_level":    support,
                "resistance_level": resistance,
                "range_width_pct":  consol["range_width"],
                "range_window":     consol["window"],
                "entry_price":      entry,
                "stop_loss":        sl,
                "target_1r":        round(entry + R, 2),
                "target_2r":        round(entry + reward_ratio * R, 2),
                "risk_pct":         risk_pct,
                "atr_pct":          atr,
                "quality_score":    score,
                "quality_checks":   checks,
                "breadth_score":    b_score,
                "avg_vol_10d":      round(avg_vol),
            })

        # ── SHORT (DFC only) ──────────────────────────────────────────────
        # Primary  : strong prior decline (≥15% down over 30d) — mirrors long requirement
        # Alt      : already negative 30d AND accelerating hard (10d ≤ -10%)
        short_perf_ok = p30 <= -15.0 or (p30 < 0 and p10 <= -10.0)

        if (sym in DFC_SYMBOLS
                and s_rank > bot_cut
                and s_mom in SHORT_MOM
                and p10 < 0
                and short_perf_ok):

            consol = _find_consolidation(closes, highs, lows, max_range_pct=max_range_pct)
            if not consol:
                continue

            resistance = consol["resistance"]
            support    = consol["support"]

            # Entry is a sell-stop below support — must be below latest close
            entry = round(support * (1 - eb), 2)
            if entry >= latest:
                continue        # price already at or past breakdown level — skip

            # SL above the range ceiling — a full traversal of the range invalidates thesis
            sl       = round(resistance * (1 + sb), 2)
            risk_pct = round((sl - entry) / entry * 100, 2)
            if not (0 < risk_pct <= max_risk_pct):
                continue

            R  = sl - entry
            cc = consol["closes"]
            pos = _range_position(latest, support, resistance)

            checks = {
                "Support tested >=2x":   _count_support_tests(cc, support) >= 2,
                "Rising lows":           _has_rising_lows(cc),
                "Volatility contracting":_has_volatility_contraction(closes),
                "Price near resistance": 0.35 <= pos <= 0.75,
            }
            score = sum(checks.values())
            if score < min_quality:
                continue

            setups.append({
                "created_date":     today_str,
                "direction":        "SHORT",
                "symbol":           sym,
                "sector":           sector,
                "sector_rank":      int(s_rank),
                "sector_momentum":  s_mom,
                "stock_perf_30d":   p30,
                "stock_perf_60d":   round(p60, 2) if p60 is not None else None,
                "stock_perf_10d":   p10,
                "latest_close":     latest,
                "support_level":    support,
                "resistance_level": resistance,
                "range_width_pct":  consol["range_width"],
                "range_window":     consol["window"],
                "entry_price":      entry,
                "stop_loss":        sl,
                "target_1r":        round(entry - R, 2),
                "target_2r":        round(entry - reward_ratio * R, 2),
                "risk_pct":         risk_pct,
                "atr_pct":          atr,
                "quality_score":    score,
                "quality_checks":   checks,
                "breadth_score":    b_score,
                "avg_vol_10d":      round(avg_vol),
            })

    shorts = sorted([s for s in setups if s["direction"] == "SHORT"],
                    key=lambda x: (-x["quality_score"], x["stock_perf_10d"]))
    longs  = sorted([s for s in setups if s["direction"] == "LONG"],
                    key=lambda x: (-x["quality_score"], -x["stock_perf_30d"]))
    return longs + shorts


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
            "target_1r":        None,
            "target_2r":        None,
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
        long_candidates, short_candidates, trade_setups
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

    setups = generate_trade_setups(
        stock_30d, stock_10d, sector_df, df, breadth,
        kse_filter=kse_filter,
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
        "trade_setups":     setups,
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
