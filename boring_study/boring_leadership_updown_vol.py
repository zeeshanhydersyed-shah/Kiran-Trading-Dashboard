"""
boring_leadership_updown_vol.py — decompose trailing 60d realized volatility
into upside and downside semi-deviation, per occurrence, to test whether
"leadership" volatility is specifically an upside phenomenon or symmetric.

upside_semivol   = sqrt(mean(max(daily_ret, 0)^2))   over trailing 60d
downside_semivol = sqrt(mean(min(daily_ret, 0)^2))   over trailing 60d

Predictor-only, no outcome touched. Read-only against psx_data.db.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
WINDOW = 60

occ = pd.read_csv("boring_donchian_mechanism_dataset.csv")[["symbol", "date"]]
con = sqlite3.connect(DB)
prices = pd.read_sql_query("SELECT symbol, date, close FROM prices_adjusted ORDER BY symbol, date", con)
con.close()

print("Computing trailing upside/downside semi-deviation per symbol...")
by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    close = g["close"].to_numpy(dtype=float)
    dates = g["date"].to_numpy()
    n = len(close)

    daily_ret = np.full(n, np.nan)
    prev = close[:-1]
    safe = prev != 0
    daily_ret[1:][safe] = (close[1:][safe] - prev[safe]) / prev[safe] * 100

    up_sq = np.where(daily_ret > 0, daily_ret ** 2, 0.0)
    down_sq = np.where(daily_ret < 0, daily_ret ** 2, 0.0)
    valid = ~np.isnan(daily_ret)
    up_sq = np.where(valid, up_sq, np.nan)
    down_sq = np.where(valid, down_sq, np.nan)

    up_semivol = np.sqrt(pd.Series(up_sq).rolling(WINDOW, min_periods=WINDOW).mean().to_numpy())
    down_semivol = np.sqrt(pd.Series(down_sq).rolling(WINDOW, min_periods=WINDOW).mean().to_numpy())

    by_symbol[sym] = {"dates": dates, "up_semivol": up_semivol, "down_semivol": down_semivol}

rows = []
for _, row in occ.iterrows():
    sym, d = row["symbol"], row["date"]
    pf = by_symbol.get(sym)
    if pf is None:
        continue
    pos = np.searchsorted(pf["dates"], d)
    if pos >= len(pf["dates"]) or pf["dates"][pos] != d:
        continue
    rows.append({
        "symbol": sym, "date": d,
        "up_semivol": pf["up_semivol"][pos],
        "down_semivol": pf["down_semivol"][pos],
    })

updown = pd.DataFrame(rows)
updown.to_csv("boring_leadership_updown_vol.csv", index=False)
print(f"Rows: {len(updown):,}")
print(updown[["up_semivol", "down_semivol"]].describe().round(3).to_string())
print("Done.")
