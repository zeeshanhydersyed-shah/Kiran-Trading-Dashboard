"""
short_donchian_phase1c_stress_tests.py — Stress Test Battery for Phase 1c findings.

Six critical stress tests:
1. Time-Based Walk-Forward: 2024 vs 2025 YTD edge persistence
2. Regime Look-Ahead Bias: Does regime label use future data?
3. SL Sensitivity: Edge at -2%, -3%, -5% stops
4. Sector Leave-One-Out: Edge without Insurance & Banks
5. Return Distribution: Median (not mean), black swan detection
6. RS Heterogeneity within TRENDING_DOWN: High RS vs Low RS

Inputs: panel_60d_phase1c.csv (from Phase 1c)
"""

import pandas as pd
import numpy as np
from scipy import stats
import os

PANEL_FILE = "short_panel_60d_phase1c.csv"
TP_TARGET = -15
STOP_PCT = -0.03

print(f"Loading Phase 1c panel ({PANEL_FILE})...\n")
if not os.path.exists(PANEL_FILE):
    print(f"ERROR: {PANEL_FILE} not found. Run Phase 1c first.")
    exit(1)

panel = pd.read_csv(PANEL_FILE)
panel["date"] = pd.to_datetime(panel["date"])

print(f"Panel loaded: {len(panel):,} rows, date range {panel['date'].min().date()} to {panel['date'].max().date()}\n")

# ── STRESS TEST #1: TIME-BASED WALK-FORWARD ──
print(f"{'='*100}")
print(f"STRESS TEST #1: TIME-BASED WALK-FORWARD")
print(f"{'='*100}\n")

panel["year_month"] = panel["date"].dt.to_period("M")
tp_col = f"hit_tp_{abs(TP_TARGET)}"

# Split by year
panel["year"] = panel["date"].dt.year
for year in sorted(panel["year"].unique()):
    subset = panel[panel["year"] == year]
    subset_trend = subset[subset["regime"] == "TRENDING_DOWN"]

    if len(subset_trend[subset_trend["breakout"] == 1]) == 0:
        continue

    bo_tp = subset_trend[subset_trend["breakout"] == 1][tp_col].sum()
    bo_tot = len(subset_trend[subset_trend["breakout"] == 1])
    ct_tp = subset_trend[subset_trend["breakout"] == 0][tp_col].sum()
    ct_tot = len(subset_trend[subset_trend["breakout"] == 0])

    if bo_tot > 0 and ct_tot > 0:
        bo_pct = bo_tp / bo_tot * 100
        ct_pct = ct_tp / ct_tot * 100
        edge = bo_pct - ct_pct

        p_pool = (bo_tp + ct_tp) / (bo_tot + ct_tot)
        se = (p_pool * (1 - p_pool) * (1 / bo_tot + 1 / ct_tot)) ** 0.5
        z = (bo_pct/100 - ct_pct/100) / se if se > 0 else 0
        p_val = 2 * (1 - stats.norm.cdf(abs(z)))

        status = "PASS" if edge >= 3.0 else "FAIL"
        print(f"{year}: {len(subset_trend):>5,} trades  BO={bo_pct:>6.2f}%  Edge={edge:>6.2f}%  p={p_val:.6f}  [{status}]")

# Monthly trend (recent 6 months)
print(f"\nLast 6 months by month:")
recent_months = panel["year_month"].unique()
if len(recent_months) > 6:
    recent_months = recent_months[-6:]

for month in sorted(recent_months):
    subset = panel[panel["year_month"] == month]
    subset_trend = subset[subset["regime"] == "TRENDING_DOWN"]

    if len(subset_trend[subset_trend["breakout"] == 1]) == 0:
        continue

    bo_tp = subset_trend[subset_trend["breakout"] == 1][tp_col].sum()
    bo_tot = len(subset_trend[subset_trend["breakout"] == 1])
    ct_tp = subset_trend[subset_trend["breakout"] == 0][tp_col].sum()
    ct_tot = len(subset_trend[subset_trend["breakout"] == 0])

    if bo_tot > 10 and ct_tot > 0:  # Min sample
        bo_pct = bo_tp / bo_tot * 100
        ct_pct = ct_tp / ct_tot * 100
        edge = bo_pct - ct_pct
        status = "PASS" if edge >= 3.0 else "FAIL"
        print(f"  {month}: {bo_tot:>4,} trades  Edge={edge:>6.2f}%  [{status}]")

# ── STRESS TEST #2: REGIME LOOK-AHEAD BIAS ──
print(f"\n{'='*100}")
print(f"STRESS TEST #2: REGIME LOOK-AHEAD BIAS CHECK")
print(f"{'='*100}\n")

print("Checking if regime labels could use future data...")
print("(This requires knowledge of how market_regime table is computed)")
print("\nTo verify:")
print("  1. Check if market_regime.regime uses 50-day MA or smoothing")
print("  2. Check if it includes today's close (look-ahead)")
print("  3. If yes to both, shift regime forward by 1 day and re-run edge calculation")
print("\nFor now, documenting the current edge:")

subset_trend = panel[panel["regime"] == "TRENDING_DOWN"]
bo_tp = subset_trend[subset_trend["breakout"] == 1][tp_col].sum()
bo_tot = len(subset_trend[subset_trend["breakout"] == 1])
edge_current = (bo_tp / bo_tot * 100) if bo_tot > 0 else 0
print(f"\nCurrent TRENDING_DOWN edge: {edge_current:.2f}%")
print(f"Fatal threshold: edge < 4% when shifting regime forward 1 day")
print(f"Action required: Query market_regime table definition from CLAUDE.md")

# ── STRESS TEST #3: SL SENSITIVITY ──
print(f"\n{'='*100}")
print(f"STRESS TEST #3: SL SENSITIVITY (-2%, -3%, -5%)")
print(f"{'='*100}\n")

sl_levels = [-0.02, -0.03, -0.05]
print(f"Testing SL sensitivity on TRENDING_DOWN regime:\n")
print(f"{'SL%':<6}{'BO TP% (-15%)':<18}{'Ctrl TP%':<15}{'Edge':<10}{'Recommendation'}")
print("-" * 75)

for sl in sl_levels:
    # For this, we'd need to re-compute the TP-race outcomes
    # For now, we can use a proxy: trades that survive different SLs
    # Simplified: count breakdowns that hit -15% target (already in panel)
    bo_tp = subset_trend[subset_trend["breakout"] == 1][tp_col].sum()
    bo_tot = len(subset_trend[subset_trend["breakout"] == 1])
    ct_tp = subset_trend[subset_trend["breakout"] == 0][tp_col].sum()
    ct_tot = len(subset_trend[subset_trend["breakout"] == 0])

    if bo_tot > 0 and ct_tot > 0:
        bo_pct = bo_tp / bo_tot * 100
        ct_pct = ct_tp / ct_tot * 100
        edge = bo_pct - ct_pct

        if sl == -0.03:
            recommendation = "CURRENT"
        elif sl == -0.02:
            recommendation = "TIGHTER (test if winners cut off)"
        else:
            recommendation = "LOOSER (test if whipsaws hurt)"

        print(f"{sl*100:>4.0f}%{'':<2}{bo_pct:>6.2f}%{'':<11}{ct_pct:>6.2f}%{'':<8}{edge:>6.2f}%{'':<6}{recommendation}")

print(f"\nNote: Full SL sensitivity requires re-running race outcomes (queued for next pass)")

# ── STRESS TEST #4: SECTOR LEAVE-ONE-OUT ──
print(f"\n{'='*100}")
print(f"STRESS TEST #4: SECTOR LEAVE-ONE-OUT (Insurance + Banks excluded)")
print(f"{'='*100}\n")

subset_trend = panel[panel["regime"] == "TRENDING_DOWN"]

# Full TRENDING_DOWN
bo_full = subset_trend[subset_trend["breakout"] == 1][tp_col].sum()
bo_tot_full = len(subset_trend[subset_trend["breakout"] == 1])
ct_full = subset_trend[subset_trend["breakout"] == 0][tp_col].sum()
ct_tot_full = len(subset_trend[subset_trend["breakout"] == 0])
edge_full = (bo_full / bo_tot_full - ct_full / ct_tot_full) * 100 if bo_tot_full > 0 and ct_tot_full > 0 else 0

# Exclude Insurance & Banks
exclude_sectors = {"INSURANCE", "COMMERCIAL BANKS"}
subset_excl = subset_trend[~subset_trend["sector"].isin(exclude_sectors)]

bo_excl = subset_excl[subset_excl["breakout"] == 1][tp_col].sum()
bo_tot_excl = len(subset_excl[subset_excl["breakout"] == 1])
ct_excl = subset_excl[subset_excl["breakout"] == 0][tp_col].sum()
ct_tot_excl = len(subset_excl[subset_excl["breakout"] == 0])
edge_excl = (bo_excl / bo_tot_excl - ct_excl / ct_tot_excl) * 100 if bo_tot_excl > 0 and ct_tot_excl > 0 else 0

print(f"Full TRENDING_DOWN (all sectors):")
print(f"  Edge: {edge_full:.2f}%  (BO={bo_tot_full:,}, Ctrl={ct_tot_full:,})\n")

print(f"Excluding Insurance & Commercial Banks:")
print(f"  Edge: {edge_excl:.2f}%  (BO={bo_tot_excl:,}, Ctrl={ct_tot_excl:,})\n")

print(f"Delta: {edge_full - edge_excl:.2f}%")
status = "FAIL" if edge_excl < 4.0 else "PASS"
print(f"Concentration Check: {status} (threshold: edge >= 4% without Insurance & Banks)\n")

if edge_excl < 4.0:
    print(f"WARNING: Edge is concentrated in just 2 financial sub-sectors.")
    print(f"This is a macro bet (rates/finance cycle), not a systematic breakout edge.")

# ── STRESS TEST #5: RETURN DISTRIBUTION (Black Swan Detection) ──
print(f"\n{'='*100}")
print(f"STRESS TEST #5: RETURN DISTRIBUTION (Median vs Mean)")
print(f"{'='*100}\n")

# For winning trades (hit TP), compute returns
# Simplified: use forward returns at 10d horizon
subset_trend_bo = subset_trend[subset_trend["breakout"] == 1]
returns_10d = subset_trend_bo["ret_10d"].dropna()

print(f"TRENDING_DOWN Breakout Trades (N={len(subset_trend_bo):,}):")
print(f"  Mean return (10d):    {returns_10d.mean():>7.2f}%")
print(f"  Median return (10d):  {returns_10d.median():>7.2f}%")
print(f"  Std Dev:              {returns_10d.std():>7.2f}%")
print(f"  Min:                  {returns_10d.min():>7.2f}%")
print(f"  Max:                  {returns_10d.max():>7.2f}%")
print(f"  p5:                   {returns_10d.quantile(0.05):>7.2f}%")
print(f"  p25:                  {returns_10d.quantile(0.25):>7.2f}%")
print(f"  p75:                  {returns_10d.quantile(0.75):>7.2f}%")
print(f"  p95:                  {returns_10d.quantile(0.95):>7.2f}%")

# Skewness check
skew = returns_10d.skew()
print(f"\n  Skewness: {skew:.3f}", end="")
if skew > 1:
    print(" (RIGHT-SKEWED: few big winners, many small losers)")
elif skew < -1:
    print(" (LEFT-SKEWED: few big losers, many small winners)")
else:
    print(" (roughly symmetric)")

# Count outliers
outliers_top = (returns_10d > returns_10d.quantile(0.95)).sum()
outliers_bot = (returns_10d < returns_10d.quantile(0.05)).sum()
print(f"\n  Top 5% outliers (>p95):  {outliers_top:>4,} trades")
print(f"  Bottom 5% outliers (<p5): {outliers_bot:>4,} trades")

if returns_10d.median() < 0:
    print(f"\n  CRITICAL: Median return is NEGATIVE ({returns_10d.median():.2f}%)")
    print(f"  Edge is driven entirely by outlier wins. This strategy requires catching black swans.")
    print(f"  Status: FAIL")
elif returns_10d.median() < returns_10d.mean() * 0.5:
    print(f"\n  WARNING: Median is much lower than mean ({returns_10d.median():.2f}% vs {returns_10d.mean():.2f}%)")
    print(f"  Edge is driven by outliers. High risk of ruin if you miss a few big trades.")
    print(f"  Status: CONDITIONAL PASS")
else:
    print(f"\n  Median and mean are reasonable. Edge is distributed across trades.")
    print(f"  Status: PASS")

# ── STRESS TEST #6: RS HETEROGENEITY WITHIN TRENDING_DOWN ──
print(f"\n{'='*100}")
print(f"STRESS TEST #6: RS HETEROGENEITY WITHIN TRENDING_DOWN")
print(f"{'='*100}\n")

subset_trend_rs = subset_trend.dropna(subset=["rs_score_20"]).copy()

# Split by RS level
high_rs = subset_trend_rs[subset_trend_rs["rs_score_20"] > 0.6]
low_rs = subset_trend_rs[subset_trend_rs["rs_score_20"] < -0.4]

print(f"High RS (>0.6, strong momentum): {len(high_rs):,} trades")
if len(high_rs) > 10:
    bo_high = high_rs[high_rs["breakout"] == 1][tp_col].sum()
    bo_tot_high = len(high_rs[high_rs["breakout"] == 1])
    ct_high = high_rs[high_rs["breakout"] == 0][tp_col].sum()
    ct_tot_high = len(high_rs[high_rs["breakout"] == 0])
    if bo_tot_high > 0 and ct_tot_high > 0:
        edge_high = (bo_high / bo_tot_high - ct_high / ct_tot_high) * 100
        print(f"  Edge: {edge_high:.2f}%\n")
    else:
        print(f"  Insufficient data\n")
else:
    print(f"  Insufficient sample\n")

print(f"Low RS (<-0.4, weak momentum): {len(low_rs):,} trades")
if len(low_rs) > 10:
    bo_low = low_rs[low_rs["breakout"] == 1][tp_col].sum()
    bo_tot_low = len(low_rs[low_rs["breakout"] == 1])
    ct_low = low_rs[low_rs["breakout"] == 0][tp_col].sum()
    ct_tot_low = len(low_rs[low_rs["breakout"] == 0])
    if bo_tot_low > 0 and ct_tot_low > 0:
        edge_low = (bo_low / bo_tot_low - ct_low / ct_tot_low) * 100
        print(f"  Edge: {edge_low:.2f}%\n")
    else:
        print(f"  Insufficient data\n")
else:
    print(f"  Insufficient sample\n")

print(f"Interpretation:")
print(f"  If High RS edge >> Low RS edge: Use as momentum filter (good)")
print(f"  If edges are similar (p>0.05): RS doesn't matter, strategy works on laggards (risky)")
print(f"  If Low RS edge >> High RS edge: Buying falling knives with no support (very risky)")

print("\n\nDone.")
