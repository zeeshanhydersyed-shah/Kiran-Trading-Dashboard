"""
boring_capital_lockup_analysis.py -- descriptive-only analysis of how long
NON-WINNING top-decile-RS breakouts take to resolve. Answers a capital-
allocation question raised by the trading rulebook review: are losers fast-
failing or long-drifting zombies? Not a predictor search, not a mechanism
test -- pure duration description on the same locked matched panels
(seed=42, breakout=1 rows only -- control rows aren't real trades).

Uses the same decile definition (pd.qcut(10), pooled) as every prior
heterogeneity analysis in this thread, so "top decile" here is the same
population already characterized (55.1%/57.0% hit rate, 20d/60d).

For non-winners (hit_tp_10=0), classifies each row as:
  STOPPED     -- low breached the -6% stop before day 90 (or before data ran out)
  UNRESOLVED  -- neither stop nor target hit within the available window
                 -- further split into:
       FULL_HORIZON  -- a genuine 90 trading days of forward data were available
                         and it still didn't resolve (a real "zombie")
       RIGHT_CENSORED -- fewer than 90 forward bars exist (recent breakout,
                         or symbol's price history ends early) -- unknown
                         what would have happened next, not a true 90-day drift
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
STOP = -0.06
TARGET = 0.10
MAX_HORIZON = 90

con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, high, low, close FROM prices_adjusted ORDER BY symbol, date", con
)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.sort_values("date").reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }


def compute_row(sym, date):
    pf = by_symbol.get(sym)
    if pf is None:
        return None
    dates = pf["dates"]
    t = np.searchsorted(dates, date)
    if t >= len(dates) or dates[t] != date:
        return None
    entry = pf["close"][t]
    if entry is None or np.isnan(entry) or entry <= 0:
        return None
    n = len(dates)
    available_horizon = n - 1 - t
    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j <= t:
        return None

    high, low = pf["high"], pf["low"]
    fwd_high = high[t + 1:end_j + 1]
    fwd_low = low[t + 1:end_j + 1]
    stop_level = entry * (1 + STOP)
    target_level = entry * (1 + TARGET)
    stop_hits = np.where(fwd_low <= stop_level)[0]
    target_hits = np.where(fwd_high >= target_level)[0]
    stop_day = stop_hits[0] if len(stop_hits) else None
    target_day = target_hits[0] if len(target_hits) else None

    if target_day is not None and (stop_day is None or target_day < stop_day):
        return None  # winner -- not part of this analysis

    if stop_day is not None:
        return "STOPPED", stop_day + 1, available_horizon, np.nan

    # unresolved: neither hit within the observed window
    censored = available_horizon < MAX_HORIZON
    last_close = pf["close"][end_j]
    unrealized_ret = (last_close - entry) / entry * 100
    status = "RIGHT_CENSORED" if censored else "FULL_HORIZON"
    return status, end_j - t, available_horizon, unrealized_ret


def analyze(panel_path, label):
    print(f"\n{'#'*90}\n# {label}\n{'#'*90}")
    df = pd.read_csv(panel_path)
    d = df.dropna(subset=["hit_tp_10", "breakout", "stock_rs"]).copy()
    d["rs_decile"] = pd.qcut(d["stock_rs"], 10, labels=False, duplicates="drop")

    pop = d[(d["breakout"] == 1) & (d["rs_decile"] == d["rs_decile"].max())].copy()
    print(f"Top-decile RS breakouts (real trades only): N={len(pop):,}")
    print(f"  hit_tp_10 rate in this slice: {pop['hit_tp_10'].mean():.4f}")

    nonwin = pop[pop["hit_tp_10"] == 0].copy()
    print(f"Non-winners: N={len(nonwin):,}")

    results = nonwin.apply(lambda r: compute_row(r["symbol"], r["date"]), axis=1)
    valid = results.notna()
    nonwin = nonwin[valid].copy()
    vals = list(results[valid])
    nonwin["status"] = [v[0] for v in vals]
    nonwin["duration_days"] = [v[1] for v in vals]
    nonwin["available_horizon"] = [v[2] for v in vals]
    nonwin["unrealized_ret_at_end"] = [v[3] for v in vals]

    print(f"Non-winners with computable duration: N={len(nonwin):,}")
    print(f"\nStatus breakdown:")
    print((nonwin["status"].value_counts(normalize=True) * 100).round(2).to_string())
    print(nonwin["status"].value_counts().to_string())

    stopped = nonwin[nonwin["status"] == "STOPPED"]
    print(f"\n--- STOPPED (n={len(stopped):,}) -- day-to-stop distribution ---")
    print(stopped["duration_days"].describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())

    print(f"\n--- Cumulative resolution curve for STOPPED trades ---")
    for day in [1, 2, 3, 5, 10, 20, 30, 60, 90]:
        pct_of_stopped = (stopped["duration_days"] <= day).mean() * 100
        pct_of_all_nonwinners = (stopped["duration_days"] <= day).sum() / len(nonwin) * 100
        print(f"  by day {day:>3}: {pct_of_stopped:5.1f}% of eventual-stops resolved  |  "
              f"{pct_of_all_nonwinners:5.1f}% of ALL non-winners resolved (stopped) by then")

    full_horizon = nonwin[nonwin["status"] == "FULL_HORIZON"]
    censored = nonwin[nonwin["status"] == "RIGHT_CENSORED"]
    print(f"\n--- UNRESOLVED, genuine full 90-day horizon available (n={len(full_horizon):,}) -- true 'zombies' ---")
    if len(full_horizon):
        print(f"  Unrealized return at day 90, distribution:")
        print(full_horizon["unrealized_ret_at_end"].describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())

    print(f"\n--- UNRESOLVED, right-censored by data availability (n={len(censored):,}) -- unknown outcome, not a true drift ---")
    if len(censored):
        print(f"  Available horizon distribution (days of data actually observed):")
        print(censored["available_horizon"].describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())
        print(f"  Unrealized return at last observed day, distribution:")
        print(censored["unrealized_ret_at_end"].describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())

    return nonwin


nonwin_20 = analyze("boring_heterogeneity_panel_20d_race.csv", "20d panel -- top-decile RS, non-winners duration")
nonwin_60 = analyze("boring_heterogeneity_panel_60d_race.csv", "60d panel -- top-decile RS, non-winners duration")

print("\n\nDone.")
