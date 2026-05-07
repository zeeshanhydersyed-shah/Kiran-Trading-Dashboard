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
    fast_smoothing   = 5,      # EMA of raw z-score
    signal_smoothing = 10,     # EMA of fast_z  (signal line)
    buy_threshold    = -1.7,   # z < this = oversold territory
    sell_threshold   = 2.0,    # z > this = overbought territory
    price_ma_period  = 50,     # index MA for price-action confirmation
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

    # Boolean: is today's close > MA?
    above = wide > ma

    # Per date: count valid (non-NaN) comparisons, then compute pct
    valid = above.notna()
    pct_above = above.sum(axis=1) / valid.sum(axis=1).replace(0, np.nan) * 100

    pct_above.name = "pct_above_ma"
    return pct_above.dropna()


# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR
# ─────────────────────────────────────────────────────────────────────────────

class WeinsteinIndicator:
    """
    Converts a daily breadth series (% above MA) + index price into
    z-scored signals.
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
    ):
        self.ma_period        = ma_period
        self.z_lookback       = z_lookback
        self.fast_smoothing   = fast_smoothing
        self.signal_smoothing = signal_smoothing
        self.buy_threshold    = buy_threshold
        self.sell_threshold   = sell_threshold
        self.price_ma_period  = price_ma_period

    # ── internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
        roll   = s.rolling(window, min_periods=30)
        mean   = roll.mean()
        std    = roll.std().replace(0, np.nan)
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
        DataFrame with columns:
            pct_above_ma, z_score, fast_z, signal_line,
            index_close, index_ma, signal
        signal values: 0=Hold  1=Buy  -1=Sell  -2=Short
        """
        # Align on common dates
        df = pd.DataFrame({"pct_above_ma": breadth, "index_close": index_close}).dropna(
            subset=["pct_above_ma"]
        )
        df["index_close"] = df["index_close"].ffill()  # forward-fill missing index days

        # Z-score pipeline
        df["z_score"]    = self._rolling_zscore(df["pct_above_ma"], self.z_lookback)
        df["fast_z"]     = self._sma(df["z_score"], self.fast_smoothing)
        df["signal_line"] = self._sma(df["fast_z"], self.signal_smoothing)

        # Index price confirmation
        df["index_ma"] = self._sma(df["index_close"], self.price_ma_period)

        # Signal generation
        df["signal"] = 0

        fz   = df["fast_z"].values
        sl   = df["signal_line"].values
        px   = df["index_close"].values
        pma  = df["index_ma"].values
        sig  = df["signal"].values

        for i in range(1, len(df)):
            if np.isnan(fz[i]) or np.isnan(sl[i]) or np.isnan(pma[i]):
                continue

            fz_prev = fz[i - 1]

            # BUY: z crosses up through buy_threshold + price above MA
            if (
                not np.isnan(fz_prev)
                and fz_prev <= self.buy_threshold
                and fz[i] > self.buy_threshold
                and fz[i] > sl[i]
                and px[i] > pma[i]
            ):
                sig[i] = 1

            # SELL: z crosses down from overbought OR rolls below signal line
            elif (fz_prev >= self.sell_threshold and fz[i] < self.sell_threshold) or (
                fz_prev >= self.sell_threshold and fz[i] < sl[i]
            ):
                sig[i] = -1

            # SHORT: deeply oversold + index below MA + signal line negative
            elif fz[i] < self.buy_threshold and px[i] < pma[i] and sl[i] < 0:
                sig[i] = -2

        df["signal"] = sig
        return df

    def current_regime(self, signals_df: pd.DataFrame) -> dict:
        """Return a concise dict describing the latest regime state."""
        row   = signals_df.iloc[-1]
        fz    = row["fast_z"]
        sl    = row["signal_line"]
        sig   = int(row["signal"])
        pct   = row["pct_above_ma"]
        px    = row["index_close"]
        pma   = row["index_ma"]

        # Regime label based on z-score level (independent of cross signal)
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

        signal_map = {0: "HOLD", 1: "BUY", -1: "SELL", -2: "SHORT"}
        color_map  = {
            "Overbought": "#ef4444",
            "Bullish":    "#22c55e",
            "Neutral":    "#fbbf24",
            "Bearish":    "#fca5a5",
            "Oversold":   "#3b82f6",
        }

        return {
            "signal":          signal_map.get(sig, "HOLD"),
            "signal_int":      sig,
            "zone":            zone,
            "zone_color":      color_map.get(zone, "#94a3b8"),
            "fast_z":          round(float(fz), 3) if not pd.isna(fz) else None,
            "signal_line":     round(float(sl), 3) if not pd.isna(sl) else None,
            "pct_above_ma":    round(float(pct), 1) if not pd.isna(pct) else None,
            "index_above_ma":  bool(px > pma) if not (pd.isna(px) or pd.isna(pma)) else None,
            "buy_threshold":   self.buy_threshold,
            "sell_threshold":  self.sell_threshold,
            "last_date":       signals_df.index[-1],
        }


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

def _date_to_idx(signals_df: pd.DataFrame, date_str: str, window_days: int = 45) -> list[int]:
    """
    Return a list of integer positions within ±window_days of the target date.
    Gracefully returns [] if the date is outside the DataFrame's range.
    """
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
    +1 for each top with a nearby SELL or SHORT signal.
    -0.3 penalty per false signal (signal that triggered but wasn't near an event).
    """
    sig = signals_df["signal"].values

    # True positives
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
        if any(sig[i] in (-1, -2) for i in idxs if i < len(sig)):
            tp += 1

    # False signals (signals outside all event windows)
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
            "ma_period":        [50],               # fixed (user chose 50)
            "z_lookback":       [126, 189, 252],
            "fast_smoothing":   [3, 5, 8],
            "signal_smoothing": [8, 10, 13],
            "buy_threshold":    [-2.0, -1.7, -1.5],
            "sell_threshold":   [1.8, 2.0, 2.2],
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
