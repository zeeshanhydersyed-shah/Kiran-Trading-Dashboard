"""
adaptive_switching_comparison.py
------------------------------------
Real-data run of the adaptive LFD-to-opposite-boundary switching rule
(adaptive_switching_stop.py, 13/13 synthetic tests passing -- see
test_adaptive_switching_stop.py) against the full n=230 primary
comparison set (Type-4-under-trigger excluded, same scope as every prior
stage). Reconstructs each candidate's ORIGINAL (broken) boundary
deterministically from (symbol, start, end), same pattern as every prior
real-data script in this stage -- fit_boundary() reused unmodified.

Reuses the already-computed opposite_stop, r_lfd_denom, etc. from
stop_loss_three_way_results.csv only for cross-checking; all switching-
rule quantities are computed fresh via adaptive_switching_walk_forward().
"""

import sqlite3
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from research_filters import drop_placeholder_zero_bars
from adaptive_switching_stop import adaptive_switching_walk_forward

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
TOLERANCE_PCT = 0.015

three_way = pd.read_csv("stop_loss_three_way_results.csv")
primary_keys = three_way[three_way["type_trigger"] != 4.0].copy()
print(f"Primary set (from stop_loss_three_way_results.csv): n={len(primary_keys)}")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []
anomalies = []

for _, cand in primary_keys.iterrows():
    sym = cand["symbol"]
    start, end = int(cand["start"]), int(cand["end"])
    direction = cand["direction"]
    breakout_idx = int(cand["breakout_idx"])
    opposite_stop = cand["opposite_stop"]

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
        anomalies.append((sym, start, end, "original (broken) boundary refit to None -- unexpected, see prior "
                                            "session's 100% coverage finding"))
        continue

    r = adaptive_switching_walk_forward(
        closes, highs, lows, breakout_idx, direction,
        boundary=original_boundary, opposite_stop=opposite_stop,
    )

    if r.r_lfd_denom <= 0 or r.r_opposite_denom <= 0:
        anomalies.append((sym, start, end, f"non-positive denom: lfd={r.r_lfd_denom}, opp={r.r_opposite_denom}"))
        continue

    rows.append({
        "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
        "kind": cand["kind"], "outcome": cand["outcome"], "direction": direction,
        "breakout_idx": breakout_idx, "type_trigger": cand["type_trigger"],
        "entry_price": r.entry_price, "lfd_level": r.lfd_level, "r_lfd_denom": r.r_lfd_denom,
        "opposite_stop": r.opposite_stop, "r_opposite_denom": r.r_opposite_denom,
        "first_breach_idx": r.first_breach_idx, "switched": r.switched, "switch_bar": r.switch_bar,
        "exit_bar": r.exit_bar, "exit_stop": r.exit_stop, "horizon_reached": r.horizon_reached,
        "realized_R_adaptive_fixed": r.realized_R_fixed, "realized_R_adaptive_rebased": r.realized_R_rebased,
        # static baselines, already computed, carried through for direct comparison
        "realized_R_lfd_static": cand["realized_R_lfd"], "realized_R_opposite_static": cand["realized_R_opposite"],
    })

conn.close()

res = pd.DataFrame(rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/adaptive_switching_results.csv", index=False)

print(f"\n{len(res)} candidates walked forward, {len(anomalies)} anomalies")
for a in anomalies:
    print(f"  ANOMALY: {a}")

def describe(series, label):
    s = series.dropna()
    if len(s) == 0:
        print(f"  {label}: n=0")
        return
    print(f"  {label}: n={len(s)}  mean={s.mean():.4f}  median={s.median():.4f}  "
          f"std={s.std():.4f}  min={s.min():.4f}  max={s.max():.4f}")

n_switched = res["switched"].sum()
print(f"\n{'='*70}\nSWITCH FREQUENCY: {n_switched}/{len(res)} ({n_switched/len(res)*100:.1f}%)\n{'='*70}")
print(res["exit_stop"].value_counts(dropna=False).to_string())

print(f"\n{'='*70}\nrealized_R DISTRIBUTIONS, FULL PRIMARY SET (n={len(res)})\n{'='*70}")
describe(res["realized_R_lfd_static"], "static LFD-only")
describe(res["realized_R_opposite_static"], "static opposite-only")
describe(res["realized_R_adaptive_fixed"], "adaptive (Convention A, fixed original-LFD denom)")
describe(res["realized_R_adaptive_rebased"], "adaptive (Convention B, re-based denom)")

print(f"\n--- by Type (trigger variant) ---")
for t, grp in res.groupby("type_trigger"):
    print(f"\n  Type {int(t)} (n={len(grp)})")
    describe(grp["realized_R_lfd_static"], "    static LFD")
    describe(grp["realized_R_opposite_static"], "    static opposite")
    describe(grp["realized_R_adaptive_fixed"], "    adaptive (A)")
    describe(grp["realized_R_adaptive_rebased"], "    adaptive (B)")
    print(f"    switched: {grp['switched'].sum()}/{len(grp)} ({grp['switched'].mean()*100:.1f}%)")

print(f"\n--- by outcome ---")
for outc, grp in res.groupby("outcome"):
    print(f"\n  outcome={outc} (n={len(grp)})")
    describe(grp["realized_R_lfd_static"], "    static LFD")
    describe(grp["realized_R_opposite_static"], "    static opposite")
    describe(grp["realized_R_adaptive_fixed"], "    adaptive (A)")
    describe(grp["realized_R_adaptive_rebased"], "    adaptive (B)")
    print(f"    switched: {grp['switched'].sum()}/{len(grp)} ({grp['switched'].mean()*100:.1f}%)")

print(f"\n{'='*70}\nSWITCHED-TRADES-ONLY COMPARISON (n={n_switched})\n{'='*70}")
sw = res[res["switched"]].copy()
describe(sw["realized_R_adaptive_fixed"], "adaptive (A) on switched trades")
describe(sw["realized_R_adaptive_rebased"], "adaptive (B) on switched trades")
describe(sw["realized_R_lfd_static"], "what static-LFD gave on these SAME trades")
describe(sw["realized_R_opposite_static"], "what static-opposite gave on these SAME trades")

sw["fixed_vs_static_lfd"] = sw["realized_R_adaptive_fixed"] - sw["realized_R_lfd_static"]
sw["fixed_vs_static_opposite"] = sw["realized_R_adaptive_fixed"] - sw["realized_R_opposite_static"]
print(f"\n  adaptive(A) minus static-LFD on switched trades: mean={sw['fixed_vs_static_lfd'].mean():.4f}  "
      f"median={sw['fixed_vs_static_lfd'].median():.4f}")
print(f"  adaptive(A) minus static-opposite on switched trades: mean={sw['fixed_vs_static_opposite'].mean():.4f}  "
      f"median={sw['fixed_vs_static_opposite'].median():.4f}")

better_than_lfd = (sw["realized_R_adaptive_fixed"] > sw["realized_R_lfd_static"]).sum()
worse_than_lfd = (sw["realized_R_adaptive_fixed"] < sw["realized_R_lfd_static"]).sum()
tie_lfd = (sw["realized_R_adaptive_fixed"] == sw["realized_R_lfd_static"]).sum()
print(f"\n  switched trades where adaptive(A) beat static-LFD: {better_than_lfd}/{n_switched}")
print(f"  switched trades where adaptive(A) lost to static-LFD: {worse_than_lfd}/{n_switched}")
print(f"  tie: {tie_lfd}/{n_switched}")

matches_opposite = (sw["realized_R_adaptive_rebased"] == sw["realized_R_opposite_static"]).sum()
print(f"\n  switched trades where adaptive(B, re-based) == static-opposite exactly: {matches_opposite}/{n_switched} "
      f"(expected to differ whenever the switch happens after opposite would ALREADY have been touched "
      f"from bar one under the static rule)")

print(f"\nSaved {len(res)} rows to adaptive_switching_results.csv")
