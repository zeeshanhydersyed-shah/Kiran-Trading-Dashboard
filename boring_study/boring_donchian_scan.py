"""
boring_donchian_scan.py — boring study, standalone, no reference to the
scientific-track conventions (no era split, no liquidity gate, no S-00X
format). Just: find every occurrence of the agreed Donchian breakout rule
and measure what happened after.

Rule: close[t] > MAX(high[t-20 .. t-1]) * 1.01  (close beats the prior
20-trading-day high by at least 1%), on prices_adjusted, every symbol,
2005-2026, no liquidity filter.

For each occurrence: forward return at 5/10/20/30/60/90 trading days,
plus MFE (max high reached in the 90-day forward window vs entry close)
and MAE (min low reached in the same window vs entry close).
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
LOOKBACK = 20
BUFFER = 1.01
HORIZONS = [5, 10, 20, 30, 60, 90]
MAX_HORIZON = 90
START_DATE = "2005-01-01"
END_DATE = "2026-12-31"


def main():
    con = sqlite3.connect(DB)
    prices = pd.read_sql_query(
        "SELECT symbol, date, high, low, close FROM prices_adjusted "
        "WHERE date >= ? AND date <= ? ORDER BY symbol, date",
        con, params=(START_DATE, END_DATE)
    )
    con.close()
    print(f"Loaded {len(prices):,} rows, {prices['symbol'].nunique():,} symbols")

    all_rows = []
    for sym, g in prices.groupby("symbol"):
        g = g.reset_index(drop=True)
        n = len(g)
        if n < LOOKBACK + 1:
            continue
        high = g["high"].to_numpy(dtype=float)
        low = g["low"].to_numpy(dtype=float)
        close = g["close"].to_numpy(dtype=float)
        dates = g["date"].to_numpy()

        # prior-20-day high, excluding today: rolling max of high[t-20..t-1]
        prior20high = np.full(n, np.nan)
        for t in range(LOOKBACK, n):
            window = high[t - LOOKBACK:t]
            if np.all(~np.isnan(window)):
                prior20high[t] = window.max()

        for t in range(LOOKBACK, n):
            ph = prior20high[t]
            if np.isnan(ph) or ph <= 0:
                continue
            c = close[t]
            if c is None or np.isnan(c):
                continue
            if c > ph * BUFFER:
                entry = c
                row = {"symbol": sym, "date": dates[t], "entry_close": entry,
                       "prior20high": ph}

                # forward returns at each horizon
                for h in HORIZONS:
                    j = t + h
                    if j < n and not np.isnan(close[j]):
                        row[f"ret_{h}d"] = (close[j] - entry) / entry * 100
                    else:
                        row[f"ret_{h}d"] = None

                # MFE / MAE over the forward window up to MAX_HORIZON
                end_j = min(t + MAX_HORIZON, n - 1)
                if end_j > t:
                    fwd_high = high[t + 1:end_j + 1]
                    fwd_low = low[t + 1:end_j + 1]
                    valid_h = fwd_high[~np.isnan(fwd_high)]
                    valid_l = fwd_low[~np.isnan(fwd_low)]
                    mfe = (valid_h.max() - entry) / entry * 100 if len(valid_h) else None
                    mae = (valid_l.min() - entry) / entry * 100 if len(valid_l) else None
                    row["mfe_pct"] = mfe
                    row["mae_pct"] = mae
                    row["days_tracked"] = end_j - t
                else:
                    row["mfe_pct"] = None
                    row["mae_pct"] = None
                    row["days_tracked"] = 0

                all_rows.append(row)

    df = pd.DataFrame(all_rows)
    print(f"\nTotal breakout occurrences: {len(df):,}")
    print(f"Unique symbols with at least one occurrence: {df['symbol'].nunique():,}")
    print(f"Date range of occurrences: {df['date'].min()} -> {df['date'].max()}")

    df.to_csv("boring_donchian_occurrences.csv", index=False)
    print("\nSaved full detail to boring_donchian_occurrences.csv")


if __name__ == "__main__":
    main()
