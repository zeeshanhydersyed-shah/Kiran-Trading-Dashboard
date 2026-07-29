"""
boring_donchian_trailing_stop_race_v2.py -- follow-up to
boring_donchian_trailing_stop_race.py. Three additions, same methodology:

1. HYBRID_TRAIL: stop(d) = max(TRAIL_LOW's stop(d), Entry x (1 - 0.08)) --
   trailing stop with a hard -8%-from-entry floor. Reports how often the
   floor (vs. the trailing component) is the binding constraint at exit.
2. Gap-down analysis for TRAIL_LOW: on each resolved trade's exit day, was
   Open(exit_day) already more than 2% below the stop level that was set
   the night before (i.e. would a real stop order have been gapped through)?
   Reports frequency AND the magnitude distribution of those gaps, not just
   a count. Uses prices_adjusted.open -- flagged coverage gaps handled
   explicitly (skipped and counted, never assumed zero-gap).
3. N=60 replication of CONTROL / TRAIL_LOW / HYBRID_TRAIL on the N=60
   decile-9 + liquidity-gated panel (boring_heterogeneity_panel_60d.csv),
   run-collapsed with gap<=60 trading days (the population's own lookback),
   for direct comparison against the N=20 result.

Donchian/ATR are not re-tested this round (already established as inferior
net-of-cost or noted as out of scope by the requester).

Read-only against psx_data.db. Writes only this script's own output.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "../psx_data.db"
STOP_PCT = -0.06
TARGET_PCT = 0.10
MAX_HORIZON = 90
FLOOR_PCT = -0.08
FRICTION = 0.20
CGT_RATE = 0.15
GAP_THRESHOLD = -0.02  # 2% below stop level counts as a "gap event"


def build_run_population(panel_path, lookback):
    panel = pd.read_csv(panel_path)
    bo = panel[(panel["breakout"] == 1) & (panel["lookback"] == lookback)].copy()
    gated = bo[(bo["liquidity"] > 200_000) & (bo["stock_rs"].notna())].copy()
    gated["decile"] = pd.qcut(gated["stock_rs"], 10, labels=False, duplicates="drop")
    d9 = gated[gated["decile"] == 9].copy()

    con = sqlite3.connect(DB)
    symbols = d9["symbol"].unique().tolist()
    placeholders = ",".join("?" for _ in symbols)
    prices = pd.read_sql_query(
        f"SELECT symbol, date, open, high, low, close FROM prices_adjusted "
        f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
        con, params=symbols
    )
    con.close()

    by_symbol = {}
    for sym, g in prices.groupby("symbol"):
        g = g.reset_index(drop=True)
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "open": g["open"].to_numpy(dtype=float),
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
            if idx - prev_idx > lookback:
                first_fire.append((sym, run_start[1]))
                run_start = (idx, d)
            prev_idx = idx
        first_fire.append((sym, run_start[1]))

    print(f"[{panel_path}, lookback={lookback}] {len(d9):,} decile-9+liquidity-gated rows "
          f"-> {len(first_fire):,} distinct runs")
    return first_fire, by_symbol, date_idx


def race_control(sym, t, by_symbol):
    pf = by_symbol[sym]
    high, low, close = pf["high"], pf["low"], pf["close"]
    n = len(close)
    entry = close[t]
    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j <= t:
        return None
    fwd_high = high[t + 1:end_j + 1]
    fwd_low = low[t + 1:end_j + 1]
    stop_level = entry * (1 + STOP_PCT)
    target_level = entry * (1 + TARGET_PCT)
    sh = np.where(fwd_low <= stop_level)[0]
    th_ = np.where(fwd_high >= target_level)[0]
    sd = sh[0] if len(sh) else None
    td = th_[0] if len(th_) else None
    if td is None and sd is None:
        return {"ret": (close[end_j] - entry) / entry * 100, "days": end_j - t, "censored": True}
    elif td is not None and (sd is None or td < sd):
        return {"ret": TARGET_PCT * 100, "days": td + 1, "censored": False}
    else:
        return {"ret": STOP_PCT * 100, "days": sd + 1, "censored": False}


def race_trail(sym, t, by_symbol, floor_pct=None):
    """floor_pct=None -> plain TRAIL_LOW. floor_pct=-0.08 -> HYBRID_TRAIL."""
    pf = by_symbol[sym]
    low, close = pf["low"], pf["close"]
    n = len(close)
    entry = close[t]
    floor_level = entry * (1 + floor_pct) if floor_pct is not None else -np.inf
    trail = low[t]
    stop = max(trail, floor_level)
    exit_d = None
    floor_binding = None
    for d in range(t + 1, n):
        trail = max(trail, low[d - 1])
        stop = max(trail, floor_level)
        if low[d] <= stop:
            exit_d = d
            floor_binding = (floor_level >= trail)
            break
    if exit_d is not None:
        ret = (stop - entry) / entry * 100
        return {"ret": ret, "days": exit_d - t, "censored": False,
                "exit_day_idx": exit_d, "stop_at_exit": stop, "floor_binding": floor_binding}
    else:
        last = n - 1
        return {"ret": (close[last] - entry) / entry * 100, "days": last - t, "censored": True,
                "exit_day_idx": None, "stop_at_exit": None, "floor_binding": None}


def apply_costs(ret):
    net_friction = ret - FRICTION
    net_cgt = ret * (1 - CGT_RATE) - FRICTION if ret > 0 else ret - FRICTION
    return net_friction, net_cgt


def report(rule, rows):
    df = pd.DataFrame(rows)
    n_total = len(df)
    resolved = df[df["censored"] == False].copy()
    censored = df[df["censored"] == True].copy()
    print(f"\n{'=' * 92}\n{rule}  (n={n_total})\n{'=' * 92}")
    print(f"Censored: {len(censored)} ({len(censored) / n_total * 100:.1f}%)")
    if len(resolved):
        rets = resolved["ret"].astype(float)
        costs = [apply_costs(r) for r in rets]
        nf = pd.Series([c[0] for c in costs])
        ncgt = pd.Series([c[1] for c in costs])
        print(f"Resolved: n={len(resolved)}")
        print(f"  Gross %:                   mean={rets.mean():7.3f}  median={rets.median():7.3f}  "
              f"p25={rets.quantile(.25):7.3f}  p75={rets.quantile(.75):7.3f}  p90={rets.quantile(.90):7.3f}")
        print(f"  Net of {FRICTION:.2f}% friction:      mean={nf.mean():7.3f}  median={nf.median():7.3f}  "
              f"p25={nf.quantile(.25):7.3f}  p75={nf.quantile(.75):7.3f}  p90={nf.quantile(.90):7.3f}")
        print(f"  Net of friction + {CGT_RATE*100:.0f}% CGT(wins): mean={ncgt.mean():7.3f}  median={ncgt.median():7.3f}  "
              f"p25={ncgt.quantile(.25):7.3f}  p75={ncgt.quantile(.75):7.3f}  p90={ncgt.quantile(.90):7.3f}")
        print(f"  Win rate: {(rets > 0).mean() * 100:.1f}%   Avg days held: {resolved['days'].mean():.1f}   "
              f"median days: {resolved['days'].median():.1f}")
    if len(censored):
        cr = censored["ret"].astype(float)
        print(f"  [CENSORED mark-to-market, NOT above]: mean={cr.mean():7.3f}%  median={cr.median():7.3f}%  "
              f"avg days held so far={censored['days'].mean():.1f}")
    return df


# ===========================================================================
# PART 1 & 2: N=20 population -- CONTROL, TRAIL_LOW, HYBRID_TRAIL + gap analysis
# ===========================================================================
print("#" * 92)
print("# PART 1: N=20 -- CONTROL / TRAIL_LOW / HYBRID_TRAIL(-8% floor)")
print("#" * 92)

first_fire_20, by_symbol_20, date_idx_20 = build_run_population("boring_heterogeneity_panel_20d.csv", 20)

control_rows, trail_rows, hybrid_rows = [], [], []
for sym, date in first_fire_20:
    idxmap = date_idx_20.get(sym)
    if idxmap is None:
        continue
    t = idxmap.get(date)
    if t is None:
        continue
    entry = by_symbol_20[sym]["close"][t]
    if entry is None or np.isnan(entry) or entry <= 0:
        continue
    c = race_control(sym, t, by_symbol_20)
    if c:
        control_rows.append(c)
    trail_rows.append({**race_trail(sym, t, by_symbol_20, floor_pct=None), "symbol": sym, "t": t})
    hybrid_rows.append({**race_trail(sym, t, by_symbol_20, floor_pct=FLOOR_PCT), "symbol": sym, "t": t})

report("CONTROL (N=20)", control_rows)
report("TRAIL_LOW (N=20)", trail_rows)
hybrid_df = report("HYBRID_TRAIL -8% floor (N=20)", hybrid_rows)

# floor-binding analysis (resolved hybrid trades only)
resolved_hybrid = hybrid_df[hybrid_df["censored"] == False]
floor_bound = resolved_hybrid["floor_binding"] == True
trail_bound = resolved_hybrid["floor_binding"] == False
print(f"\nHYBRID_TRAIL floor-binding breakdown (resolved n={len(resolved_hybrid)}):")
print(f"  Exit determined by the -8% FLOOR:      {floor_bound.sum()} ({floor_bound.mean()*100:.1f}%)")
print(f"  Exit determined by the TRAILING stop:  {trail_bound.sum()} ({trail_bound.mean()*100:.1f}%)")

# ===========================================================================
# PART 2: gap-down analysis for TRAIL_LOW exits
# ===========================================================================
print(f"\n{'#' * 92}\n# PART 2: Gap-down analysis, TRAIL_LOW exits (N=20 population)\n{'#' * 92}")

gap_events = []
no_open_data = 0
checked = 0
for row in trail_rows:
    if row["censored"] or row["exit_day_idx"] is None:
        continue
    sym, t, exit_d = row["symbol"], row["t"], row["exit_day_idx"]
    pf = by_symbol_20[sym]
    stop_at_exit = row["stop_at_exit"]
    open_px = pf["open"][exit_d]
    checked += 1
    if np.isnan(open_px):
        no_open_data += 1
        continue
    gap_pct = (open_px - stop_at_exit) / stop_at_exit * 100
    if gap_pct < GAP_THRESHOLD * 100:
        gap_events.append(gap_pct)

print(f"TRAIL_LOW resolved exits checked: {checked}")
print(f"Exit days with no Open price data available (skipped, not assumed zero-gap): "
      f"{no_open_data} ({no_open_data/checked*100:.1f}%)")
evaluable = checked - no_open_data
print(f"Evaluable exits: {evaluable}")
print(f"Exits where Open(exit_day) gapped > 2% below the overnight stop level: "
      f"{len(gap_events)} ({len(gap_events)/evaluable*100:.1f}% of evaluable exits)")
if gap_events:
    ge = pd.Series(gap_events)
    print(f"Gap magnitude distribution among flagged events (% below stop level, negative=worse):")
    print(f"  mean={ge.mean():.2f}  median={ge.median():.2f}  min={ge.min():.2f}  "
          f"p10={ge.quantile(.10):.2f}  p25={ge.quantile(.25):.2f}")

# ===========================================================================
# PART 3: N=60 replication
# ===========================================================================
print(f"\n{'#' * 92}\n# PART 3: N=60 replication -- CONTROL / TRAIL_LOW / HYBRID_TRAIL\n{'#' * 92}")

first_fire_60, by_symbol_60, date_idx_60 = build_run_population("boring_heterogeneity_panel_60d.csv", 60)

control_rows_60, trail_rows_60, hybrid_rows_60 = [], [], []
for sym, date in first_fire_60:
    idxmap = date_idx_60.get(sym)
    if idxmap is None:
        continue
    t = idxmap.get(date)
    if t is None:
        continue
    entry = by_symbol_60[sym]["close"][t]
    if entry is None or np.isnan(entry) or entry <= 0:
        continue
    c = race_control(sym, t, by_symbol_60)
    if c:
        control_rows_60.append(c)
    trail_rows_60.append(race_trail(sym, t, by_symbol_60, floor_pct=None))
    hybrid_rows_60.append(race_trail(sym, t, by_symbol_60, floor_pct=FLOOR_PCT))

report("CONTROL (N=60)", control_rows_60)
report("TRAIL_LOW (N=60)", trail_rows_60)
hybrid_df_60 = report("HYBRID_TRAIL -8% floor (N=60)", hybrid_rows_60)

resolved_hybrid_60 = hybrid_df_60[hybrid_df_60["censored"] == False]
fb60 = resolved_hybrid_60["floor_binding"] == True
tb60 = resolved_hybrid_60["floor_binding"] == False
print(f"\nHYBRID_TRAIL(N=60) floor-binding breakdown (resolved n={len(resolved_hybrid_60)}):")
print(f"  Exit determined by the -8% FLOOR:      {fb60.sum()} ({fb60.mean()*100:.1f}%)")
print(f"  Exit determined by the TRAILING stop:  {tb60.sum()} ({tb60.mean()*100:.1f}%)")

print(f"\n{'=' * 92}\nDone.\n{'=' * 92}")
