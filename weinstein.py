"""
Weinstein Market Breadth Indicator for PSX / Kiran.

Entry points
------------
  compute_breadth_series(prices_df)            → pd.Series  (% stocks above 50-MA, per date)
  WeinsteinIndicator(...)                      → indicator object
      .generate_signals(breadth, index_close)  → pd.DataFrame  (z-scores + signal col)
  run_optimizer(breadth, index_close, ...)     → (best_params dict, results_df)
"""

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT PSX-TUNED PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
PSX_DEFAULTS = dict(
    ma_period        = 50,     # 50-day MA for individual stock breadth
    z_lookback       = 252,    # 1-year rolling z-score window
    fast_smoothing   = 5,      # EMA span for fast Z (MACD fast line)
    signal_smoothing = 13,     # EMA span for signal line (MACD slow line)
    buy_threshold    = -1.5,   # z < this = oversold territory
    sell_threshold   = 1.8,    # z > this = overbought territory
    price_ma_period  = 50,     # index MA for price-action confirmation
    slope_period     = 5,      # bars used for slope / ROC calculations
)

# Known PSX macro turning points (approximate month start dates)
# Bottom: Jan 2024 | Stall top: Jan 2025 | Hard top: Jan 2026
PSX_KNOWN_BOTTOMS = ["2024-01-01"]
PSX_KNOWN_TOPS    = ["2025-01-01", "2026-01-01"]


# ─────────────────────────────────────────────────────────────────────────────
# BREADTH SERIES BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def compute_breadth_series(prices_df: pd.DataFrame, ma_period: int = 50) -> pd.Series:
    """
    Given a long-format DataFrame with columns [symbol, date, close],
    returns a date-indexed Series of (% of stocks above their ma_period-day MA).

    Minimum history needed: ma_period + z_lookback (≈ 302 trading days).
    """
    df = prices_df[["symbol", "date", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"])

    # Pivot → wide matrix: rows=dates, cols=symbols
    wide = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    wide = wide.sort_index()

    # Rolling MA per symbol
    ma = wide.rolling(ma_period, min_periods=ma_period).mean()

    # Only count symbols that have both a valid close and a valid MA
    valid = wide.notna() & ma.notna()
    above = valid & (wide > ma)

    pct_above = above.sum(axis=1) / valid.sum(axis=1).replace(0, np.nan) * 100

    pct_above.name = "pct_above_ma"
    return pct_above.dropna()


# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR
# ─────────────────────────────────────────────────────────────────────────────

class WeinsteinIndicator:
    """
    Converts a daily breadth series (% above MA) + index price into
    MACD-style z-scored signals with momentum and trend-score columns.

    Signal columns in generate_signals() output:
        pct_above_ma   – raw breadth percentage
        z_score        – rolling z-score of breadth (z_lookback window)
        fast_z         – EMA(z_score, fast_smoothing) — MACD fast line
        signal_line    – EMA(fast_z, signal_smoothing) — MACD slow line
        z_histogram    – fast_z − signal_line  (positive = breadth improving)
        fast_z_slope   – slope_period-bar change in fast_z
        breadth_roc    – slope_period-bar % change in raw breadth
        trend_score    – composite −100 … +100 (incline vs decline)
        index_close    – KSE-100 price
        index_ma       – SMA(index_close, price_ma_period)
        signal         – 0=Hold  1=Buy  −1=Sell
    """

    def __init__(
        self,
        ma_period        = PSX_DEFAULTS["ma_period"],
        z_lookback       = PSX_DEFAULTS["z_lookback"],
        fast_smoothing   = PSX_DEFAULTS["fast_smoothing"],
        signal_smoothing = PSX_DEFAULTS["signal_smoothing"],
        buy_threshold    = PSX_DEFAULTS["buy_threshold"],
        sell_threshold   = PSX_DEFAULTS["sell_threshold"],
        price_ma_period  = PSX_DEFAULTS["price_ma_period"],
        slope_period     = PSX_DEFAULTS["slope_period"],
    ):
        self.ma_period        = ma_period
        self.z_lookback       = z_lookback
        self.fast_smoothing   = fast_smoothing
        self.signal_smoothing = signal_smoothing
        self.buy_threshold    = buy_threshold
        self.sell_threshold   = sell_threshold
        self.price_ma_period  = price_ma_period
        self.slope_period     = slope_period

    # ── internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
        roll = s.rolling(window, min_periods=30)
        mean = roll.mean()
        std  = roll.std().replace(0, np.nan)
        return (s - mean) / std

    @staticmethod
    def _sma(s: pd.Series, period: int) -> pd.Series:
        return s.rolling(period, min_periods=1).mean()

    # ── public API ───────────────────────────────────────────────────────────

    def generate_signals(
        self,
        breadth: pd.Series,
        index_close: pd.Series,
    ) -> pd.DataFrame:
        """
        Parameters
        ----------
        breadth     : date-indexed Series from compute_breadth_series()
        index_close : date-indexed Series of KSE-100 daily close prices

        Returns
        -------
        DataFrame — see class docstring for column list.
        """
        df = (
            pd.DataFrame({"pct_above_ma": breadth, "index_close": index_close})
            .dropna(subset=["pct_above_ma"])
            .copy()
        )
        df["index_close"] = df["index_close"].ffill()

        # ── Z-score pipeline (MACD-style with EMA) ──────────────────────────
        df["z_score"]     = self._rolling_zscore(df["pct_above_ma"], self.z_lookback)
        df["fast_z"]      = df["z_score"].ewm(span=self.fast_smoothing,   adjust=False).mean()
        df["signal_line"] = df["fast_z"].ewm(span=self.signal_smoothing,  adjust=False).mean()
        df["z_histogram"] = df["fast_z"] - df["signal_line"]
        df["index_ma"]    = self._sma(df["index_close"], self.price_ma_period)

        # ── Momentum / slope columns ─────────────────────────────────────────
        # Slope: how much fast_z changed over the last slope_period bars
        df["fast_z_slope"] = df["fast_z"].diff(self.slope_period)

        # Breadth rate of change: 5-bar % change in raw breadth percentage
        df["breadth_roc"]  = df["pct_above_ma"].pct_change(self.slope_period) * 100

        # ── Composite Trend Score  −100 … +100 ──────────────────────────────
        # Component 1: z-score level (−40 … +40)
        z_contrib   = df["fast_z"].clip(-3, 3) / 3.0 * 40

        # Component 2: slope direction / speed (−30 … +30)
        slope_contrib = df["fast_z_slope"].clip(-1.5, 1.5) / 1.5 * 30

        # Component 3: KSE-100 above/below its own 50-day MA (−20 … +20)
        idx_contrib = (df["index_close"] > df["index_ma"]).astype(float) * 40 - 20

        # Component 4: breadth rate of change (−10 … +10)
        roc_contrib = df["breadth_roc"].clip(-15, 15) / 15.0 * 10

        df["trend_score"] = (z_contrib + slope_contrib + idx_contrib + roc_contrib).clip(-100, 100)

        # ── Signal generation (histogram crossover) ──────────────────────────
        hist_list = df["z_histogram"].tolist()
        px_list   = df["index_close"].tolist()
        pma_list  = df["index_ma"].tolist()
        sig_list  = [0] * len(df)

        def _nan(v):
            return v is None or (isinstance(v, float) and v != v)

        for i in range(1, len(df)):
            if _nan(hist_list[i]) or _nan(pma_list[i]):
                continue

            h_prev = hist_list[i - 1]
            h_cur  = hist_list[i]
            px_cur = px_list[i]
            pma_cur = pma_list[i]

            if _nan(h_prev):
                continue

            # BUY: histogram crosses from negative → positive (fast_z beats signal)
            #      AND index is above its own MA (price confirmation)
            if h_prev < 0 and h_cur >= 0 and px_cur > pma_cur:
                sig_list[i] = 1

            # SELL: histogram crosses from positive → negative
            elif h_prev > 0 and h_cur <= 0:
                sig_list[i] = -1

        df["signal"] = sig_list
        return df

    def current_regime(self, signals_df: pd.DataFrame) -> dict:
        """Return a concise dict describing the latest regime state."""
        row  = signals_df.iloc[-1]
        fz   = row["fast_z"]
        sl   = row["signal_line"]
        hist = row["z_histogram"]
        sig  = int(row["signal"])
        pct  = row["pct_above_ma"]
        px   = row["index_close"]
        pma  = row["index_ma"]
        slope = row.get("fast_z_slope", np.nan)
        roc   = row.get("breadth_roc",   np.nan)
        score = row.get("trend_score",   np.nan)

        # ── Zone based on fast_z level ───────────────────────────────────────
        if pd.isna(fz):
            zone = "Insufficient data"
        elif fz > self.sell_threshold:
            zone = "Overbought"
        elif fz > 0.5:
            zone = "Bullish"
        elif fz > -0.5:
            zone = "Neutral"
        elif fz > self.buy_threshold:
            zone = "Bearish"
        else:
            zone = "Oversold"

        # ── Direction arrow from slope ───────────────────────────────────────
        if pd.isna(slope):
            direction = "Flat"
        elif slope > 0.15:
            direction = "Rising"
        elif slope < -0.15:
            direction = "Falling"
        else:
            direction = "Flat"

        direction_arrow = {"Rising": "▲", "Falling": "▼", "Flat": "→"}.get(direction, "→")

        signal_map = {0: "HOLD", 1: "BUY", -1: "SELL"}
        color_map  = {
            "Overbought": "#ef4444",
            "Bullish":    "#22c55e",
            "Neutral":    "#fbbf24",
            "Bearish":    "#fca5a5",
            "Oversold":   "#3b82f6",
        }

        # ── Regime state: persistent "where are we now" ──────────────────────
        idx_above = bool(px > pma) if not (pd.isna(px) or pd.isna(pma)) else False
        if not pd.isna(hist) and hist > 0 and idx_above:
            regime_state = "In Market"
            regime_color = "#22c55e"
        else:
            regime_state = "Out of Market"
            regime_color = "#ef4444"

        # ── Last crossover event ─────────────────────────────────────────────
        crossover_mask = signals_df["signal"] != 0
        if crossover_mask.any():
            last_cross_row  = signals_df[crossover_mask].iloc[-1]
            last_cross_sig  = signal_map.get(int(last_cross_row["signal"]), "HOLD")
            last_cross_date = last_cross_row.name
        else:
            last_cross_sig  = None
            last_cross_date = None

        def _f(v, n=3):
            return round(float(v), n) if not pd.isna(v) else None

        return {
            "signal":          signal_map.get(sig, "HOLD"),
            "signal_int":      sig,
            "regime_state":    regime_state,
            "regime_color":    regime_color,
            "last_cross_sig":  last_cross_sig,
            "last_cross_date": last_cross_date,
            "zone":            zone,
            "zone_color":      color_map.get(zone, "#94a3b8"),
            "fast_z":          _f(fz),
            "signal_line":     _f(sl),
            "z_histogram":     _f(hist),
            "fast_z_slope":    _f(slope),
            "breadth_roc":     _f(roc, 1),
            "trend_score":     _f(score, 1),
            "direction":       direction,
            "direction_arrow": direction_arrow,
            "pct_above_ma":    round(float(pct), 1) if not pd.isna(pct) else None,
            "index_above_ma":  idx_above,
            "buy_threshold":   self.buy_threshold,
            "sell_threshold":  self.sell_threshold,
            "last_date":       signals_df.index[-1],
        }


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

def _date_to_idx(signals_df: pd.DataFrame, date_str: str, window_days: int = 45) -> list[int]:
    target = pd.Timestamp(date_str)
    lo = target - pd.Timedelta(days=window_days)
    hi = target + pd.Timedelta(days=window_days)
    mask = (signals_df.index >= lo) & (signals_df.index <= hi)
    return list(np.where(mask)[0])


def _score_signals(
    signals_df: pd.DataFrame,
    bottom_dates: list[str],
    top_dates: list[str],
    window: int = 45,
) -> float:
    """
    Score a signals DataFrame against known PSX turning points.
    +1 for each bottom with a nearby BUY signal.
    +1 for each top with a nearby SELL signal.
    −0.3 penalty per false signal outside all event windows.
    """
    sig = signals_df["signal"].values

    tp = 0
    event_positions: set[int] = set()
    for d in bottom_dates:
        idxs = _date_to_idx(signals_df, d, window)
        event_positions.update(idxs)
        if any(sig[i] == 1 for i in idxs if i < len(sig)):
            tp += 1
    for d in top_dates:
        idxs = _date_to_idx(signals_df, d, window)
        event_positions.update(idxs)
        if any(sig[i] == -1 for i in idxs if i < len(sig)):
            tp += 1

    fp = sum(
        1 for i, s in enumerate(sig)
        if s != 0 and i not in event_positions
    )

    return tp - 0.3 * fp


def run_optimizer(
    breadth: pd.Series,
    index_close: pd.Series,
    bottom_dates: list[str] = PSX_KNOWN_BOTTOMS,
    top_dates: list[str]    = PSX_KNOWN_TOPS,
    param_grid: dict | None = None,
    window_days: int        = 45,
) -> tuple[dict, pd.DataFrame]:
    """
    Grid-search over param_grid to find the parameter set that best captures
    the supplied PSX turning-point dates.

    Returns (best_params_dict, results_df sorted by score descending).
    """
    if param_grid is None:
        param_grid = {
            "ma_period":        [50],
            "z_lookback":       [126, 189, 252],
            "fast_smoothing":   [3, 5, 8],
            "signal_smoothing": [10, 13, 17],
            "buy_threshold":    [-1.8, -1.5, -1.2],
            "sell_threshold":   [1.5, 1.8, 2.0],
        }

    from itertools import product

    keys   = list(param_grid.keys())
    combos = list(product(*[param_grid[k] for k in keys]))

    records: list[dict] = []
    best_score = -9999.0
    best_params: dict = {}

    for combo in combos:
        params = dict(zip(keys, combo))

        ind = WeinsteinIndicator(**params)
        try:
            signals_df = ind.generate_signals(breadth, index_close)
        except Exception:
            continue

        score = _score_signals(signals_df, bottom_dates, top_dates, window=window_days)

        row = {**params, "score": round(score, 3)}
        records.append(row)

        if score > best_score:
            best_score  = score
            best_params = params.copy()

    results_df = (
        pd.DataFrame(records)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )
    return best_params, results_df
