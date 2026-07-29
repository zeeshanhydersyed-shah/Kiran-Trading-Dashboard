"""
triangle_measured_move_analysis.py
-------------------------------------
Descriptive-only post-breakout performance analysis on the canonical
302-symbol classified-triangle set (triangle_full_universe_results.csv,
544 candidates). No pipeline changes -- reuses find_pivots_collapsed(),
fit_boundary(), and the exact (symbol, start, end) windows already
recorded, to deterministically reconstruct each candidate's upper/lower
Boundary objects.

For every candidate with a recorded breakout (up/down/whipsaw/sequential
-- the 2 "none" candidates are excluded), at horizons of 10/20/30/60/90
trading days after the breakout bar:

  1. Raw % price move from the breakout-bar close, in the breakout
     direction (a down-breakout's decline is reported as positive).
  2. % of the "measured move" achieved. Measured move = triangle height,
     defined here as upper_boundary.price_at(breakout_idx) -
     lower_boundary.price_at(breakout_idx) (both boundary lines evaluated
     AT the breakout bar, per explicit instruction -- not at the
     pattern's start). Actual price move (in price units, favorable
     direction = positive) divided by this height, as a percentage.

KNOWN ISSUE, FIXED HERE (2026-07-15 follow-up): pct_of_measured_move's
mean is dominated by extreme outliers when the measured-move height is
small relative to price -- this happens whenever a breakout lands at or
past the pattern's apex, where the two boundary lines have nearly or
fully converged, making the denominator near-zero. Confirmed directly:
25.9% of all candidate-horizon rows had |pct_of_measured_move| > 500%,
max 223,375% (CRTM 3560-3640). Fix: report a TRIMMED mean (top/bottom
10% dropped) for pct_of_measured_move instead of the raw mean --
raw_pct_move's mean is unaffected by this and is left as a plain mean.
Also reports, per horizon, how many candidates have measured-move height
< 2% of breakout price (a proposed, adjustable threshold) -- to show
whether the outlier mass is concentrated in a small set of near-flat-
apex triangles or spread broadly.

Breakout point = the FIRST boundary violation chronologically:
  - outcome up/down: the single recorded violation (up_idx / down_idx)
  - outcome whipsaw/sequential: min(up_idx, down_idx), direction = whichever
    side that earlier violation was on

If a horizon's target bar falls outside the available price history for
that symbol, the candidate is excluded from THAT horizon's stats (not
truncated/extrapolated) and counted in a per-horizon exclusion tally.

No Type 1-4 classification, no stop-loss logic. Descriptive only.
"""
import sqlite3
import pandas as pd
import numpy as np

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
RESULTS_CSV = "C:/Users/Lenovo/psx_pipeline/triangle_full_universe_results.csv"
TOLERANCE_PCT = 0.015
HORIZONS = [10, 20, 30, 60, 90]

candidates = pd.read_csv(RESULTS_CSV)
n_total = len(candidates)
candidates = candidates[candidates["outcome"] != "none"].reset_index(drop=True)
n_excluded_none = n_total - len(candidates)
print(f"{n_total} classified candidates loaded, {n_excluded_none} 'none' outcomes excluded, "
      f"{len(candidates)} candidates for this analysis")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}  # symbol -> (df, closes, all_pivots)

rows = []
height_nonpositive_count = 0

for _, cand in candidates.iterrows():
    sym = cand["symbol"]
    start, end = int(cand["start"]), int(cand["end"])
    outcome = cand["outcome"]
    up_idx = cand["up_idx"]
    down_idx = cand["down_idx"]

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df["date"] = pd.to_datetime(df["date"])
        df = drop_placeholder_zero_bars(df)
        highs = df["high"].tolist()
        lows = df["low"].tolist()
        closes = df["close"].tolist()
        all_pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)
        symbol_cache[sym] = (df, closes, all_pivots)

    df, closes, all_pivots = symbol_cache[sym]

    hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
    lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
    hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
    lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)

    # determine breakout index + direction: first violation chronologically
    if outcome == "up":
        breakout_idx, direction = int(up_idx), "up"
    elif outcome == "down":
        breakout_idx, direction = int(down_idx), "down"
    else:  # whipsaw or sequential -- both recorded, use earlier one
        if up_idx <= down_idx:
            breakout_idx, direction = int(up_idx), "up"
        else:
            breakout_idx, direction = int(down_idx), "down"

    breakout_close = closes[breakout_idx]
    hi_at_breakout = hi_boundary.price_at(breakout_idx)
    lo_at_breakout = lo_boundary.price_at(breakout_idx)
    measured_move_height = abs(hi_at_breakout - lo_at_breakout)

    if measured_move_height <= 0:
        height_nonpositive_count += 1
        continue  # can't compute % of measured move -- excluded, tallied separately

    height_pct_of_price = measured_move_height / breakout_close * 100

    n = len(df)
    for h in HORIZONS:
        target_idx = breakout_idx + h
        if target_idx >= n:
            rows.append({
                "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
                "kind": cand["kind"], "outcome": outcome, "horizon": h,
                "excluded_insufficient_data": True,
                "raw_pct_move": np.nan, "pct_of_measured_move": np.nan,
                "height_pct_of_price": height_pct_of_price,
            })
            continue

        target_close = closes[target_idx]
        if direction == "up":
            move_price = target_close - breakout_close
        else:
            move_price = breakout_close - target_close

        raw_pct_move = move_price / breakout_close * 100
        pct_of_measured_move = move_price / measured_move_height * 100

        rows.append({
            "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
            "kind": cand["kind"], "outcome": outcome, "horizon": h,
            "excluded_insufficient_data": False,
            "raw_pct_move": raw_pct_move, "pct_of_measured_move": pct_of_measured_move,
            "height_pct_of_price": height_pct_of_price,
        })

conn.close()

print(f"\n{height_nonpositive_count} candidate(s) excluded entirely: measured_move_height <= 0 "
      f"(boundaries crossed at/before the breakout bar)")

res = pd.DataFrame(rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_measured_move_results.csv", index=False)

# ---- per-horizon exclusion counts (point 3) ----
print("\n=== Per-horizon exclusion counts (insufficient forward data) ===")
excl = res.groupby("horizon")["excluded_insufficient_data"].sum().astype(int)
total_per_horizon = res.groupby("horizon").size()
for h in HORIZONS:
    print(f"  horizon={h}d: {excl[h]} excluded / {total_per_horizon[h]} total candidates")

valid = res[~res["excluded_insufficient_data"]].copy()

# ---- low-height-relative-to-price diagnostic (point 2) ----
LOW_HEIGHT_THRESHOLD_PCT = 2.0  # proposed, adjustable: height < 2% of breakout price
print(f"\n=== Candidates with measured-move height < {LOW_HEIGHT_THRESHOLD_PCT}% of breakout price, per horizon ===")
for h in HORIZONS:
    sub = valid[valid["horizon"] == h]
    n_low = (sub["height_pct_of_price"] < LOW_HEIGHT_THRESHOLD_PCT).sum()
    n_tot = len(sub)
    print(f"  horizon={h}d: {n_low} / {n_tot} ({n_low/n_tot*100:.1f}%) below threshold")


def trimmed_mean(values, trim_frac=0.10):
    v = sorted(values)
    n = len(v)
    k = int(n * trim_frac)
    trimmed = v[k:n - k] if n - 2 * k > 0 else v
    return sum(trimmed) / len(trimmed)


def summarize(df, group_cols, label):
    print(f"\n=== {label} ===")
    grouped = df.groupby(group_cols + ["horizon"]) if group_cols else df.groupby(["horizon"])
    out_rows = []
    for keys, g in grouped:
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_cols + ["horizon"], keys)) if group_cols else {"horizon": keys[0]}
        row["n"] = len(g)
        row["raw_pct_move_mean"] = g["raw_pct_move"].mean()
        row["raw_pct_move_median"] = g["raw_pct_move"].median()
        row["pct_of_measured_move_trimmed_mean_10pct"] = trimmed_mean(g["pct_of_measured_move"].tolist())
        row["pct_of_measured_move_median"] = g["pct_of_measured_move"].median()
        out_rows.append(row)
    out_df = pd.DataFrame(out_rows)
    print(out_df.to_string(index=False))
    return out_df


summarize(valid, [], "Overall (all kinds, all outcomes)")
summarize(valid, ["kind"], "By triangle kind")
summarize(valid, ["outcome"], "By outcome category")

print(f"\nSaved {len(res)} candidate-horizon rows to triangle_measured_move_results.csv")
