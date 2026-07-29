"""
temporal_split_validation.py
--------------------------------
Temporal holdout re-validation (NOT true prospective OOS -- every pipeline
parameter was tuned on the full 2005-2026 dataset; this only checks
whether the findings' PATTERNS replicate when the already-fixed pipeline
is applied to two non-overlapping date halves). All parameters are FIXED
at their already-decided values; nothing is re-tuned per era.

Split: by candidate COUNT (not calendar midpoint), via
temporal_split_dates.py -- 272/272 exactly, split date 2017-02-07.
Era A: 2005-07-11 to 2017-01-19 (272 candidates, ~11.5 calendar years).
Era B: 2017-02-07 to 2026-07-10 (272 candidates, ~9.4 calendar years).
Confirms candidate density is NOT uniform across the 21-year span (more
candidates/year in the later period) -- an even split by date would NOT
have been an even split by count.

SCOPE NOTE ON "FUNNEL COUNTS": pre-classification funnel stages (windows
examined, converging candidates before the forced-line/shape filters)
were only ever printed to console during the original full-history run
and were not saved per-candidate with dates anywhere -- they cannot be
split by era without a fresh full re-run of pivot/boundary detection on
date-filtered price data per symbol (which would also shift window-index
offsets, produce a DIFFERENT candidate set than the already-classified
544, and break every downstream join to Type/stop-loss/EV results keyed
on the original bar indices). Reported instead: classified-triangle
count per era (the funnel's actual final output) and the 518-candidate
walk-forward-eligible count per era, sufficient to judge sample adequacy
for every downstream comparison this task actually needs.
"""

import pandas as pd

dates = pd.read_csv("triangle_breakout_dates.csv")
dates["breakout_date"] = pd.to_datetime(dates["breakout_date"])
SPLIT_DATE = pd.Timestamp("2017-02-07")
dates["era"] = dates["breakout_date"].apply(lambda d: "A" if d < SPLIT_DATE else "B")
era_key = dates[["symbol", "start", "end", "era"]]

print(f"Era A: {(era_key['era']=='A').sum()} candidates, "
      f"{dates[dates['era']=='A']['breakout_date'].min().date()} to {dates[dates['era']=='A']['breakout_date'].max().date()}")
print(f"Era B: {(era_key['era']=='B').sum()} candidates, "
      f"{dates[dates['era']=='B']['breakout_date'].min().date()} to {dates[dates['era']=='B']['breakout_date'].max().date()}")

# ═══════════════════════════════════════════════════════════════════════
# 1. Classified-triangle count + 5-category breakout distribution
# ═══════════════════════════════════════════════════════════════════════
tri = pd.read_csv("triangle_full_universe_results.csv").merge(era_key, on=["symbol", "start", "end"], how="left")
print(f"\n{'='*70}\n1. CLASSIFIED TRIANGLES + 5-CATEGORY OUTCOME\n{'='*70}")
for era in ["A", "B"]:
    sub = tri[tri["era"] == era]
    print(f"\n--- Era {era}: n={len(sub)} classified triangles ---")
    print(sub["outcome"].value_counts().reindex(["up", "down", "whipsaw", "sequential", "none"], fill_value=0).to_string())
print(f"\n--- FULL SAMPLE (n=544) ---")
print(tri["outcome"].value_counts().reindex(["up", "down", "whipsaw", "sequential", "none"], fill_value=0).to_string())

# ═══════════════════════════════════════════════════════════════════════
# 2. Type 1-4 distribution (trigger variant)
# ═══════════════════════════════════════════════════════════════════════
variants = pd.read_csv("breakout_classification_variant_results.csv")
variants = variants[variants["variant"] == "trigger"].merge(era_key, on=["symbol", "start", "end"], how="left")
print(f"\n{'='*70}\n2. TYPE 1-4 DISTRIBUTION (trigger variant)\n{'='*70}")
for era in ["A", "B"]:
    sub = variants[variants["era"] == era]
    print(f"\n--- Era {era}: n={len(sub)} ---")
    print(sub["type"].value_counts(dropna=False).sort_index().to_string())
print(f"\n--- FULL SAMPLE ---")
print(variants["type"].value_counts(dropna=False).sort_index().to_string())

# ═══════════════════════════════════════════════════════════════════════
# 3. Type-conditional LFD-vs-opposite win rate
# ═══════════════════════════════════════════════════════════════════════
res = pd.read_csv("stop_loss_three_way_results.csv").merge(era_key, on=["symbol", "start", "end"], how="left")
primary = res[res["type_trigger"] != 4.0].copy()
primary["lfd_wins"] = primary["realized_R_lfd"] > primary["realized_R_opposite"]
primary["opp_wins"] = primary["realized_R_opposite"] > primary["realized_R_lfd"]
primary["tie"] = primary["realized_R_lfd"] == primary["realized_R_opposite"]

print(f"\n{'='*70}\n3. TYPE-CONDITIONAL LFD-vs-OPPOSITE WIN RATE\n{'='*70}")
print(f"\nprimary set (Type-4 excluded): full n={len(primary)}, "
      f"Era A n={(primary['era']=='A').sum()}, Era B n={(primary['era']=='B').sum()}")
for era in ["A", "B", None]:
    label = f"Era {era}" if era else "FULL SAMPLE"
    sub = primary if era is None else primary[primary["era"] == era]
    print(f"\n--- {label} ---")
    for t, grp in sub.groupby("type_trigger"):
        n = len(grp)
        if n == 0:
            continue
        print(f"  Type {int(t)}: n={n}  LFD wins={grp['lfd_wins'].sum()} ({grp['lfd_wins'].mean()*100:.1f}%)  "
              f"Opp wins={grp['opp_wins'].sum()} ({grp['opp_wins'].mean()*100:.1f}%)  "
              f"Tie={grp['tie'].sum()} ({grp['tie'].mean()*100:.1f}%)")

# ═══════════════════════════════════════════════════════════════════════
# 4. Kind asymmetry: descending vs ascending measured-move achievement
# ═══════════════════════════════════════════════════════════════════════
mm = pd.read_csv("triangle_measured_move_results.csv").merge(era_key, on=["symbol", "start", "end"], how="left")
mm90 = mm[(mm["horizon"] == 90) & (~mm["excluded_insufficient_data"])]

print(f"\n{'='*70}\n4. KIND ASYMMETRY: descending vs ascending, pct_of_measured_move @90d\n{'='*70}")
for era in ["A", "B", None]:
    label = f"Era {era}" if era else "FULL SAMPLE"
    sub = mm90 if era is None else mm90[mm90["era"] == era]
    print(f"\n--- {label} ---")
    for kind in ["ascending", "descending", "symmetrical"]:
        s = sub[sub["kind"] == kind]["pct_of_measured_move"].dropna()
        if len(s) == 0:
            print(f"  {kind}: n=0")
            continue
        print(f"  {kind}: n={len(s)}  mean={s.mean():.1f}%  median={s.median():.1f}%")

# ═══════════════════════════════════════════════════════════════════════
# 5. Full-population EV, gross and net-of-costs, per era
# ═══════════════════════════════════════════════════════════════════════
ev = pd.read_csv("triangle_ev_realistic_r.csv").merge(era_key, on=["symbol", "start", "end"], how="left")
FLOOR = -3.0
RISK_FRAC = 0.01
FRICTION_PCT = 0.20
CGT_RATE = 0.15

ev["R_final"] = ev["realized_R_realistic"].clip(lower=FLOOR)
ev["risk_pct_of_price"] = ev["r_lfd_denom"] / ev["entry_price"] * 100
ev["friction_in_R"] = FRICTION_PCT / ev["risk_pct_of_price"]
ev["R_net_friction"] = ev["R_final"] - ev["friction_in_R"]
ev["R_net_friction_cgt"] = ev.apply(
    lambda r: (r["R_final"] * (1 - CGT_RATE) if r["R_final"] > 0 else r["R_final"]) - r["friction_in_R"], axis=1)

print(f"\n{'='*70}\n5. FULL-POPULATION EV (gross / net-of-costs), n=518 basis\n{'='*70}")
for era in ["A", "B", None]:
    label = f"Era {era}" if era else "FULL SAMPLE"
    sub = ev if era is None else ev[ev["era"] == era]
    n = len(sub)
    if n == 0:
        print(f"\n--- {label}: n=0 ---")
        continue
    gross = sub["R_final"].mean()
    net_f = sub["R_net_friction"].mean()
    net_fc = sub["R_net_friction_cgt"].mean()
    win_rate = (sub["R_final"] > 0).mean() * 100
    print(f"\n--- {label} (n={n}) ---")
    print(f"  gross mean R:               {gross:.4f}  -> {gross*RISK_FRAC*100:+.3f}% of capital/trade")
    print(f"  net of friction:            {net_f:.4f}  -> {net_f*RISK_FRAC*100:+.3f}% of capital/trade")
    print(f"  net of friction+CGT(wins):  {net_fc:.4f}  -> {net_fc*RISK_FRAC*100:+.3f}% of capital/trade")
    print(f"  median R: {sub['R_final'].median():.4f}")
    print(f"  win rate: {win_rate:.1f}%")

# ═══════════════════════════════════════════════════════════════════════
# 6. Outlier concentration check -- CYAN, DCL, MTL, NCL, QUICE
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\n6. BIG-WINNER OUTLIER ERA CONCENTRATION\n{'='*70}")
outlier_symbols = ["CYAN", "DCL", "MTL", "NCL", "QUICE"]
outlier_rows = ev[ev["symbol"].isin(outlier_symbols)]
print(outlier_rows[["symbol", "start", "end", "era", "realized_R_realistic", "R_final"]].to_string())

# top-10 R contributors, full sample, with era labels
print(f"\n--- top 10 R_final contributors, full sample, with era ---")
print(ev.sort_values("R_final", ascending=False).head(10)[
    ["symbol", "start", "end", "era", "R_final"]
].to_string())

for era in ["A", "B"]:
    sub = ev[ev["era"] == era].sort_values("R_final", ascending=False)
    top5_sum = sub.head(5)["R_final"].sum()
    total_sum = sub["R_final"].sum()
    print(f"\nEra {era}: top 5 R contributors sum to {top5_sum:.2f}R of total {total_sum:.2f}R "
          f"({top5_sum/total_sum*100:.1f}% of the era's total summed R)")
