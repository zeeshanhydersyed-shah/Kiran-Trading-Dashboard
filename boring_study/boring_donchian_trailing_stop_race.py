"""
boring_donchian_trailing_stop_race.py -- adversarial shadow-test of alternative
exit mechanics against the locked +10%/-6% fixed race.

Population: the SAME run-collapsed, decile-9 + liquidity-gated set used to
correct the pseudo-replication bug found in the clustering audit (647 runs,
built from boring_heterogeneity_panel_20d.csv, lookback=20, liquidity>200000,
top RS_60 decile, one entry per run = first occurrence). NOT the raw
80,744-row occurrence file -- comparing against that would compare the new
exit rules to a population inflated by same-symbol re-fires, which is exactly
the bug this script's baseline number was built to correct for.

Entry: unchanged, close[t] on the breakout day (first occurrence of the run).
This script tests exit mechanics only.

Exit rules:
  CONTROL        fixed +10% TP / -6% SL, first touch (tie -> stop), 90-day cap
  TRAIL_LOW      stop(d) = max(stop(d-1), Low(d-1)), no fixed TP, no horizon cap
  DONCHIAN_M10   exit when Close(d) < MIN(Low(d-10..d-1)), no fixed TP, no cap
  ATR_CHANDELIER stop(d) = max(stop(d-1), HighestHigh(entry..d) - 2.5*ATR_14(d)), no cap

The three no-fixed-TP rules run until stopped or until that symbol's price
history ends -- censored trades are reported explicitly (mark-to-market
return as of the last available close), never dropped or force-closed.

Read-only against psx_data.db. Writes only this script's own output files.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "../psx_data.db"
N = 20
STOP_PCT = -0.06
TARGET_PCT = 0.10
MAX_HORIZON = 90        # control only
ATR_WINDOW = 14
ATR_MULT = 2.5
DONCHIAN_M = 10
FRICTION = 0.20          # % round trip, matches boring_monte_carlo_500trades.py primary
CGT_RATE = 0.15          # illustrative, wins only, same as round-2 sensitivity

# ---------------------------------------------------------------------------
# Step 1: reconstruct the 647-run decile-9 + liquidity-gated population
# (identical logic to the clustering-audit reconstruction)
# ---------------------------------------------------------------------------
panel = pd.read_csv("boring_heterogeneity_panel_20d.csv")
bo = panel[(panel["breakout"] == 1) & (panel["lookback"] == 20)].copy()
gated = bo[(bo["liquidity"] > 200_000) & (bo["stock_rs"].notna())].copy()
gated["decile"] = pd.qcut(gated["stock_rs"], 10, labels=False, duplicates="drop")
d9 = gated[gated["decile"] == 9].copy()

con = sqlite3.connect(DB)
symbols = d9["symbol"].unique().tolist()
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
        "close": g["close"].to_numpy(dtype=float),
    }
date_idx = {sym: {d: i for i, d in enumerate(pf["dates"])} for sym, pf in by_symbol.items()}

first_fire = []
for sym, g in d9.groupby("symbol"):
    idxmap = date_idx.get(sym)
    if idxmap is None:
        continue
    rows = sorted((idxmap[d], d) for d in g["date"] if d in idxmap)
    if not rows:
        continue
    run_start = rows[0]
    prev_idx = rows[0][0]
    for (idx, d) in rows[1:]:
        if idx - prev_idx > N:
            first_fire.append((sym, run_start[1]))
            run_start = (idx, d)
        prev_idx = idx
    first_fire.append((sym, run_start[1]))

print(f"Decile-9 + liquidity-gated raw rows: {len(d9):,} -> {len(first_fire):,} distinct runs (entries)")

# ---------------------------------------------------------------------------
# Step 2: ATR_14 per symbol (simple moving average of True Range)
# ---------------------------------------------------------------------------
atr_by_symbol = {}
for sym, pf in by_symbol.items():
    high, low, close = pf["high"], pf["low"], pf["close"]
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr_by_symbol[sym] = pd.Series(tr).rolling(ATR_WINDOW).mean().to_numpy()

# ---------------------------------------------------------------------------
# Step 3: per-run walk-forward, all four rules
# ---------------------------------------------------------------------------
results = {r: [] for r in ["CONTROL", "TRAIL_LOW", "DONCHIAN_M10", "ATR_CHANDELIER"]}
atr_skipped = 0

for sym, date in first_fire:
    pf = by_symbol.get(sym)
    if pf is None:
        continue
    idxmap = date_idx[sym]
    t = idxmap.get(date)
    if t is None:
        continue
    dates, high, low, close = pf["dates"], pf["high"], pf["low"], pf["close"]
    n = len(dates)
    entry = close[t]
    if entry is None or np.isnan(entry) or entry <= 0:
        continue

    # ---- CONTROL: fixed TP/SL, 90-day horizon, first touch, tie->stop ----
    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j > t:
        fwd_high = high[t + 1:end_j + 1]
        fwd_low = low[t + 1:end_j + 1]
        stop_level = entry * (1 + STOP_PCT)
        target_level = entry * (1 + TARGET_PCT)
        sh = np.where(fwd_low <= stop_level)[0]
        th_ = np.where(fwd_high >= target_level)[0]
        sd = sh[0] if len(sh) else None
        td = th_[0] if len(th_) else None
        if td is None and sd is None:
            mtm = (close[end_j] - entry) / entry * 100
            results["CONTROL"].append({"ret": mtm, "days": end_j - t, "censored": True})
        elif td is not None and (sd is None or td < sd):
            results["CONTROL"].append({"ret": TARGET_PCT * 100, "days": td + 1, "censored": False})
        else:
            results["CONTROL"].append({"ret": STOP_PCT * 100, "days": sd + 1, "censored": False})

    # ---- TRAIL_LOW: stop(d) = max(stop(d-1), Low(d-1)), ratchet BEFORE check ----
    stop = low[t]
    exit_d = None
    for d in range(t + 1, n):
        stop = max(stop, low[d - 1])
        if low[d] <= stop:
            exit_d = d
            break
    if exit_d is not None:
        ret = (stop - entry) / entry * 100
        results["TRAIL_LOW"].append({"ret": ret, "days": exit_d - t, "censored": False})
    else:
        last = n - 1
        ret_mtm = (close[last] - entry) / entry * 100
        results["TRAIL_LOW"].append({"ret": ret_mtm, "days": last - t, "censored": True})

    # ---- DONCHIAN_M10: exit when Close(d) < MIN(Low(d-10..d-1)) ----
    exit_d = None
    for d in range(t + 1, n):
        window = low[max(0, d - DONCHIAN_M):d]
        if len(window) < DONCHIAN_M:
            continue
        band = np.nanmin(window)
        if close[d] < band:
            exit_d = d
            break
    if exit_d is not None:
        ret = (close[exit_d] - entry) / entry * 100
        results["DONCHIAN_M10"].append({"ret": ret, "days": exit_d - t, "censored": False})
    else:
        last = n - 1
        ret_mtm = (close[last] - entry) / entry * 100
        results["DONCHIAN_M10"].append({"ret": ret_mtm, "days": last - t, "censored": True})

    # ---- ATR_CHANDELIER: stop(d) = max(stop(d-1), HighestHigh(entry..d) - 2.5*ATR_14(d)) ----
    atr = atr_by_symbol[sym]
    if np.isnan(atr[t]):
        atr_skipped += 1
        continue
    highest = high[t]
    stopA = highest - ATR_MULT * atr[t]
    exit_d = None
    for d in range(t + 1, n):
        highest = max(highest, high[d])
        if not np.isnan(atr[d]):
            stopA = max(stopA, highest - ATR_MULT * atr[d])
        if low[d] <= stopA:
            exit_d = d
            break
    if exit_d is not None:
        ret = (stopA - entry) / entry * 100
        results["ATR_CHANDELIER"].append({"ret": ret, "days": exit_d - t, "censored": False})
    else:
        last = n - 1
        ret_mtm = (close[last] - entry) / entry * 100
        results["ATR_CHANDELIER"].append({"ret": ret_mtm, "days": last - t, "censored": True})

print(f"ATR_CHANDELIER: {atr_skipped} run(s) skipped (insufficient history for entry-day ATR_14)")


# ---------------------------------------------------------------------------
# Step 4: report
# ---------------------------------------------------------------------------
def apply_costs(ret):
    net_friction = ret - FRICTION
    if ret > 0:
        net_cgt = ret * (1 - CGT_RATE) - FRICTION
    else:
        net_cgt = ret - FRICTION
    return net_friction, net_cgt


for rule, rows in results.items():
    df = pd.DataFrame(rows)
    n_total = len(df)
    resolved = df[df["censored"] == False].copy()
    censored = df[df["censored"] == True].copy()
    print(f"\n{'=' * 92}\n{rule}  (n={n_total})\n{'=' * 92}")
    print(f"Censored (no resolution by end of available price history): "
          f"{len(censored)} ({len(censored) / n_total * 100:.1f}%)")

    if len(resolved):
        rets = resolved["ret"].astype(float)
        costs = [apply_costs(r) for r in rets]
        nf = pd.Series([c[0] for c in costs])
        ncgt = pd.Series([c[1] for c in costs])
        print(f"Resolved: n={len(resolved)}")
        print(f"  Gross return %:            mean={rets.mean():7.3f}  median={rets.median():7.3f}  "
              f"p25={rets.quantile(.25):7.3f}  p75={rets.quantile(.75):7.3f}  p90={rets.quantile(.90):7.3f}")
        print(f"  Net of {FRICTION:.2f}% friction:      mean={nf.mean():7.3f}  median={nf.median():7.3f}  "
              f"p25={nf.quantile(.25):7.3f}  p75={nf.quantile(.75):7.3f}  p90={nf.quantile(.90):7.3f}")
        print(f"  Net of friction + {CGT_RATE*100:.0f}% CGT(wins): mean={ncgt.mean():7.3f}  median={ncgt.median():7.3f}  "
              f"p25={ncgt.quantile(.25):7.3f}  p75={ncgt.quantile(.75):7.3f}  p90={ncgt.quantile(.90):7.3f}")
        print(f"  Win rate (gross ret > 0): {(rets > 0).mean() * 100:.1f}%")
        print(f"  Avg days held: {resolved['days'].mean():.1f}   median days held: {resolved['days'].median():.1f}")

    if len(censored):
        cr = censored["ret"].astype(float)
        print(f"  [CENSORED -- mark-to-market as of data end, NOT in the stats above]")
        print(f"    mean={cr.mean():7.3f}%  median={cr.median():7.3f}%  "
              f"avg days held so far={censored['days'].mean():.1f}")

print(f"\n{'=' * 92}\nDone. Population: {len(first_fire):,} runs "
      f"(decile-9 + liquidity-gated, N=20 lookback, first-fire-of-run entries).\n{'=' * 92}")
