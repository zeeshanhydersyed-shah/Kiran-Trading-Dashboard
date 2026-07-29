"""
stop_loss_opposite_boundary_comparison.py
--------------------------------------------
Adds the third stop-comparison arm (opposite/un-broken boundary's price at
the breakout bar) to the LFD-vs-rolling walk-forward already run in
stop_loss_r_multiple_comparison.py. Reconstructs each candidate's fitted
Boundary objects deterministically from (symbol, start, end), exactly as
breakout_classification_variant_comparison.py does -- fit_boundary() is
reused unmodified, never refit differently. opposite_stop is a single
price evaluation (boundary.price_at(breakout_idx)), not a re-fit.

Same primary-set scope as before: excludes Type-4-under-trigger and the
same LFD/rolling degenerate-denominator anomalies already flagged in the
prior run, so n=230 matches exactly.
"""

import sqlite3
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from research_filters import drop_placeholder_zero_bars
from stop_loss_definitions import walk_forward

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
TOLERANCE_PCT = 0.015

candidates = pd.read_csv("triangle_full_universe_results.csv")
variants = pd.read_csv("breakout_classification_variant_results.csv")
measured_move = pd.read_csv("triangle_measured_move_results.csv")

trigger_types = variants[variants["variant"] == "trigger"][
    ["symbol", "start", "end", "type"]
].rename(columns={"type": "type_trigger"})
candidates = candidates.merge(trigger_types, on=["symbol", "start", "end"], how="left")

print(f"{len(candidates)} candidates loaded")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []
anomalies = []
opposite_boundary_none = []       # fit_boundary() returned None for the opposite side
opposite_denom_degenerate = []    # opposite_stop computed but on the wrong side of entry

for _, cand in candidates.iterrows():
    sym = cand["symbol"]
    outcome = cand["outcome"]
    if outcome == "none":
        continue

    start, end = int(cand["start"]), int(cand["end"])
    up_idx, down_idx = cand["up_idx"], cand["down_idx"]

    if outcome == "up":
        breakout_idx, direction = int(up_idx), "up"
    elif outcome == "down":
        breakout_idx, direction = int(down_idx), "down"
    else:
        if up_idx <= down_idx:
            breakout_idx, direction = int(up_idx), "up"
        else:
            breakout_idx, direction = int(down_idx), "down"

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df = drop_placeholder_zero_bars(df)
        highs_all = df["high"].tolist()
        lows_all = df["low"].tolist()
        closes_all = df["close"].tolist()
        all_pivots = find_pivots_collapsed(closes_all, highs_all, lows_all, left=3, right=3)
        symbol_cache[sym] = (highs_all, lows_all, closes_all, all_pivots)

    highs, lows, closes, all_pivots = symbol_cache[sym]

    if breakout_idx >= len(closes) - 1:
        anomalies.append((sym, start, end, "breakout_idx at/past last available bar"))
        continue

    hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
    lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
    hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
    lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)

    if hi_boundary is None or lo_boundary is None:
        opposite_boundary_none.append((sym, start, end, "hi_boundary" if hi_boundary is None else "lo_boundary"))

    opposite_boundary = lo_boundary if direction == "up" else hi_boundary
    opposite_stop = opposite_boundary.price_at(breakout_idx) if opposite_boundary is not None else None

    r = walk_forward(closes, highs, lows, breakout_idx, direction, opposite_stop=opposite_stop)

    if opposite_stop is not None and r.opposite_stop is None:
        # walk_forward silently deactivated it (denom <= 0) -- distinct from
        # fit_boundary() returning None; report separately, not conflated.
        opposite_denom_degenerate.append((sym, start, end, opposite_stop, r.entry_price))

    if r.r_lfd_denom <= 0 or (r.r_rolling_denom is not None and r.r_rolling_denom <= 0):
        anomalies.append((sym, start, end, "non-positive LFD/rolling R denominator (same as prior run)"))
        continue

    rows.append({
        "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
        "kind": cand["kind"], "outcome": outcome, "direction": direction,
        "breakout_idx": breakout_idx, "type_trigger": cand["type_trigger"],
        "entry_price": r.entry_price,
        "lfd_level": r.lfd_level, "r_lfd_denom": r.r_lfd_denom,
        "rolling_status": r.rolling_status, "rolling_stop": r.rolling_stop, "r_rolling_denom": r.r_rolling_denom,
        "opposite_stop": r.opposite_stop, "r_opposite_denom": r.r_opposite_denom,
        "lfd_hit_bar": r.lfd_hit_bar, "rolling_hit_bar": r.rolling_hit_bar, "opposite_hit_bar": r.opposite_hit_bar,
        "anchor_bar": r.anchor_bar, "simultaneous_hit": r.simultaneous_hit, "horizon_reached": r.horizon_reached,
        "realized_R_lfd": r.realized_R_lfd, "realized_R_rolling": r.realized_R_rolling,
        "realized_R_opposite": r.realized_R_opposite,
    })

conn.close()

res = pd.DataFrame(rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/stop_loss_three_way_results.csv", index=False)

print(f"\n{len(res)} candidates walked forward, {len(anomalies)} LFD/rolling anomalies excluded "
      f"(same set as the prior 2-stop run)")
print(f"\nOpposite-boundary coverage:")
print(f"  fit_boundary() returned None for the opposite side: {len(opposite_boundary_none)} candidates")
for a in opposite_boundary_none:
    print(f"    {a}")
print(f"  opposite_stop computed but degenerate (wrong side of entry, deactivated): {len(opposite_denom_degenerate)} candidates")
for a in opposite_denom_degenerate:
    print(f"    {a}")

n_with_opposite = res["opposite_stop"].notna().sum()
print(f"\nOpposite-boundary stop defined for {n_with_opposite}/{len(res)} candidates in the walked-forward set "
      f"({n_with_opposite/len(res)*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════════════
primary = res[res["type_trigger"] != 4.0].copy()
print(f"\n{'='*70}\nPRIMARY SET: n={len(primary)}\n{'='*70}")

def describe(series, label):
    s = series.dropna()
    if len(s) == 0:
        print(f"  {label}: n=0")
        return
    print(f"  {label}: n={len(s)}  mean={s.mean():.4f}  median={s.median():.4f}  "
          f"std={s.std():.4f}  min={s.min():.4f}  max={s.max():.4f}")

print(f"\nOpposite-boundary coverage within primary: "
      f"{primary['opposite_stop'].notna().sum()}/{len(primary)} "
      f"({primary['opposite_stop'].notna().sum()/len(primary)*100:.1f}%)")

print("\n--- realized_R_opposite (primary, where defined) ---")
describe(primary["realized_R_opposite"], "realized_R_opposite")

print(f"\n--- by triangle kind ---")
for kind, grp in primary.groupby("kind"):
    print(f"\n  kind={kind} (n={len(grp)})")
    describe(grp["realized_R_opposite"], "    realized_R_opposite")

print(f"\n--- by outcome ---")
for outc, grp in primary.groupby("outcome"):
    print(f"\n  outcome={outc} (n={len(grp)})")
    describe(grp["realized_R_opposite"], "    realized_R_opposite")

print(f"\n--- opposite_stop vs LFD/rolling width, primary where all three defined ---")
all3 = primary[primary["opposite_stop"].notna() & (primary["rolling_status"] == "ok")].copy()
print(f"  n={len(all3)}")
if len(all3):
    all3["opp_wider_than_lfd"] = all3["r_opposite_denom"] > all3["r_lfd_denom"]
    all3["opp_wider_than_rolling"] = all3["r_opposite_denom"] > all3["r_rolling_denom"]
    print(f"  opposite wider than LFD: {all3['opp_wider_than_lfd'].sum()}/{len(all3)} "
          f"({all3['opp_wider_than_lfd'].mean()*100:.1f}%)")
    print(f"  opposite wider than rolling: {all3['opp_wider_than_rolling'].sum()}/{len(all3)} "
          f"({all3['opp_wider_than_rolling'].mean()*100:.1f}%)")
    print(f"  opposite fires before LFD (breaks the rolling-side invariant): "
          f"{(all3['opposite_hit_bar'].notna() & (all3['opposite_hit_bar'] < all3['lfd_hit_bar'].fillna(1e9))).sum()}")

print(f"\n--- three-way head-to-head (n where all three realized_R are defined) ---")
h3 = primary.dropna(subset=["realized_R_lfd", "realized_R_rolling", "realized_R_opposite"]).copy()
print(f"  n={len(h3)}")
if len(h3):
    def winner(row):
        vals = {"lfd": row["realized_R_lfd"], "rolling": row["realized_R_rolling"], "opposite": row["realized_R_opposite"]}
        best = max(vals.values())
        winners = [k for k, v in vals.items() if v == best]
        return "tie" if len(winners) > 1 else winners[0]
    h3["winner"] = h3.apply(winner, axis=1)
    print(h3["winner"].value_counts().to_string())

print(f"\nSaved {len(res)} rows to stop_loss_three_way_results.csv")
