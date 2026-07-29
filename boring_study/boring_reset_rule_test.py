"""
boring_reset_rule_test.py -- measurement-only test of a proposed structural
reset condition for the breakout re-fire/clustering problem (round 3
finding: 90.11% of N=20 occurrences are within N trading days of another
same-symbol occurrence). Does NOT modify boring_signals.py or any
production file. Read-only against psx_data.db and this folder's existing
CSVs.

Proposed rule: after a fire on symbol S at day t, suppress further breakout
signals on S until Close(d) < MIN(Low[d-N..d-1]) (the lower Donchian band)
for at least K consecutive day(s) -- i.e. price must genuinely break back
below its own trailing N-day range before a subsequent breakout counts.
K=1 is the primary spec; K=2 is tested as a sensitivity check.

Same-day precedence, stated explicitly: the fire-eligibility check on day d
uses the suppression state as of the START of day d (before today's own
reset condition is evaluated). A symbol cannot reset and re-fire on the
same day -- reset only takes effect starting the following day. This
avoids same-day ambiguity between "closed below the lower band" and
"closed above the upper band" (which are near-mutually-exclusive per day
anyway, since the upper band >= lower band by construction).

Validation built in: the raw (unsuppressed) fire condition replicated here
must reproduce the existing boring_donchian_occurrences.csv exactly
(1,698 symbols, 80,744 rows) -- checked explicitly before trusting any
downstream suppressed/surviving split.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "../psx_data.db"
N = 20
BUFFER = 1.01
STOP_PCT = -0.06
TARGET_PCT = 0.10
MAX_HORIZON = 90
FRICTION = 0.20
CGT_RATE = 0.15

# ---------------------------------------------------------------------------
# Step 0: load the original raw occurrence file (for symbol list + validation)
# ---------------------------------------------------------------------------
occ_orig = pd.read_csv("boring_donchian_occurrences.csv")
orig_symbols = sorted(occ_orig["symbol"].unique())
orig_pairs = set(zip(occ_orig["symbol"], occ_orig["date"]))
print(f"Original raw occurrence file: {len(occ_orig):,} rows, {len(orig_symbols):,} symbols")

con = sqlite3.connect(DB)
placeholders = ",".join("?" for _ in orig_symbols)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted WHERE symbol IN ({placeholders}) "
    f"ORDER BY symbol, date",
    con, params=orig_symbols
)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(), "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float), "close": g["close"].to_numpy(dtype=float),
    }
date_idx = {sym: {d: i for i, d in enumerate(pf["dates"])} for sym, pf in by_symbol.items()}

# ---------------------------------------------------------------------------
# Step 1: per-symbol day-by-day simulation -- raw fire + suppress state (K=1, K=2)
# ---------------------------------------------------------------------------
records = []  # symbol, date, raw_fire(always True here), survived_k1, survived_k2

for sym, pf in by_symbol.items():
    high, low, close, dates = pf["high"], pf["low"], pf["close"], pf["dates"]
    n = len(close)
    if n < N + 1:
        continue
    suppressed_k1 = False
    suppressed_k2 = False
    below_streak = 0  # consecutive days closed below the lower band, for K=2

    for d in range(N, n):
        prior_high = np.nanmax(high[d - N:d])
        lower_band = np.nanmin(low[d - N:d])
        c = close[d]
        if np.isnan(prior_high) or np.isnan(lower_band) or np.isnan(c):
            continue

        raw_fire = c > prior_high * BUFFER

        if raw_fire:
            records.append({
                "symbol": sym, "date": dates[d],
                "survived_k1": not suppressed_k1,
                "survived_k2": not suppressed_k2,
            })
            if not suppressed_k1:
                suppressed_k1 = True
            if not suppressed_k2:
                suppressed_k2 = True

        # reset condition evaluated AFTER today's fire check (takes effect tomorrow)
        below_today = c < lower_band
        if below_today:
            below_streak += 1
        else:
            below_streak = 0

        if suppressed_k1 and below_today:
            suppressed_k1 = False
        if suppressed_k2 and below_streak >= 2:
            suppressed_k2 = False

sim = pd.DataFrame(records)
print(f"Simulated raw fires: {len(sim):,}")

# ---------------------------------------------------------------------------
# Step 2: validation -- must match the original occurrence file exactly
# ---------------------------------------------------------------------------
sim_pairs = set(zip(sim["symbol"], sim["date"]))
missing_from_sim = orig_pairs - sim_pairs
extra_in_sim = sim_pairs - orig_pairs
print(f"VALIDATION: {len(missing_from_sim)} pairs in original file but missing from simulation")
print(f"VALIDATION: {len(extra_in_sim)} pairs in simulation but not in original file")
if missing_from_sim or extra_in_sim:
    print("WARNING: simulation does not exactly reproduce the original occurrence file -- "
          "results below should be treated with reduced confidence until reconciled.")
else:
    print("VALIDATION PASSED: exact match to boring_donchian_occurrences.csv.")

sim.to_csv("boring_reset_rule_simulation.csv", index=False)

# ---------------------------------------------------------------------------
# Step 3 (Part A): does the reset rule solve the clustering problem?
# ---------------------------------------------------------------------------
print(f"\n{'#'*92}\n# PART A: clustering rate, before vs after the reset rule\n{'#'*92}")

for k_label, col in [("K=1", "survived_k1"), ("K=2", "survived_k2")]:
    suppressed_frac = 1 - sim[col].mean()
    print(f"\n{k_label}: suppressed {sim[~sim[col]].shape[0]:,} of {len(sim):,} raw fires "
          f"({suppressed_frac*100:.2f}%)")

    surv = sim[sim[col]].copy()
    # recompute the round-3 clustering metric on the SURVIVING set only
    flagged = 0
    total_checked = 0
    for sym, g in surv.groupby("symbol"):
        idxmap = date_idx.get(sym)
        if idxmap is None:
            continue
        idxs = sorted(idxmap[d] for d in g["date"] if d in idxmap)
        if len(idxs) < 2:
            continue
        total_checked += len(idxs)
        diffs = np.diff(idxs)
        is_flagged = np.zeros(len(idxs), dtype=bool)
        is_flagged[:-1] |= (diffs <= N)
        is_flagged[1:] |= (diffs <= N)
        flagged += is_flagged.sum()
    print(f"  Surviving occurrences: {len(surv):,}")
    print(f"  Of those, still within N={N} trading days of another same-symbol survivor: "
          f"{flagged:,} ({flagged/len(surv)*100:.2f}%)  [round-3 baseline on ALL raw occurrences: 90.11%]")

# ---------------------------------------------------------------------------
# Step 4: race functions (identical methodology to rounds 4/5)
# ---------------------------------------------------------------------------
def race_control(sym, t, by_symbol):
    pf = by_symbol[sym]
    high, low, close = pf["high"], pf["low"], pf["close"]
    n = len(close)
    entry = close[t]
    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j <= t:
        return None
    fwd_high = high[t+1:end_j+1]; fwd_low = low[t+1:end_j+1]
    stop_level = entry * (1 + STOP_PCT); target_level = entry * (1 + TARGET_PCT)
    sh = np.where(fwd_low <= stop_level)[0]; th_ = np.where(fwd_high >= target_level)[0]
    sd = sh[0] if len(sh) else None; td = th_[0] if len(th_) else None
    if td is None and sd is None:
        return {"ret": (close[end_j]-entry)/entry*100, "days": end_j-t, "censored": True}
    elif td is not None and (sd is None or td < sd):
        return {"ret": TARGET_PCT*100, "days": td+1, "censored": False}
    else:
        return {"ret": STOP_PCT*100, "days": sd+1, "censored": False}


def race_trail(sym, t, by_symbol):
    pf = by_symbol[sym]
    low, close = pf["low"], pf["close"]
    n = len(close)
    entry = close[t]
    stop = low[t]
    exit_d = None
    for d in range(t+1, n):
        stop = max(stop, low[d-1])
        if low[d] <= stop:
            exit_d = d
            break
    if exit_d is not None:
        return {"ret": (stop-entry)/entry*100, "days": exit_d-t, "censored": False}
    else:
        last = n-1
        return {"ret": (close[last]-entry)/entry*100, "days": last-t, "censored": True}


def apply_costs(ret):
    nf = ret - FRICTION
    ncgt = ret*(1-CGT_RATE) - FRICTION if ret > 0 else ret - FRICTION
    return nf, ncgt


def summarize_group(label, entries, by_symbol):
    control_rows, trail_rows = [], []
    for sym, date in entries:
        idxmap = date_idx.get(sym)
        if idxmap is None:
            continue
        t = idxmap.get(date)
        if t is None:
            continue
        entry = by_symbol[sym]["close"][t]
        if entry is None or np.isnan(entry) or entry <= 0:
            continue
        c = race_control(sym, t, by_symbol)
        if c:
            control_rows.append(c)
        trail_rows.append(race_trail(sym, t, by_symbol))

    print(f"\n--- {label} (n={len(entries)}) ---")
    for rule_name, rows in [("CONTROL", control_rows), ("TRAIL_LOW", trail_rows)]:
        df = pd.DataFrame(rows)
        resolved = df[df["censored"] == False]
        censored = df[df["censored"] == True]
        if len(resolved) == 0:
            print(f"  {rule_name}: no resolved trades")
            continue
        rets = resolved["ret"].astype(float)
        costs = [apply_costs(r) for r in rets]
        nf = pd.Series([c[0] for c in costs]); ncgt = pd.Series([c[1] for c in costs])
        print(f"  {rule_name}: n_resolved={len(resolved)} censored={len(censored)} ({len(censored)/len(df)*100:.1f}%)  "
              f"gross_mean={rets.mean():.3f}%  net_friction_mean={nf.mean():.3f}%  "
              f"net_friction_cgt_mean={ncgt.mean():.3f}%  win_rate={(rets>0).mean()*100:.1f}%  "
              f"median={rets.median():.3f}%")
    return control_rows, trail_rows

# ---------------------------------------------------------------------------
# Step 5 (Part B): EV of suppressed vs surviving, on the decile-9+liquidity-gated pop
# ---------------------------------------------------------------------------
print(f"\n{'#'*92}\n# PART B: forward EV, suppressed vs surviving occurrences "
      f"(decile-9 + liquidity-gated population)\n{'#'*92}")

panel = pd.read_csv("boring_heterogeneity_panel_20d.csv")
bo = panel[(panel["breakout"] == 1) & (panel["lookback"] == 20)].copy()
gated = bo[(bo["liquidity"] > 200_000) & (bo["stock_rs"].notna())].copy()
gated["decile"] = pd.qcut(gated["stock_rs"], 10, labels=False, duplicates="drop")
d9 = gated[gated["decile"] == 9].copy()
print(f"Decile-9 + liquidity-gated raw rows: {len(d9):,}")

sim_lookup = sim.set_index(["symbol", "date"])[["survived_k1", "survived_k2"]]
d9 = d9.merge(sim_lookup, left_on=["symbol", "date"], right_index=True, how="left")
matched = d9["survived_k1"].notna().sum()
print(f"Matched to reset-rule simulation: {matched:,} of {len(d9):,} "
      f"({matched/len(d9)*100:.1f}%; unmatched rows are symbols/dates outside today's "
      f"prices_adjusted coverage used to build the simulation, or edge-of-history rows)")

d9_matched = d9[d9["survived_k1"].notna()].copy()
survivors = d9_matched[d9_matched["survived_k1"] == True]
suppressed = d9_matched[d9_matched["survived_k1"] == False]
print(f"Within decile-9+gated population: {len(survivors):,} survive the K=1 reset rule, "
      f"{len(suppressed):,} are suppressed")

surv_entries = list(zip(survivors["symbol"], survivors["date"]))
supp_entries = list(zip(suppressed["symbol"], suppressed["date"]))
all_entries = list(zip(d9_matched["symbol"], d9_matched["date"]))

summarize_group("ALL decile-9+gated occurrences (baseline, no reset filter)", all_entries, by_symbol)
summarize_group("SURVIVING occurrences (pass the K=1 reset filter)", surv_entries, by_symbol)
summarize_group("SUPPRESSED occurrences (blocked by the K=1 reset filter)", supp_entries, by_symbol)

# ---------------------------------------------------------------------------
# Step 6 (Part C): frequency / capital-concentration effect
# ---------------------------------------------------------------------------
print(f"\n{'#'*92}\n# PART C: signal frequency and same-symbol overlap, decile-9+gated population\n{'#'*92}")

years_span = (pd.to_datetime(d9_matched["date"]).max() - pd.to_datetime(d9_matched["date"]).min()).days / 365.25
n_symbols = d9_matched["symbol"].nunique()
print(f"Date span: {years_span:.1f} years, {n_symbols} distinct symbols")
print(f"Raw decile-9+gated signals/year (current, unsuppressed): {len(d9_matched)/years_span:.1f}")
print(f"Surviving decile-9+gated signals/year (K=1 reset applied): {len(survivors)/years_span:.1f}")
print(f"Reduction: {(1 - len(survivors)/len(d9_matched))*100:.1f}%")

# direct answer: of same-symbol pairs within N=20 trading days of each other (the
# original clustering definition), how many would now produce TWO live surviving
# signals under the reset rule vs. under current (unsuppressed) code?
overlap_current = 0
overlap_reset = 0
total_pairs = 0
for sym, g in d9_matched.groupby("symbol"):
    idxmap = date_idx.get(sym)
    if idxmap is None:
        continue
    g = g.sort_values("date")
    idxs_all = [(idxmap[d], d, surv) for d, surv in zip(g["date"], g["survived_k1"]) if d in idxmap]
    idxs_all.sort()
    for i in range(len(idxs_all) - 1):
        idx_a, d_a, surv_a = idxs_all[i]
        idx_b, d_b, surv_b = idxs_all[i + 1]
        if idx_b - idx_a <= N:
            total_pairs += 1
            overlap_current += 1  # under current code, both are always live signals
            if surv_a and surv_b:
                overlap_reset += 1

print(f"\nAdjacent same-symbol pairs within N={N} trading days of each other "
      f"(the round-3 clustering definition): {total_pairs}")
print(f"  Under CURRENT code: both members of the pair are live signals in {overlap_current} "
      f"of {total_pairs} cases (100% by construction -- no suppression exists today)")
print(f"  Under the K=1 RESET RULE: both members would still both be live signals in "
      f"{overlap_reset} of {total_pairs} cases ({overlap_reset/total_pairs*100 if total_pairs else 0:.1f}%)")

# ---------------------------------------------------------------------------
# Step 7 (Part D already covered by K=2 above); Part E: overlap with round-4/5 run-collapse
# ---------------------------------------------------------------------------
print(f"\n{'#'*92}\n# PART E: does the K=1 reset-rule survivor set match round 4/5's "
      f"run-collapse first-fire set?\n{'#'*92}")

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

run_collapse_set = set(first_fire)
reset_survivor_set = set(zip(survivors["symbol"], survivors["date"]))
both = run_collapse_set & reset_survivor_set
only_run_collapse = run_collapse_set - reset_survivor_set
only_reset = reset_survivor_set - run_collapse_set

print(f"Round 4/5 run-collapse first-fire set (decile-9+gated): {len(run_collapse_set):,}")
print(f"K=1 reset-rule survivor set (decile-9+gated):            {len(reset_survivor_set):,}")
print(f"Agree (in both sets):                                     {len(both):,}")
print(f"Only in run-collapse first-fire (reset rule would suppress this too, or classify differently): "
      f"{len(only_run_collapse):,}")
print(f"Only in reset-rule survivors (run-collapse treated this as a later occurrence in an existing run, "
      f"but the reset rule says the symbol had genuinely reset): {len(only_reset):,}")

print(f"\n{'='*92}\nDone.\n{'='*92}")
