"""
Signal Screener Engine — 4-Condition Trade Signals
===================================================
LONG (all 4 required):
  1. Close above a RISING 200-EMA
  2. Price inside a confirmed SR support channel
  3. HH + HL market structure (latest pivots show higher highs and higher lows)
  4. Bullish candle: Engulfing / Marubozu / Hammer
  Volume gate: 10-day avg volume >= 100,000 shares

SHORT (all 4 required — DFC symbols only):
  1. Close below a FALLING 200-EMA
  2. Price inside a confirmed SR resistance channel
  3. LH + LL market structure
  4. Bearish candle: Engulfing / Marubozu / Inverted Hammer
  Volume gate: 10-day avg volume >= 100,000 shares
  DFC gate: symbol must be in config.DFC_SYMBOLS

SR Channel translated from "Support Resistance Channels" by LonesomeTheBlue (Pine Script v6).
Market structure translated from standard pivot-sequence HH/HL/LH/LL detection.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

import database as db
from config import DFC_SYMBOLS

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
EMA_PERIOD    = 200
# Need 300 bars for SR channel touch counting + 10-bar pivot right-side buffer
MIN_BARS      = 315
MIN_VOL_10D   = 100_000   # 10-day avg volume gate (both directions)

# SR channel defaults (match Pine Script inputs)
SR_PRD         = 10    # pivot left/right period
SR_CHANNEL_W   = 5     # max channel width as % of 300-bar range
SR_MIN_STR     = 1     # minimum strength (×20 = 20 min combined score)
SR_LOOPBACK    = 290   # bars back to search for pivots
SR_MAX_CHANS   = 6     # number of top channels to keep

# Pivot period for market structure (matches Pine Script Pivot Points HL)
MS_LEFT  = 10
MS_RIGHT = 10


# ══════════════════════════════════════════════════════════════════════════════
# PIVOT DETECTION  (matches Pine Script ta.pivothigh / ta.pivotlow)
# ══════════════════════════════════════════════════════════════════════════════

def _pivot_highs(src: np.ndarray, left: int, right: int) -> list[tuple[int, float]]:
    """
    Return (bar_index, value) for every confirmed pivot high in `src`.
    Pivot high at i: src[i] is the strict maximum of src[i-left : i+right+1].
    Array must be sorted oldest-first (index 0 = oldest).
    """
    n = len(src)
    result = []
    for i in range(left, n - right):
        window = src[i - left : i + right + 1]
        if src[i] == window.max() and (window == src[i]).sum() == 1:
            result.append((i, float(src[i])))
    return result


def _pivot_lows(src: np.ndarray, left: int, right: int) -> list[tuple[int, float]]:
    """
    Return (bar_index, value) for every confirmed pivot low in `src`.
    Pivot low at i: src[i] is the strict minimum of src[i-left : i+right+1].
    """
    n = len(src)
    result = []
    for i in range(left, n - right):
        window = src[i - left : i + right + 1]
        if src[i] == window.min() and (window == src[i]).sum() == 1:
            result.append((i, float(src[i])))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SR CHANNEL  (Python translation of LonesomeTheBlue's Pine Script v6)
# ══════════════════════════════════════════════════════════════════════════════

def compute_sr_channels(
    df: pd.DataFrame,
    prd: int       = SR_PRD,
    channel_w: int = SR_CHANNEL_W,
    min_str: int   = SR_MIN_STR,
    loopback: int  = SR_LOOPBACK,
    max_chans: int = SR_MAX_CHANS,
) -> list[dict]:
    """
    Compute top SR channels for the symbol.

    Returns a list of dicts: {'hi': float, 'lo': float, 'strength': int}
    sorted strongest-first, up to max_chans entries.

    Input df must have columns: high, low, close — sorted oldest-first.
    """
    n = len(df)
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)

    # ── Pivot detection ───────────────────────────────────────────────────────
    ph_list = _pivot_highs(highs, prd, prd)   # (idx, val)
    pl_list = _pivot_lows(lows,   prd, prd)

    # Keep only pivots within loopback bars from the last bar
    all_pivots = [
        (idx, val)
        for idx, val in ph_list + pl_list
        if (n - 1 - idx) <= loopback
    ]
    if not all_pivots:
        return []

    # Sort newest-first (mirrors Pine's array.unshift order)
    all_pivots.sort(key=lambda x: x[0], reverse=True)
    pivot_vals = np.array([v for _, v in all_pivots])
    pivot_idxs = [i for i, _ in all_pivots]

    # ── Channel width = ChannelW% of the 300-bar range ────────────────────────
    lookback_300 = min(300, n)
    cwidth = (highs[-lookback_300:].max() - lows[-lookback_300:].min()) * channel_w / 100
    if cwidth <= 0:
        return []

    # ── Build one channel per pivot (get_sr_vals equivalent) ─────────────────
    np_count = len(pivot_vals)
    channels: list[dict] = []

    for i in range(np_count):
        lo = hi = pivot_vals[i]
        numpp = 0
        for j in range(np_count):
            cpp = pivot_vals[j]
            wdth = (hi - cpp) if cpp <= hi else (cpp - lo)
            if wdth <= cwidth:
                if cpp <= hi:
                    lo = min(lo, cpp)
                else:
                    hi = max(hi, cpp)
                numpp += 20
        channels.append({"hi": hi, "lo": lo, "strength": numpp})

    # ── Touch-strength bonus (high or low inside channel for past loopback bars)
    for ch in channels:
        chi, clo = ch["hi"], ch["lo"]
        s = 0
        start = max(0, n - loopback)
        h_slice = highs[start:]
        l_slice = lows[start:]
        mask = ((h_slice <= chi) & (h_slice >= clo)) | ((l_slice <= chi) & (l_slice >= clo))
        s = int(mask.sum())
        ch["strength"] += s

    # ── Greedy selection: pick strongest non-overlapping channels ─────────────
    threshold = min_str * 20
    used      = [False] * np_count
    selected: list[dict] = []

    for _ in range(max_chans):
        best_str, best_idx = -1, -1
        for i in range(np_count):
            if not used[i] and channels[i]["strength"] >= threshold:
                if channels[i]["strength"] > best_str:
                    best_str = channels[i]["strength"]
                    best_idx = i
        if best_idx < 0:
            break

        chosen = channels[best_idx]
        selected.append(chosen)

        # Nullify all channels that overlap with the chosen one
        for i in range(np_count):
            if not used[i]:
                ci = channels[i]
                if (ci["hi"] <= chosen["hi"] and ci["hi"] >= chosen["lo"]) or \
                   (ci["lo"] <= chosen["hi"] and ci["lo"] >= chosen["lo"]):
                    used[i] = True
        used[best_idx] = True

    # Sort strongest-first (mirrors Pine's final sort)
    selected.sort(key=lambda x: x["strength"], reverse=True)
    return selected


def _pullback_to_support(df: pd.DataFrame, channels: list[dict], lookback: int = 20) -> bool:
    """
    True when price has genuinely pulled back INTO a support channel from above.

    Criteria for a valid pullback:
      1. The latest close is inside the channel band [lo, hi].
      2. At least one close within the last `lookback` bars was ABOVE channel hi
         (confirming price was above that level before pulling back into it).

    This rejects stocks that are merely rising INTO a channel from below
    (breakout / first touch from underneath).
    """
    recent_closes = df["close"].iloc[-lookback:].values
    latest_close  = float(df["close"].iloc[-1])

    for ch in channels:
        if ch["lo"] <= latest_close <= ch["hi"]:
            # Was price above this channel at any point in the lookback window?
            if (recent_closes > ch["hi"]).any():
                return True
    return False


def _pullback_to_resistance(df: pd.DataFrame, channels: list[dict], lookback: int = 20) -> bool:
    """
    True when price has genuinely pulled back INTO a resistance channel from below.

    Criteria:
      1. The latest close is inside the channel band [lo, hi].
      2. At least one close within the last `lookback` bars was BELOW channel lo
         (confirming price was below the channel before rallying back into it).

    This rejects stocks that are merely falling INTO a channel from above.
    """
    recent_closes = df["close"].iloc[-lookback:].values
    latest_close  = float(df["close"].iloc[-1])

    for ch in channels:
        if ch["lo"] <= latest_close <= ch["hi"]:
            if (recent_closes < ch["lo"]).any():
                return True
    return False


def check_support_channel(df: pd.DataFrame) -> bool:
    """
    LONG condition 2 — price has pulled back into a defined support channel.

    A valid pullback requires the close to be inside a channel band AND
    price to have been above that band recently (came from above, not below).
    """
    channels = compute_sr_channels(df)
    if not channels:
        return False
    return _pullback_to_support(df, channels)


def check_resistance_channel(df: pd.DataFrame) -> bool:
    """
    SHORT condition 2 — price has pulled back into a defined resistance channel.

    A valid pullback requires the close to be inside a channel band AND
    price to have been below that band recently (rallied from below, not above).
    """
    channels = compute_sr_channels(df)
    if not channels:
        return False
    return _pullback_to_resistance(df, channels)


# ══════════════════════════════════════════════════════════════════════════════
# MARKET STRUCTURE  (pivot sequence HH/HL and LH/LL)
# ══════════════════════════════════════════════════════════════════════════════

def check_hh_hl_structure(df: pd.DataFrame) -> tuple[bool, str]:
    """
    LONG condition 3 — at least one confirmed Higher High (HH) and one
    confirmed Higher Low (HL) in the current move.

    Uses ta.pivothigh/ta.pivotlow equivalent with left=right=10.
    Requires at least 2 confirmed pivot highs and 2 confirmed pivot lows.
    HH: most recent pivot high > previous pivot high.
    HL: most recent pivot low  > previous pivot low.
    """
    ph = _pivot_highs(df["high"].values.astype(float), MS_LEFT, MS_RIGHT)
    pl = _pivot_lows( df["low"].values.astype(float),  MS_LEFT, MS_RIGHT)

    if len(ph) < 2 or len(pl) < 2:
        return False, ""

    hh = ph[-1][1] > ph[-2][1]   # latest pivot high > previous pivot high
    hl = pl[-1][1] > pl[-2][1]   # latest pivot low  > previous pivot low

    if hh and hl:
        return True, "HH+HL"
    if hh:
        return False, "HH only"
    if hl:
        return False, "HL only"
    return False, "No bullish structure"


def check_lh_ll_structure(df: pd.DataFrame) -> tuple[bool, str]:
    """
    SHORT condition 3 — at least one confirmed Lower High (LH) and one
    confirmed Lower Low (LL) in the current move.

    LH: most recent pivot high < previous pivot high.
    LL: most recent pivot low  < previous pivot low.
    """
    ph = _pivot_highs(df["high"].values.astype(float), MS_LEFT, MS_RIGHT)
    pl = _pivot_lows( df["low"].values.astype(float),  MS_LEFT, MS_RIGHT)

    if len(ph) < 2 or len(pl) < 2:
        return False, ""

    lh = ph[-1][1] < ph[-2][1]
    ll = pl[-1][1] < pl[-2][1]

    if lh and ll:
        return True, "LH+LL"
    if lh:
        return False, "LH only"
    if ll:
        return False, "LL only"
    return False, "No bearish structure"


# ══════════════════════════════════════════════════════════════════════════════
# CANDLESTICK PATTERN DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_bullish_pattern(df: pd.DataFrame) -> Optional[str]:
    """
    Check the last candle for bullish reversal patterns.
    Priority: Bullish Engulfing → Bullish Marubozu → Hammer.
    Returns pattern name or None.
    """
    if len(df) < 2:
        return None
    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    o,  h,  l,  c  = float(c0["open"]), float(c0["high"]), float(c0["low"]),  float(c0["close"])
    o1, h1, l1, c1v = float(c1["open"]), float(c1["high"]), float(c1["low"]), float(c1["close"])

    full_range = h - l
    if full_range <= 0:
        return None
    body = abs(c - o)
    uw   = h - max(o, c)
    lw   = min(o, c) - l

    # Bullish Engulfing: prev bearish, current bullish, body engulfs prev body
    if c1v < o1 and c > o:
        if o <= c1v and c >= o1:
            return "Bullish Engulfing"

    # Bullish Marubozu: bullish candle, body >= 95% of range
    if c > o and body / full_range >= 0.95:
        return "Bullish Marubozu"

    # Hammer: lower wick >= 2× body, upper wick <= 0.5× body, lw >= 60% of range
    if body > 0 and lw >= 2 * body and uw <= 0.5 * body and lw >= 0.6 * full_range:
        return "Hammer"

    return None


def detect_bearish_pattern(df: pd.DataFrame) -> Optional[str]:
    """
    Check the last candle for bearish reversal patterns.
    Priority: Bearish Engulfing → Bearish Marubozu → Inverted Hammer.
    Returns pattern name or None.
    """
    if len(df) < 2:
        return None
    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    o,  h,  l,  c  = float(c0["open"]), float(c0["high"]), float(c0["low"]),  float(c0["close"])
    o1, h1, l1, c1v = float(c1["open"]), float(c1["high"]), float(c1["low"]), float(c1["close"])

    full_range = h - l
    if full_range <= 0:
        return None
    body = abs(c - o)
    uw   = h - max(o, c)
    lw   = min(o, c) - l

    # Bearish Engulfing: prev bullish, current bearish, body engulfs prev body
    if c1v > o1 and c < o:
        if o >= c1v and c <= o1:
            return "Bearish Engulfing"

    # Bearish Marubozu: bearish candle, body >= 95% of range
    if c < o and body / full_range >= 0.95:
        return "Bearish Marubozu"

    # Inverted Hammer: upper wick >= 2× body, lower wick <= 0.5× body, uw >= 60% of range
    if body > 0 and uw >= 2 * body and lw <= 0.5 * body and uw >= 0.6 * full_range:
        return "Inverted Hammer"

    return None


# ══════════════════════════════════════════════════════════════════════════════
# EMA HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADER
# ══════════════════════════════════════════════════════════════════════════════

def load_bulk_ohlcv(lookback: int = MIN_BARS) -> dict[str, pd.DataFrame]:
    """
    Fetch the last `lookback` OHLCV bars for every symbol in the sectors table.
    Single SQL round-trip using a window function.
    Returns {symbol: DataFrame} sorted oldest-first.
    """
    sql = """
        WITH ranked AS (
            SELECT
                p.symbol,
                p.date,
                p.open,
                p.high,
                p.low,
                p.close,
                p.volume,
                ROW_NUMBER() OVER (PARTITION BY p.symbol ORDER BY p.date DESC) AS rn
            FROM prices p
            INNER JOIN sectors s ON p.symbol = s.symbol
        )
        SELECT symbol, date, open, high, low, close, volume
        FROM   ranked
        WHERE  rn <= ?
        ORDER BY symbol, date
    """
    with db.get_conn() as conn:
        rows = conn.execute(sql, (lookback,)).fetchall()

    if not rows:
        return {}

    df_all = pd.DataFrame([dict(r) for r in rows])
    df_all["date"]   = pd.to_datetime(df_all["date"])
    for col in ("open", "high", "low", "close"):
        df_all[col] = pd.to_numeric(df_all[col], errors="coerce")
    df_all["volume"] = pd.to_numeric(df_all["volume"], errors="coerce").fillna(0)

    result: dict[str, pd.DataFrame] = {}
    for sym, grp in df_all.groupby("symbol", sort=False):
        result[sym] = grp.sort_values("date").reset_index(drop=True)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PER-SYMBOL EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_symbol(symbol: str, df: pd.DataFrame) -> Optional[dict]:
    """
    Run all conditions for LONG and SHORT on one symbol.
    Returns a signal dict or None.
    """
    if len(df) < MIN_BARS:
        return None

    closes = df["close"]

    # ── Volume gate (10-day average) ──────────────────────────────────────────
    avg_vol_10d = df["volume"].iloc[-10:].mean()
    if avg_vol_10d < MIN_VOL_10D:
        return None

    # ── Condition 1 — 200-EMA direction ──────────────────────────────────────
    ema_s      = _ema(closes, EMA_PERIOD)
    ema_now    = float(ema_s.iloc[-1])
    ema_prev   = float(ema_s.iloc[-2])
    latest_close = float(closes.iloc[-1])

    ema_rising  = ema_now > ema_prev
    above_ema   = latest_close > ema_now
    below_ema   = latest_close < ema_now

    # ── LONG path ─────────────────────────────────────────────────────────────
    if above_ema and ema_rising:
        if check_support_channel(df):
            struct_ok, struct_label = check_hh_hl_structure(df)
            if struct_ok:
                pattern = detect_bullish_pattern(df)
                if pattern:
                    return {
                        "symbol":        symbol,
                        "signal":        "LONG",
                        "latest_close":  round(latest_close, 2),
                        "ema_200":       round(ema_now, 2),
                        "ema_direction": "Rising",
                        "pattern":       pattern,
                        "structure":     struct_label,
                        "avg_vol_10d":   int(avg_vol_10d),
                    }

    # ── SHORT path (DFC symbols only) ─────────────────────────────────────────
    if below_ema and (not ema_rising) and (symbol in DFC_SYMBOLS):
        if check_resistance_channel(df):
            struct_ok, struct_label = check_lh_ll_structure(df)
            if struct_ok:
                pattern = detect_bearish_pattern(df)
                if pattern:
                    return {
                        "symbol":        symbol,
                        "signal":        "SHORT",
                        "latest_close":  round(latest_close, 2),
                        "ema_200":       round(ema_now, 2),
                        "ema_direction": "Falling",
                        "pattern":       pattern,
                        "structure":     struct_label,
                        "avg_vol_10d":   int(avg_vol_10d),
                    }

    return None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def run_screener() -> list[dict]:
    """
    Scan every symbol in the sectors table.
    Returns a list of signal dicts for stocks passing all four conditions.
    """
    ohlcv_map = load_bulk_ohlcv(lookback=MIN_BARS)
    if not ohlcv_map:
        logger.warning("screener_signals: no OHLCV data returned")
        return []

    signals: list[dict] = []
    for symbol, df in ohlcv_map.items():
        try:
            result = evaluate_symbol(symbol, df)
            if result:
                signals.append(result)
        except Exception as exc:
            logger.debug("screener_signals: skipped %s — %s", symbol, exc)

    signals.sort(key=lambda x: (x["signal"], x["symbol"]))
    return signals
