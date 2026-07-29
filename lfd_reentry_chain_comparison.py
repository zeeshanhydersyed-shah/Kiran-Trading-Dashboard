"""
lfd_reentry_chain_comparison.py
-----------------------------------
Real-data run of lfd_reentry_chain.py (26/26 synthetic tests passing)
against the primary n=230 set (Type-4-under-trigger excluded) -- chains
START from the same primary population used throughout this stage's
stop-loss comparisons, for a direct, apples-to-apples comparison against
the already-computed single-trade realized_R_lfd. Re-entry LEGS beyond
the first are NOT independently Type-classified (that would require
re-running breakout_classification.py on each new leg, out of scope
here) -- "primary set" refers only to the STARTING candidate of each
chain.

Reconstructs each candidate's ORIGINAL (broken) boundary deterministically
from (symbol, start, end), same pattern as every prior real-data script
in this stage -- fit_boundary() reused unmodified, boundary never refit
across legs (only price_at() extrapolated, per boundaries.py's existing,
unmodified linear formula).
"""

import sqlite3
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from research_filters import drop_placeholder_zero_bars
from lfd_reentry_chain import walk_reentry_chain, DEFAULT_MAX_REENTRIES

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
TOLERANCE_PCT = 0.015

three_way = pd.read_csv("stop_loss_three_way_results.csv")
primary_keys = three_way[three_way["type_trigger"] != 4.0].copy()
print(f"Primary set (chains start here): n={len(primary_keys)}")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []
leg_rows = []
anomalies = []

for _, cand in primary_keys.iterrows():
    sym = cand["symbol"]
    start, end = int(cand["start"]), int(cand["end"])
    direction = cand["direction"]
    breakout_idx = int(cand["breakout_idx"])

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

    hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
    lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
    hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
    lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)
    original_boundary = hi_boundary if direction == "up" else lo_boundary

    if original_boundary is None:
        anomalies.append((sym, start, end, "original boundary refit to None -- unexpected"))
        continue

    r = walk_reentry_chain(closes, highs, lows, breakout_idx, direction, boundary=original_boundary)

    if r.legs[0].r_lfd_denom <= 0:
        anomalies.append((sym, start, end, f"non-positive leg-1 r_lfd_denom={r.legs[0].r_lfd_denom}"))
        continue

    rows.append({
        "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
        "kind": cand["kind"], "outcome": cand["outcome"], "direction": direction,
        "type_trigger": cand["type_trigger"],
        "n_legs": len(r.legs), "n_reentries": r.n_reentries, "cap_bound": r.cap_bound,
        "chain_realized_R": r.chain_realized_R,
        "original_realized_R_lfd": cand["realized_R_lfd"],  # already-computed single-trade baseline
        "final_leg_exit_type": r.legs[-1].exit_type,
    })

    for leg_i, leg in enumerate(r.legs):
        leg_rows.append({
            "symbol": sym, "start": start, "end": end, "leg_index": leg_i,
            "entry_bar": leg.entry_bar, "entry_price": leg.entry_price, "lfd_level": leg.lfd_level,
            "r_lfd_denom": leg.r_lfd_denom, "exit_bar": leg.exit_bar, "exit_type": leg.exit_type,
            "realized_R": leg.realized_R,
        })

conn.close()

res = pd.DataFrame(rows)
legs_df = pd.DataFrame(leg_rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/lfd_reentry_chain_results.csv", index=False)
legs_df.to_csv("C:/Users/Lenovo/psx_pipeline/lfd_reentry_chain_legs.csv", index=False)

print(f"\n{len(res)} chains built, {len(anomalies)} anomalies")
for a in anomalies:
    print(f"  ANOMALY: {a}")

n_with_reentry = (res["n_reentries"] > 0).sum()
print(f"\n{'='*70}\nRE-ENTRY FREQUENCY: {n_with_reentry}/{len(res)} chains had >=1 re-entry "
      f"({n_with_reentry/len(res)*100:.1f}%)\n{'='*70}")

print(f"\n--- chain length (n_legs) distribution ---")
print(res["n_legs"].value_counts().sort_index().to_string())

print(f"\n--- n_reentries distribution ---")
print(res["n_reentries"].value_counts().sort_index().to_string())

n_cap_bound = res["cap_bound"].sum()
print(f"\n--- cap binding: max_reentries={DEFAULT_MAX_REENTRIES} was reached AND a further "
      f"re-entry existed but wasn't taken ---")
print(f"  {n_cap_bound}/{len(res)} chains ({n_cap_bound/len(res)*100:.2f}%)")

print(f"\n{'='*70}\nCHAIN realized_R vs. ORIGINAL SINGLE-TRADE realized_R_lfd, full n={len(res)}\n{'='*70}")

def describe(series, label):
    s = series.dropna()
    print(f"  {label}: n={len(s)}  mean={s.mean():.4f}  median={s.median():.4f}  "
          f"std={s.std():.4f}  min={s.min():.4f}  max={s.max():.4f}")

describe(res["original_realized_R_lfd"], "original single-trade realized_R_lfd")
describe(res["chain_realized_R"], "chain_realized_R (all legs summed)")

res["recovered"] = res["chain_realized_R"] - res["original_realized_R_lfd"]
print(f"\n--- chain minus original, full set ---")
describe(res["recovered"], "chain_realized_R - original_realized_R_lfd")

reentered = res[res["n_reentries"] > 0].copy()
print(f"\n{'='*70}\nSAME COMPARISON, RE-ENTERED CHAINS ONLY (n={len(reentered)})\n{'='*70}")
describe(reentered["original_realized_R_lfd"], "original single-trade realized_R_lfd")
describe(reentered["chain_realized_R"], "chain_realized_R")
describe(reentered["recovered"], "chain_realized_R - original_realized_R_lfd")

n_better = (reentered["chain_realized_R"] > reentered["original_realized_R_lfd"]).sum()
n_worse = (reentered["chain_realized_R"] < reentered["original_realized_R_lfd"]).sum()
n_tie = (reentered["chain_realized_R"] == reentered["original_realized_R_lfd"]).sum()
print(f"\n  chain beat original single-trade: {n_better}/{len(reentered)}")
print(f"  chain worse than original single-trade: {n_worse}/{len(reentered)}")
print(f"  tie: {n_tie}/{len(reentered)}")

print(f"\n--- by Type (trigger variant), re-entered chains only ---")
for t, grp in reentered.groupby("type_trigger"):
    print(f"\n  Type {int(t)} (n={len(grp)})")
    describe(grp["original_realized_R_lfd"], "    original")
    describe(grp["chain_realized_R"], "    chain")

print(f"\nSaved {len(res)} chain rows to lfd_reentry_chain_results.csv, "
      f"{len(legs_df)} leg rows to lfd_reentry_chain_legs.csv")
