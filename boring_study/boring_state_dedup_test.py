"""
boring_state_dedup_test.py -- measurement-only test of a "block while open"
dedup rule: a symbol is ineligible to fire a new signal while it already has
an unresolved (Pending/Executed-equivalent) position open on that symbol.
No price-structure condition (unlike boring_reset_rule_test.py's band-reset
rule), no cooldown -- eligible again the trading day immediately after the
open position resolves. Does NOT modify boring_signals.py or any production
file. Read-only.

Population: the same 2,130 raw decile-9 + liquidity-gated N=20 occurrences
used throughout (boring_heterogeneity_panel_20d.csv), but walked
CHRONOLOGICALLY per symbol -- order matters here, unlike round 4/5's static
gap-based run-collapse, because "is there an open position" is a genuinely
sequential/stateful question.

Resolution logic: TRAIL_LOW (round 5's prior-day-low trailing stop, no fixed
TP), since that's the exit rule under consideration for production. A
position is considered "open" for trading-day indices [entry_idx, exit_idx]
inclusive; the symbol becomes eligible for a new fire starting exit_idx+1.
Censored (never-resolved) positions block the symbol for the remainder of
its available price history -- reported explicitly, not glossed over.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "../psx_data.db"
FRICTION = 0.20
CGT_RATE = 0.15

# ---------------------------------------------------------------------------
# Step 1: load the decile-9 + liquidity-gated population (identical to prior rounds)
# ---------------------------------------------------------------------------
panel = pd.read_csv("boring_heterogeneity_panel_20d.csv")
bo = panel[(panel["breakout"] == 1) & (panel["lookback"] == 20)].copy()
gated = bo[(bo["liquidity"] > 200_000) & (bo["stock_rs"].notna())].copy()
gated["decile"] = pd.qcut(gated["stock_rs"], 10, labels=False, duplicates="drop")
d9 = gated[gated["decile"] == 9].copy()
print(f"Decile-9 + liquidity-gated raw rows: {len(d9):,}")

con = sqlite3.connect(DB)
symbols = d9["symbol"].unique().tolist()
placeholders = ",".join("?" for _ in symbols)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted WHERE symbol IN ({placeholders}) "
    f"ORDER BY symbol, date",
    con, params=symbols
)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {"dates": g["date"].to_numpy(), "high": g["high"].to_numpy(dtype=float),
                       "low": g["low"].to_numpy(dtype=float), "close": g["close"].to_numpy(dtype=float)}
date_idx = {sym: {d: i for i, d in enumerate(pf["dates"])} for sym, pf in by_symbol.items()}


def race_trail(sym, t, by_symbol):
    pf = by_symbol[sym]
    low, close = pf["low"], pf["close"]
    n = len(close)
    entry = close[t]
    stop = low[t]
    exit_d = None
    for d in range(t + 1, n):
        stop = max(stop, low[d - 1])
        if low[d] <= stop:
            exit_d = d
            break
    if exit_d is not None:
        return {"ret": (stop - entry) / entry * 100, "days": exit_d - t, "censored": False, "exit_idx": exit_d}
    else:
        last = n - 1
        return {"ret": (close[last] - entry) / entry * 100, "days": last - t, "censored": True, "exit_idx": None}


def apply_costs(ret):
    nf = ret - FRICTION
    ncgt = ret * (1 - CGT_RATE) - FRICTION if ret > 0 else ret - FRICTION
    return nf, ncgt


# ---------------------------------------------------------------------------
# Step 2: chronological, stateful simulation of the "block while open" rule
# ---------------------------------------------------------------------------
survivors = []      # dicts: symbol, date, idx, race result, gap_since_last_resolution
suppressed = []      # dicts: symbol, date
overlap_check = []   # per-symbol list of (entry_idx, open_until) intervals, for direct verification

for sym, g in d9.groupby("symbol"):
    idxmap = date_idx.get(sym)
    if idxmap is None:
        continue
    occ_idx = sorted((idxmap[d], d) for d in g["date"] if d in idxmap)
    if not occ_idx:
        continue

    position_open_until = None   # None = no open position; float('inf') = censored/never resolves
    prior_exit_idx = None        # exit index of the most recently RESOLVED position, for gap tracking
    intervals = []

    for (idx, date) in occ_idx:
        if position_open_until is not None and idx <= position_open_until:
            suppressed.append({"symbol": sym, "date": date})
            continue

        gap_since_resolution = (idx - prior_exit_idx) if prior_exit_idx is not None else None
        res = race_trail(sym, idx, by_symbol)
        survivors.append({
            "symbol": sym, "date": date, "idx": idx,
            "ret": res["ret"], "days": res["days"], "censored": res["censored"],
            "gap_since_last_resolution": gap_since_resolution,
            "is_first_fire_for_symbol": prior_exit_idx is None and position_open_until is None,
        })

        if res["censored"]:
            position_open_until = float("inf")
            intervals.append((idx, float("inf")))
        else:
            position_open_until = res["exit_idx"]
            prior_exit_idx = res["exit_idx"]
            intervals.append((idx, res["exit_idx"]))

    overlap_check.append((sym, intervals))

surv_df = pd.DataFrame(survivors)
supp_df = pd.DataFrame(suppressed)
n_total = len(surv_df) + len(supp_df)
print(f"\nTotal occurrences: {n_total:,}")
print(f"Survivors: {len(surv_df):,} ({len(surv_df)/n_total*100:.2f}%)")
print(f"Suppressed: {len(supp_df):,} ({len(supp_df)/n_total*100:.2f}%)")

# ---------------------------------------------------------------------------
# Step 3: direct verification -- do any survivor intervals overlap for the same symbol?
# ---------------------------------------------------------------------------
overlap_violations = 0
for sym, intervals in overlap_check:
    intervals_sorted = sorted(intervals)
    for i in range(len(intervals_sorted) - 1):
        a_start, a_end = intervals_sorted[i]
        b_start, b_end = intervals_sorted[i + 1]
        if b_start <= a_end:
            overlap_violations += 1
print(f"\nDirect verification -- survivor open-interval overlaps for the same symbol: {overlap_violations} "
      f"(should be 0 by construction; a nonzero count would indicate a simulation bug)")

# ---------------------------------------------------------------------------
# Step 4: EV / win rate / median, survivors vs suppressed, TRAIL_LOW logic
# ---------------------------------------------------------------------------
def report_group(label, df):
    resolved = df[df["censored"] == False]
    censored = df[df["censored"] == True]
    print(f"\n--- {label} (n={len(df)}) ---")
    if len(resolved) == 0:
        print("  no resolved trades")
        return
    rets = resolved["ret"].astype(float)
    costs = [apply_costs(r) for r in rets]
    nf = pd.Series([c[0] for c in costs]); ncgt = pd.Series([c[1] for c in costs])
    print(f"  n_resolved={len(resolved)}  censored={len(censored)} ({len(censored)/len(df)*100:.1f}%)")
    print(f"  gross_mean={rets.mean():.3f}%  net_friction_mean={nf.mean():.3f}%  "
          f"net_friction_cgt_mean={ncgt.mean():.3f}%")
    print(f"  win_rate={(rets>0).mean()*100:.1f}%  median={rets.median():.3f}%  "
          f"p25={rets.quantile(.25):.3f}%  p75={rets.quantile(.75):.3f}%")
    print(f"  avg days held={resolved['days'].mean():.1f}  median days held={resolved['days'].median():.1f}")


print(f"\n{'#'*92}\n# EV comparison: survivors vs suppressed, TRAIL_LOW exit logic\n{'#'*92}")
# for suppressed occurrences, we still evaluate their hypothetical TRAIL_LOW outcome
# (had they been allowed to fire) purely to compare quality -- they never actually opened
supp_hypothetical = []
for _, row in supp_df.iterrows():
    sym, date = row["symbol"], row["date"]
    idxmap = date_idx.get(sym)
    idx = idxmap.get(date) if idxmap else None
    if idx is None:
        continue
    res = race_trail(sym, idx, by_symbol)
    supp_hypothetical.append({"symbol": sym, "date": date, "ret": res["ret"], "days": res["days"],
                               "censored": res["censored"]})
supp_hyp_df = pd.DataFrame(supp_hypothetical)

report_group("ALL decile-9+gated occurrences (baseline, no dedup filter)",
             pd.concat([surv_df[["ret", "days", "censored"]], supp_hyp_df[["ret", "days", "censored"]]],
                       ignore_index=True))
report_group("SURVIVING occurrences (pass the state-dedup filter)", surv_df)
report_group("SUPPRESSED occurrences (hypothetical outcome had they fired anyway)", supp_hyp_df)

# ---------------------------------------------------------------------------
# Step 5: signal frequency, before/after
# ---------------------------------------------------------------------------
years_span = (pd.to_datetime(d9["date"]).max() - pd.to_datetime(d9["date"]).min()).days / 365.25
print(f"\n{'#'*92}\n# Frequency\n{'#'*92}")
print(f"Date span: {years_span:.1f} years")
print(f"Raw signals/year (current, unsuppressed): {n_total/years_span:.1f}")
print(f"Surviving signals/year (state-dedup applied): {len(surv_df)/years_span:.1f}")
print(f"Reduction: {(1 - len(surv_df)/n_total)*100:.1f}%")

# ---------------------------------------------------------------------------
# Step 6: does the rule ever allow two of the 1,483 clustered pairs to be simultaneously open?
# ---------------------------------------------------------------------------
print(f"\n{'#'*92}\n# Same-symbol simultaneous-open check (the 1,483-pair test from round 6)\n{'#'*92}")

survivor_set = set(zip(surv_df["symbol"], surv_df["date"]))
survivor_intervals = {}
for sym, intervals in overlap_check:
    survivor_intervals[sym] = sorted(intervals)

both_survive = 0
both_simultaneously_open = 0
total_pairs = 0
for sym, g in d9.groupby("symbol"):
    idxmap = date_idx.get(sym)
    if idxmap is None:
        continue
    occ_idx = sorted((idxmap[d], d) for d in g["date"] if d in idxmap)
    for i in range(len(occ_idx) - 1):
        idx_a, d_a = occ_idx[i]
        idx_b, d_b = occ_idx[i + 1]
        if idx_b - idx_a <= 20:
            total_pairs += 1
            a_surv = (sym, d_a) in survivor_set
            b_surv = (sym, d_b) in survivor_set
            if a_surv and b_surv:
                both_survive += 1
                # check whether b's fire falls inside a's open interval (would indicate a bug)
                a_interval = next((iv for iv in survivor_intervals[sym] if iv[0] == idx_a), None)
                if a_interval and idx_b <= a_interval[1]:
                    both_simultaneously_open += 1

print(f"Adjacent same-symbol pairs within N=20 trading days: {total_pairs}")
print(f"Both members survive the dedup filter (not necessarily simultaneously open): "
      f"{both_survive} ({both_survive/total_pairs*100:.1f}%)")
print(f"Both members SIMULTANEOUSLY OPEN at the same time: {both_simultaneously_open} "
      f"(should be 0 by construction)")

# ---------------------------------------------------------------------------
# Step 7: resolve-then-immediately-refire pattern
# ---------------------------------------------------------------------------
print(f"\n{'#'*92}\n# Resolve-then-immediately-refire pattern\n{'#'*92}")

has_gap = surv_df["gap_since_last_resolution"].notna()
gaps = surv_df.loc[has_gap, "gap_since_last_resolution"]
print(f"Survivors that are NOT a symbol's first-ever fire (have a defined gap-since-last-resolution): "
      f"{has_gap.sum()} of {len(surv_df)}")
if has_gap.sum():
    print(f"Gap distribution (trading days between prior resolution and this re-fire):")
    print(f"  median={gaps.median():.1f}  p10={gaps.quantile(.10):.1f}  p25={gaps.quantile(.25):.1f}  "
          f"p75={gaps.quantile(.75):.1f}")
    for threshold in [1, 3, 5, 10]:
        frac = (gaps <= threshold).mean() * 100
        cnt = (gaps <= threshold).sum()
        print(f"  fraction with gap <= {threshold} trading day(s): {cnt} ({frac:.1f}%)")

    quick_refire = surv_df[has_gap & (surv_df["gap_since_last_resolution"] <= 5)]
    ordinary = surv_df[~has_gap | (surv_df["gap_since_last_resolution"] > 5)]
    report_group("QUICK REFIRES (gap <= 5 trading days since prior resolution)", quick_refire)
    report_group("ORDINARY survivors (first-ever fire, or gap > 5 trading days)", ordinary)

print(f"\n{'='*92}\nDone.\n{'='*92}")
