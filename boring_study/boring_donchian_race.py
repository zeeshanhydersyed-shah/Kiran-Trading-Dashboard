"""
boring_donchian_race.py — for every breakout occurrence already found,
race each profit target against a fixed -6% stop: which comes first,
using daily high (target) / low (stop), walked day by day from entry+1
up to the same up-to-90-trading-day window as before.

Tie rule (both target and stop touched same day — can't know intrabar
order from daily OHLC): stop wins, the conservative assumption.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
STOP = -0.06
THRESHOLDS = [5, 10, 20, 30, 50]
MAX_HORIZON = 90

occ = pd.read_csv("boring_donchian_occurrences.csv")
print(f"Occurrences to race: {len(occ):,}")

con = sqlite3.connect(DB)
symbols = occ["symbol"].unique().tolist()
placeholders = ",".join("?" for _ in symbols)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=symbols
)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
    }

results = {th: {"TP_FIRST": 0, "STOP_FIRST": 0, "NEITHER": 0} for th in THRESHOLDS}
n_processed = 0

for _, row in occ.iterrows():
    sym = row["symbol"]
    date = row["date"]
    entry = row["entry_close"]
    pf = by_symbol.get(sym)
    if pf is None:
        continue
    dates = pf["dates"]
    high = pf["high"]
    low = pf["low"]
    idx = np.searchsorted(dates, date)
    if idx >= len(dates) or dates[idx] != date:
        continue
    n = len(dates)
    end_j = min(idx + MAX_HORIZON, n - 1)
    if end_j <= idx:
        continue

    fwd_high = high[idx + 1:end_j + 1]
    fwd_low = low[idx + 1:end_j + 1]

    stop_level = entry * (1 + STOP)
    stop_hits = np.where(fwd_low <= stop_level)[0]
    stop_day = stop_hits[0] if len(stop_hits) else None

    n_processed += 1
    for th in THRESHOLDS:
        target_level = entry * (1 + th / 100)
        target_hits = np.where(fwd_high >= target_level)[0]
        target_day = target_hits[0] if len(target_hits) else None

        if target_day is None and stop_day is None:
            results[th]["NEITHER"] += 1
        elif target_day is not None and (stop_day is None or target_day < stop_day):
            results[th]["TP_FIRST"] += 1
        else:
            # target_day is None (stop only) OR same-day tie OR stop strictly first
            results[th]["STOP_FIRST"] += 1

print(f"Occurrences actually raced (had forward data): {n_processed:,}\n")

print(f"{'Threshold':<12}{'Hit TP before -6%':<20}{'Stop hit first':<18}{'Neither (window closed)'}")
for th in THRESHOLDS:
    r = results[th]
    tot = r["TP_FIRST"] + r["STOP_FIRST"] + r["NEITHER"]
    tp_pct = r["TP_FIRST"] / tot * 100
    stop_pct = r["STOP_FIRST"] / tot * 100
    neither_pct = r["NEITHER"] / tot * 100
    print(f"+{th}%{'':<8}{tp_pct:>6.1f}% ({r['TP_FIRST']:,}){'':<4}"
          f"{stop_pct:>6.1f}% ({r['STOP_FIRST']:,}){'':<4}"
          f"{neither_pct:>6.1f}% ({r['NEITHER']:,})")
