"""
KSE-100 Index trend filter for KIRAN screener.

Provides a point-in-time correct answer to:
    "Is the market in a long-friendly regime on this date?"

Rules:
    LONG  gate: KSE-100 close >= its 50-day MA  → market trending up   → allow LONGs
    SHORT gate: KSE-100 close <  its 50-day MA  → market trending down  → allow SHORTs
                (shorts are already rare / DFC-restricted, no suppression needed)

If KSE-100 data is unavailable for a date (table empty, not yet backfilled),
the filter returns True for both directions so nothing is suppressed — safe
default that preserves existing behaviour.

Usage (backtest — point-in-time):
    from kse100_filter import KSE100Filter
    kse_filter = KSE100Filter()            # loads all data once
    long_ok = kse_filter.long_allowed(as_of_date)

Usage (live screener):
    from kse100_filter import KSE100Filter
    kse_filter = KSE100Filter()
    long_ok = kse_filter.long_allowed()   # uses today
"""

from datetime import date as date_cls
from functools import lru_cache

import pandas as pd

MA_PERIOD = 50      # 50-trading-day moving average


class KSE100Filter:
    """
    Loads the full KSE-100 price history once and answers trend questions
    efficiently for any date (point-in-time correct).
    """

    def __init__(self):
        self._df = self._load()

    def _load(self) -> pd.DataFrame:
        """Load KSE-100 from index_prices, compute rolling 50-day MA."""
        try:
            from database import get_conn
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """SELECT date, close FROM index_prices
                       WHERE symbol = 'KSE-100'
                       ORDER BY date"""
                )
                rows = cur.fetchall()
            if not rows:
                return pd.DataFrame(columns=["date", "close", "ma50"])

            df = pd.DataFrame(rows, columns=["date", "close"])
            df["date"]  = pd.to_datetime(df["date"])
            df["ma50"]  = df["close"].rolling(MA_PERIOD, min_periods=MA_PERIOD).mean()
            return df.set_index("date")
        except Exception:
            return pd.DataFrame(columns=["date", "close", "ma50"])

    def _available(self) -> bool:
        return not self._df.empty

    def long_allowed(self, as_of: date_cls | None = None) -> bool:
        """
        Return True if KSE-100 is above its 50-day MA on as_of date.
        Falls back to True when data unavailable (no suppression).
        """
        if not self._available():
            return True

        as_of_ts = pd.Timestamp(as_of or date_cls.today())

        # Find the most recent row on or before as_of_ts
        past = self._df[self._df.index <= as_of_ts]
        if past.empty:
            return True

        row = past.iloc[-1]
        if pd.isna(row["ma50"]):
            return True     # not enough history yet for 50MA

        return bool(row["close"] >= row["ma50"])

    def short_favoured(self, as_of: date_cls | None = None) -> bool:
        """Return True if KSE-100 is below its 50MA (bearish regime)."""
        return not self.long_allowed(as_of)

    def kse100_summary(self, as_of: date_cls | None = None) -> dict:
        """Return a dict of current KSE-100 trend stats for display in KIRAN."""
        if not self._available():
            return {"available": False}

        as_of_ts = pd.Timestamp(as_of or date_cls.today())
        past = self._df[self._df.index <= as_of_ts]
        if past.empty:
            return {"available": False}

        row = past.iloc[-1]
        # close comes back as decimal.Decimal on Postgres (numeric column type)
        # vs. plain float on SQLite -- cast to float here so every downstream
        # calculation and the returned dict are consistently float, regardless
        # of backend. Same root cause as the _load() cursor fix: this function
        # never ran to completion against Postgres before that fix landed, so
        # this mismatch was never exercised.
        close = float(row["close"])
        ma50  = row["ma50"]

        if pd.isna(ma50):
            return {"available": True, "close": close, "ma50": None,
                    "above_ma50": None, "pct_vs_ma50": None}

        ma50 = float(ma50)
        pct = (close - ma50) / ma50 * 100

        # 30-trading-day performance
        perf_30d = None
        if len(past) > 30:
            base_close = float(past.iloc[-31]["close"])
            if base_close and base_close > 0:
                perf_30d = round((close - base_close) / base_close * 100, 1)

        return {
            "available":   True,
            "date":        past.index[-1].date().isoformat(),
            "close":       round(close, 0),
            "ma50":        round(ma50, 0),
            "above_ma50":  close >= ma50,
            "pct_vs_ma50": round(pct, 1),
            "perf_30d":    perf_30d,
        }
