"""
boring_donchian_lookback_sweep.py — repeat the full breakout + matched
control-group + TP-vs-stop race study across 5 lookback definitions:
10/20/40/60/120-day Donchian breakout. Same 1% buffer, same -6% stop,
same methodology as the single 20-day study, same seed (42) for the
control draw. No liquidity/RS/sector/regime filters.

Read-only against psx_data.db. Prices loaded once, reused across all
5 lookback runs for speed.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
LOOKBACKS = [10, 20, 40, 60, 120]
BUFFER = 1.01
STOP = -0.06
THRESHOLDS = [5, 10, 20, 30, 50]
MAX_HORIZON = 90
SEED = 42
START_DATE = "2005-01-01"
END_DATE = "2026-12-31"

print("Loading prices_adjusted (once, reused for all lookbacks)...")
con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, high, low, close FROM prices_adjusted "
    "WHERE date >= ? AND date <= ? ORDER BY symbol, date",
    con, params=(START_DATE, END_DATE)
)
con.close()
print(f"Loaded {len(prices):,} rows, {prices['symbol'].nunique():,} symbols\n")

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }
del prices


def find_breakouts(lookback):
    occs = []
    for sym, pf in by_symbol.items():
        high, close, dates = pf["high"], pf["close"], pf["dates"]
        n = len(dates)
        if n < lookback + 1:
            continue
        prior_high = pd.Series(high).shift(1).rolling(lookback).max().to_numpy()
        c_ok = ~np.isnan(close)
        for t in range(lookback, n):
            ph = prior_high[t]
            if np.isnan(ph) or ph <= 0 or not c_ok[t]:
                continue
            if close[t] > ph * BUFFER:
                occs.append((sym, dates[t], close[t], t))
    return pd.DataFrame(occs, columns=["symbol", "date", "entry_close", "t_idx"])


def make_control(occ_df, lookback, seed):
    breakout_days = set(zip(occ_df["symbol"], occ_df["date"]))
    rng = np.random.default_rng(seed)
    eligible_pool = {}
    for sym, pf in by_symbol.items():
        dates = pf["dates"]
        n = len(dates)
        idxs = np.arange(lookback, n)
        non_bo = [i for i in idxs if (sym, dates[i]) not in breakout_days]
        eligible_pool[sym] = np.array(non_bo)

    rows = []
    for _, row in occ_df.iterrows():
        sym = row["symbol"]
        pool = eligible_pool.get(sym)
        if pool is None or len(pool) == 0:
            continue
        t = int(rng.choice(pool))
        pf = by_symbol[sym]
        entry = pf["close"][t]
        if entry is None or np.isnan(entry) or entry <= 0:
            continue
        rows.append((sym, pf["dates"][t], entry, t))
    return pd.DataFrame(rows, columns=["symbol", "date", "entry_close", "t_idx"])


def race(df):
    results = {th: {"TP_FIRST": 0, "STOP_FIRST": 0, "NEITHER": 0} for th in THRESHOLDS}
    for _, row in df.iterrows():
        sym, entry, t = row["symbol"], row["entry_close"], row["t_idx"]
        pf = by_symbol.get(sym)
        if pf is None:
            continue
        high, low = pf["high"], pf["low"]
        n = len(high)
        end_j = min(t + MAX_HORIZON, n - 1)
        if end_j <= t:
            continue
        fwd_high = high[t + 1:end_j + 1]
        fwd_low = low[t + 1:end_j + 1]
        stop_level = entry * (1 + STOP)
        stop_hits = np.where(fwd_low <= stop_level)[0]
        stop_day = stop_hits[0] if len(stop_hits) else None
        for th in THRESHOLDS:
            target_level = entry * (1 + th / 100)
            target_hits = np.where(fwd_high >= target_level)[0]
            target_day = target_hits[0] if len(target_hits) else None
            if target_day is None and stop_day is None:
                results[th]["NEITHER"] += 1
            elif target_day is not None and (stop_day is None or target_day < stop_day):
                results[th]["TP_FIRST"] += 1
            else:
                results[th]["STOP_FIRST"] += 1
    return results


summary = []
for lb in LOOKBACKS:
    print(f"\n{'='*80}\nLOOKBACK = {lb} days\n{'='*80}")

    occ = find_breakouts(lb)
    print(f"Breakout occurrences: {len(occ):,}")

    ctrl = make_control(occ, lb, SEED)
    print(f"Control entries: {len(ctrl):,}")

    print("Racing breakout group...")
    bo_race = race(occ)
    print("Racing control group...")
    ct_race = race(ctrl)

    print(f"\n{'Threshold':<12}{'Breakout TP%':<15}{'Control TP%':<14}{'Improvement (pp)'}")
    row = {"lookback": lb, "n_occurrences": len(occ), "n_control": len(ctrl)}
    for th in THRESHOLDS:
        br = bo_race[th]
        cr = ct_race[th]
        br_tot = sum(br.values())
        cr_tot = sum(cr.values())
        br_pct = br["TP_FIRST"] / br_tot * 100 if br_tot else float("nan")
        cr_pct = cr["TP_FIRST"] / cr_tot * 100 if cr_tot else float("nan")
        improvement = br_pct - cr_pct
        print(f"+{th}%{'':<8}{br_pct:<15.2f}{cr_pct:<14.2f}{improvement:+.2f}")
        row[f"bo_tp_{th}"] = br_pct
        row[f"ctrl_tp_{th}"] = cr_pct
        row[f"improvement_{th}"] = improvement
    summary.append(row)

summary_df = pd.DataFrame(summary)
summary_df.to_csv("boring_donchian_lookback_sweep_summary.csv", index=False)

print(f"\n\n{'='*90}")
print("FINAL COMPARISON TABLE — improvement over random (breakout TP% - control TP%), in pp")
print(f"{'='*90}")
header = f"{'Lookback':<12}{'N occ':<10}" + "".join(f"+{th}%{'':<7}" for th in THRESHOLDS)
print(header)
for row in summary:
    line = f"{row['lookback']}d{'':<9}{row['n_occurrences']:<10,}"
    for th in THRESHOLDS:
        line += f"{row[f'improvement_{th}']:+.2f}{'':<7}"
    print(line)

print("\nSaved to boring_donchian_lookback_sweep_summary.csv")
print("Done.")
