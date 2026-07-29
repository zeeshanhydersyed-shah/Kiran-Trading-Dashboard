"""
stop_loss_r_multiple_comparison.py
------------------------------------
Real-data run of the walk-forward LFD-vs-rolling-low stop comparison
(stop_loss_definitions.py, 28/28 synthetic tests passing -- see
test_stop_loss_definitions.py) against the canonical 544-candidate
classified-triangle set. Descriptive only -- no strategy conclusion.

Inputs:
  triangle_full_universe_results.csv       -- candidate list, up_idx/down_idx
  breakout_classification_variant_results.csv -- Type 1-4 under lfd_variant="trigger"
  triangle_measured_move_results.csv       -- fixed-horizon forward returns,
                                               used ONLY for the separate
                                               Type-4-exclusion cost analysis

breakout_idx/direction derivation from (outcome, up_idx, down_idx) matches
breakout_classification_variant_comparison.py exactly (same "first
chronological violation wins" rule for whipsaw/sequential), for
consistency with the already-published Type 1-4 results this run joins
against.

SCOPE (locked, confirmed by Zeeshan -- flagged as a disagreement in the
prior definitions-lock report, but implemented as decided, not
re-litigated here): candidates classified Type 4 under lfd_variant="trigger"
are EXCLUDED from the primary comparison and reported separately as the
"cost of the LFD stop" -- what fraction of these were otherwise-successful
(outcome up/down) trades, and what forward move (from the already-computed
triangle_measured_move_results.csv) they gave up.
"""

import sqlite3
import pandas as pd

from research_filters import drop_placeholder_zero_bars
from stop_loss_definitions import walk_forward

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"

candidates = pd.read_csv("triangle_full_universe_results.csv")
variants = pd.read_csv("breakout_classification_variant_results.csv")
measured_move = pd.read_csv("triangle_measured_move_results.csv")

trigger_types = variants[variants["variant"] == "trigger"][
    ["symbol", "start", "end", "type"]
].rename(columns={"type": "type_trigger"})

candidates = candidates.merge(trigger_types, on=["symbol", "start", "end"], how="left")

print(f"{len(candidates)} candidates loaded")
print(f"Type-4-under-trigger: {(candidates['type_trigger'] == 4.0).sum()}")
print(f"outcome='none' (excluded, no breakout event): {(candidates['outcome'] == 'none').sum()}")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []
anomalies = []  # (symbol, start, end, reason) -- degenerate R denominators etc, flagged not hidden

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
    else:  # whipsaw or sequential -- first chronological violation wins
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
        symbol_cache[sym] = (df["high"].tolist(), df["low"].tolist(), df["close"].tolist())

    highs, lows, closes = symbol_cache[sym]

    if breakout_idx >= len(closes) - 1:
        anomalies.append((sym, start, end, "breakout_idx at/past last available bar -- no forward data at all"))
        continue

    r = walk_forward(closes, highs, lows, breakout_idx, direction)

    if r.r_lfd_denom <= 0 or (r.r_rolling_denom is not None and r.r_rolling_denom <= 0):
        anomalies.append((sym, start, end, f"non-positive R denominator: lfd={r.r_lfd_denom}, rolling={r.r_rolling_denom}"))
        continue

    rows.append({
        "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
        "kind": cand["kind"], "outcome": outcome, "direction": direction,
        "breakout_idx": breakout_idx, "type_trigger": cand["type_trigger"],
        "entry_price": r.entry_price, "lfd_level": r.lfd_level, "r_lfd_denom": r.r_lfd_denom,
        "rolling_status": r.rolling_status, "rolling_stop": r.rolling_stop,
        "r_rolling_denom": r.r_rolling_denom,
        "lfd_hit_bar": r.lfd_hit_bar, "rolling_hit_bar": r.rolling_hit_bar,
        "anchor_bar": r.anchor_bar, "simultaneous_hit": r.simultaneous_hit,
        "horizon_reached": r.horizon_reached,
        "realized_R_lfd": r.realized_R_lfd, "realized_R_rolling": r.realized_R_rolling,
    })

conn.close()

res = pd.DataFrame(rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/stop_loss_r_multiple_results.csv", index=False)
print(f"\n{len(res)} candidates walked forward, {len(anomalies)} anomalies flagged (excluded from output)")
for a in anomalies:
    print(f"  ANOMALY: {a}")

# ═══════════════════════════════════════════════════════════════════════
# PRIMARY COMPARISON -- excludes Type-4-under-trigger (locked scope)
# ═══════════════════════════════════════════════════════════════════════
primary = res[res["type_trigger"] != 4.0].copy()
excluded_t4 = res[res["type_trigger"] == 4.0].copy()

print(f"\n{'='*70}\nPRIMARY COMPARISON (excludes {len(excluded_t4)} Type-4-under-trigger): n={len(primary)}\n{'='*70}")

def describe(series, label):
    s = series.dropna()
    if len(s) == 0:
        print(f"  {label}: n=0")
        return
    print(f"  {label}: n={len(s)}  mean={s.mean():.4f}  median={s.median():.4f}  "
          f"std={s.std():.4f}  min={s.min():.4f}  max={s.max():.4f}")

print("\n--- realized_R_lfd (all primary candidates -- LFD always defined) ---")
describe(primary["realized_R_lfd"], "realized_R_lfd")

print("\n--- realized_R_rolling (only where rolling_status='ok') ---")
describe(primary["realized_R_rolling"], "realized_R_rolling")

print(f"\n--- rolling-side availability ---")
print(primary["rolling_status"].value_counts().to_string())

print(f"\n--- simultaneous-touch frequency ---")
print(f"  {primary['simultaneous_hit'].sum()} / {len(primary)} "
      f"({primary['simultaneous_hit'].sum()/len(primary)*100:.1f}%)")

print(f"\n--- by triangle kind ---")
for kind, grp in primary.groupby("kind"):
    print(f"\n  kind={kind} (n={len(grp)})")
    describe(grp["realized_R_lfd"], "    realized_R_lfd")
    describe(grp["realized_R_rolling"], "    realized_R_rolling")

print(f"\n--- by outcome ---")
for outc, grp in primary.groupby("outcome"):
    print(f"\n  outcome={outc} (n={len(grp)})")
    describe(grp["realized_R_lfd"], "    realized_R_lfd")
    describe(grp["realized_R_rolling"], "    realized_R_rolling")

# Head-to-head: only where both are defined (rolling_status == "ok")
h2h = primary[primary["rolling_status"] == "ok"].copy()
h2h["lfd_wins"] = h2h["realized_R_lfd"] > h2h["realized_R_rolling"]
h2h["rolling_wins"] = h2h["realized_R_rolling"] > h2h["realized_R_lfd"]
h2h["tie"] = h2h["realized_R_lfd"] == h2h["realized_R_rolling"]
print(f"\n--- head-to-head (n={len(h2h)}, both stops defined) ---")
print(f"  LFD realizes higher R:      {h2h['lfd_wins'].sum()} ({h2h['lfd_wins'].mean()*100:.1f}%)")
print(f"  Rolling realizes higher R:  {h2h['rolling_wins'].sum()} ({h2h['rolling_wins'].mean()*100:.1f}%)")
print(f"  Tie:                        {h2h['tie'].sum()} ({h2h['tie'].mean()*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════════════
# TYPE-4-EXCLUSION COST ANALYSIS (separate, per locked scope)
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\nTYPE-4-UNDER-TRIGGER COST ANALYSIS: n={len(excluded_t4)}\n{'='*70}")

t4_updown = excluded_t4[excluded_t4["outcome"].isin(["up", "down"])].copy()
print(f"\nOf {len(excluded_t4)} Type-4-excluded candidates, "
      f"{len(t4_updown)} ({len(t4_updown)/len(excluded_t4)*100:.1f}%) were otherwise-successful "
      f"(outcome up/down) trades the LITERAL LFD stop would have exited.")

print(f"\n--- outcome breakdown of Type-4-excluded candidates ---")
print(excluded_t4["outcome"].value_counts().to_string())

mm_keyed = measured_move.set_index(["symbol", "start", "end", "horizon"])
print(f"\n--- forgone forward move (raw_pct_move), otherwise-successful Type-4 candidates only ---")
for horizon in sorted(measured_move["horizon"].unique()):
    vals = []
    for _, row in t4_updown.iterrows():
        key = (row["symbol"], row["start"], row["end"], horizon)
        if key in mm_keyed.index:
            v = mm_keyed.loc[key, "raw_pct_move"]
            if pd.notna(v):
                vals.append(v)
    if vals:
        s = pd.Series(vals)
        print(f"  {horizon}d: n={len(s)}  mean={s.mean():.2f}%  median={s.median():.2f}%  "
              f"min={s.min():.2f}%  max={s.max():.2f}%")
    else:
        print(f"  {horizon}d: n=0")

print(f"\nSaved {len(res)} rows to stop_loss_r_multiple_results.csv")
