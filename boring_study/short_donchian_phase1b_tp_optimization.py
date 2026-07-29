"""
short_donchian_phase1b_tp_optimization.py — Phase 1b: Optimal TP discovery via gain distribution.

For N=60 breakdowns (and matched controls, seed=42):
1. Use FULL sample (no RS filtering) to validate Phase 1a edge
2. Among winning trades (don't hit -3% SL), analyze gain distribution
3. Determine optimal TP based on MFE (max favorable excursion)
4. Then test RS heterogeneity on the full data

Outcome measure:
  - TP-race at various targets (-5%, -8%, -10%, -12%, -15%, -20%, -25%, -30%)
  - MFE distribution for winning positions
  - Statistical tests (Mann-Whitney U, Cliffs delta)
  - RS heterogeneity patterns
"""

import sqlite3
import numpy as np
import pandas as pd
import os
from scipy import stats
import statsmodels.api as sm

DB = os.path.join(os.path.dirname(__file__), "..", "psx_data.db")
LOOKBACK_PRIMARY = 60
STOP_PCT = -0.03
MAX_HORIZON = 90
SEED = 42
TARGETS = [-5, -8, -10, -12, -15, -20, -25, -30]
HORIZONS = [5, 10, 20, 30, 60, 90]

# DFC-eligible symbols
DFC_SYMBOLS = {
    "AGHA", "AGL",     "AGP",     "AICL",   "AIRLINK", "AKBL",   "ASL",
    "ATRL", "AVN",     "BAFL",    "BAHL",   "BIPL",    "BML",    "BOP",
    "CHCC", "CNERGY",  "CPHL",    "CSAP",   "DCL",     "DCR",    "DFML",
    "DGKC", "EFERT",   "ENGROH",  "EPCL",   "FABL",    "FATIMA", "FCCL",
    "FCEPL","FCL",     "FFC",     "FFL",    "FLYNG",   "GAL",    "GATM",
    "GCIL", "GGL",     "GHGL",    "GHNI",   "GLAXO",   "HBL",    "HUBC",
    "HUMNL","ILP",     "IMAGE",   "INIL",   "ISL",     "JSGBETF","JSMFETF",
    "KAPCO","KEL",     "KOHC",    "KOSM",   "LOTCHEM", "LUCK",   "MARI",
    "MCB",  "MEBL",    "MLCF",    "MTL",    "MUGHAL",  "MZNPETF","NATF",
    "NBP",  "NBPGETF", "NCPL",    "NETSOL", "NITGETF", "NML",    "NPL",
    "NRL",  "OCTOPUS", "OGDC",    "PACE",   "PAEL",    "PIAHCLA","PIBTL",
    "PIOC", "POL",     "POWER",   "PPL",    "PREMA",   "PRL",    "PSO",
    "PTC",  "SAZEW",   "SEARL",   "SNBL",   "SNGP",    "SSGC",   "SYM",
    "SYS",  "TELE",    "TGL",     "THCCL",  "TOMCL",   "TPLP",   "TREET",
    "TRG",  "UBL",     "UNITY",   "UPLPETF","WAVES",   "WAVESAPP","WTL",
    "YOUW",
}

print(f"Phase 1b: TP Optimization (N={LOOKBACK_PRIMARY}, SL={STOP_PCT*100:.0f}%)\n")

# ── STEP 1: Load price data ──
con = sqlite3.connect(DB)
placeholders = ",".join("?" for _ in DFC_SYMBOLS)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=list(DFC_SYMBOLS)
)

# Load stock_signals for RS (for heterogeneity analysis later)
stock_signals = pd.read_sql_query(
    f"SELECT symbol, date, rs_score_20, avg_vol_10d FROM stock_signals "
    f"WHERE symbol IN ({placeholders})",
    con, params=list(DFC_SYMBOLS)
)
con.close()

print(f"Price data: {len(prices):,} rows")
print(f"Stock signals: {len(stock_signals):,} rows\n")

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }

# Build RS lookup
rs_lookup = {}
for sym, g in stock_signals.groupby("symbol"):
    rs_lookup[sym] = dict(zip(g["date"], g["rs_score_20"]))

# ── STEP 2: Detect breakdowns (N=60) ──
print(f"Detecting N={LOOKBACK_PRIMARY} breakdowns...")
breakdowns = []
for sym, pf in by_symbol.items():
    close = pf["close"]
    low = pf["low"]
    dates = pf["dates"]
    n = len(close)

    for i in range(LOOKBACK_PRIMARY, n):
        prior_low_min = np.nanmin(low[i - LOOKBACK_PRIMARY:i])
        if prior_low_min > 0 and close[i] < prior_low_min * 0.99:
            breakdowns.append({
                "symbol": sym,
                "date": dates[i],
                "entry_close": close[i],
                "idx": i
            })

breakdowns_df = pd.DataFrame(breakdowns)
print(f"Breakdowns: {len(breakdowns_df):,}\n")

# ── STEP 3: Generate matched controls ──
print("Generating matched controls (seed=42)...")
breakdown_days = set(zip(breakdowns_df["symbol"], breakdowns_df["date"]))
rng = np.random.default_rng(SEED)
eligible_pool = {}
for sym, pf in by_symbol.items():
    dates = pf["dates"]
    n = len(dates)
    idxs = np.arange(20, n)
    non_breakdown_idxs = [i for i in idxs if (sym, dates[i]) not in breakdown_days]
    eligible_pool[sym] = np.array(non_breakdown_idxs)

control_rows = []
for _, row in breakdowns_df.iterrows():
    sym = row["symbol"]
    pool = eligible_pool.get(sym)
    if pool is None or len(pool) == 0:
        continue
    t = int(rng.choice(pool))
    pf = by_symbol[sym]
    dates, close = pf["dates"], pf["close"]
    entry = close[t]
    if entry is None or np.isnan(entry) or entry <= 0:
        continue

    control_rows.append({
        "symbol": sym,
        "date": dates[t],
        "entry_close": entry,
        "idx": t
    })

controls_df = pd.DataFrame(control_rows)
print(f"Controls: {len(controls_df):,}\n")

# ── STEP 4: Compute metrics for all trades ──
print("Computing forward returns, MFE, and TP-race outcomes...")

def compute_all_metrics(df_breakdowns, df_controls):
    """Compute all metrics WITHOUT RS filtering."""

    def process_trades(df, breakout_flag):
        rows = []
        for _, row in df.iterrows():
            sym = row["symbol"]
            date = row["date"]
            entry = row["entry_close"]
            pf = by_symbol.get(sym)
            if pf is None:
                continue

            dates = pf["dates"]
            close = pf["close"]
            high = pf["high"]
            low = pf["low"]
            idx = np.searchsorted(dates, date)
            if idx >= len(dates) or dates[idx] != date:
                continue

            n = len(dates)
            end_j = min(idx + MAX_HORIZON, n - 1)
            if end_j <= idx:
                continue

            out_row = {
                "symbol": sym,
                "date": date,
                "entry_close": entry,
                "breakout": breakout_flag,
                "rs_score_20": rs_lookup.get(sym, {}).get(date, np.nan)
            }

            # Forward returns at horizons
            for h in HORIZONS:
                j = idx + h
                if j < n and not np.isnan(close[j]):
                    out_row[f"ret_{h}d"] = (close[j] - entry) / entry * 100
                else:
                    out_row[f"ret_{h}d"] = None

            # MFE (max favorable excursion) and MAE
            fwd_high = high[idx + 1:end_j + 1]
            fwd_low = low[idx + 1:end_j + 1]
            valid_h = fwd_high[~np.isnan(fwd_high)]
            valid_l = fwd_low[~np.isnan(fwd_low)]
            out_row["mfe_pct"] = (valid_h.max() - entry) / entry * 100 if len(valid_h) else None
            out_row["mae_pct"] = (valid_l.min() - entry) / entry * 100 if len(valid_l) else None

            # Check if SL is hit
            stop_level = entry * (1 + STOP_PCT)
            stop_hits = np.where(fwd_high >= stop_level)[0]
            out_row["hit_sl"] = 1 if len(stop_hits) else 0

            # TP-race outcomes for all targets
            for target in TARGETS:
                target_pct = target / 100
                target_level = entry * (1 + target_pct)
                target_hits = np.where(fwd_low <= target_level)[0]
                target_day = target_hits[0] if len(target_hits) else None
                stop_day = stop_hits[0] if len(stop_hits) else None

                if target_day is not None and (stop_day is None or target_day < stop_day):
                    out_row[f"hit_tp_{abs(target)}"] = 1
                else:
                    out_row[f"hit_tp_{abs(target)}"] = 0

            rows.append(out_row)

        return pd.DataFrame(rows)

    bo_panel = process_trades(df_breakdowns, 1)
    ctrl_panel = process_trades(df_controls, 0)
    return pd.concat([bo_panel, ctrl_panel], ignore_index=True)

panel_full = compute_all_metrics(breakdowns_df, controls_df)
print(f"Full panel: {len(panel_full):,} rows\n")

# Save full panel
panel_full.to_csv("short_panel_60d_full_phase1b.csv", index=False)
print("Panel saved: short_panel_60d_full_phase1b.csv\n")

# ── STEP 5: Validate Phase 1a edge ──
print(f"{'='*100}")
print(f"EDGE VALIDATION (Full Sample, N={LOOKBACK_PRIMARY})")
print(f"{'='*100}\n")

for target in TARGETS:
    col = f"hit_tp_{abs(target)}"
    if col in panel_full.columns:
        bo_tp = (panel_full[panel_full["breakout"] == 1][col] == 1).sum()
        bo_tot = len(panel_full[panel_full["breakout"] == 1])
        ct_tp = (panel_full[panel_full["breakout"] == 0][col] == 1).sum()
        ct_tot = len(panel_full[panel_full["breakout"] == 0])

        if bo_tot > 0 and ct_tot > 0:
            bo_pct = bo_tp / bo_tot * 100
            ct_pct = ct_tp / ct_tot * 100
            edge = bo_pct - ct_pct

            # Z-test for proportion
            p_pool = (bo_tp + ct_tp) / (bo_tot + ct_tot)
            se = (p_pool * (1 - p_pool) * (1 / bo_tot + 1 / ct_tot)) ** 0.5
            z = (bo_pct/100 - ct_pct/100) / se if se > 0 else 0
            p_val = 2 * (1 - stats.norm.cdf(abs(z)))

            print(f"Target {target:>3}%:  BO={bo_pct:>5.2f}% ({bo_tp:>5,}/{bo_tot:>6,})  "
                  f"Ctrl={ct_pct:>5.2f}% ({ct_tp:>5,}/{ct_tot:>6,})  "
                  f"Edge={edge:>6.2f}%  p={p_val:.6f}")

# ── STEP 6: Analyze MFE distribution (winning trades only) ──
print(f"\n{'='*100}")
print(f"MFE DISTRIBUTION: Among trades that DON'T hit SL")
print(f"{'='*100}\n")

# Filter to trades without SL
winning_bo = panel_full[(panel_full["breakout"] == 1) & (panel_full["hit_sl"] == 0)]["mfe_pct"].dropna()
winning_ctrl = panel_full[(panel_full["breakout"] == 0) & (panel_full["hit_sl"] == 0)]["mfe_pct"].dropna()

print(f"Breakout (no SL hit): n={len(winning_bo):,}")
print(f"  Mean MFE: {winning_bo.mean():>6.2f}%")
print(f"  Median:   {winning_bo.median():>6.2f}%")
print(f"  p5:       {winning_bo.quantile(0.05):>6.2f}%")
print(f"  p25:      {winning_bo.quantile(0.25):>6.2f}%")
print(f"  p75:      {winning_bo.quantile(0.75):>6.2f}%")
print(f"  p95:      {winning_bo.quantile(0.95):>6.2f}%")

print(f"\nControl (no SL hit): n={len(winning_ctrl):,}")
print(f"  Mean MFE: {winning_ctrl.mean():>6.2f}%")
print(f"  Median:   {winning_ctrl.median():>6.2f}%")
print(f"  p5:       {winning_ctrl.quantile(0.05):>6.2f}%")
print(f"  p25:      {winning_ctrl.quantile(0.25):>6.2f}%")
print(f"  p75:      {winning_ctrl.quantile(0.75):>6.2f}%")
print(f"  p95:      {winning_ctrl.quantile(0.95):>6.2f}%")

# MFE comparison
u, p_mfe = stats.mannwhitneyu(winning_bo, winning_ctrl, alternative="two-sided")
delta_mfe = (2 * u) / (len(winning_bo) * len(winning_ctrl)) - 1
print(f"\nMann-Whitney U: p={p_mfe:.6f}  Cliffs delta={delta_mfe:.4f}")

# ── STEP 7: Find optimal TP (best risk-reward) ──
print(f"\n{'='*100}")
print(f"OPTIMAL TP RECOMMENDATION")
print(f"{'='*100}\n")

edges = []
for target in TARGETS:
    col = f"hit_tp_{abs(target)}"
    bo_tp = (panel_full[panel_full["breakout"] == 1][col] == 1).sum()
    bo_tot = len(panel_full[panel_full["breakout"] == 1])
    ct_tp = (panel_full[panel_full["breakout"] == 0][col] == 1).sum()
    ct_tot = len(panel_full[panel_full["breakout"] == 0])

    if bo_tot > 0 and ct_tot > 0:
        bo_pct = bo_tp / bo_tot
        ct_pct = ct_tp / ct_tot
        edge_pct = (bo_pct - ct_pct) * 100
        rr = abs(target) / 3  # Risk-reward: TP / SL
        edges.append({"target": target, "edge": edge_pct, "bo_rate": bo_pct*100, "rr": rr})

edges_df = pd.DataFrame(edges)
edges_df["score"] = edges_df["edge"] * edges_df["rr"]  # Edge * Risk-Reward
edges_df = edges_df.sort_values("score", ascending=False)

print("Top candidates (sorted by Edge × RiskReward):")
print(edges_df[["target", "edge", "bo_rate", "rr", "score"]].head(5).to_string(index=False))

best_tp = edges_df.iloc[0]["target"]
print(f"\nRECOMMENDATION: TP = {best_tp:.0f}%  (Edge={edges_df.iloc[0]['edge']:.2f}%, RR={edges_df.iloc[0]['rr']:.2f})")

# ── STEP 8: RS Heterogeneity (on full sample) ──
print(f"\n{'='*100}")
print(f"RS HETEROGENEITY ANALYSIS (Full Sample)")
print(f"{'='*100}\n")

d = panel_full.dropna(subset=["rs_score_20"]).copy()
d["rs_decile"] = pd.qcut(d["rs_score_20"], 10, labels=False, duplicates="drop")

# Use best TP for heterogeneity
col_tp = f"hit_tp_{abs(int(best_tp))}"
dec = d.groupby(["rs_decile", "breakout"])[col_tp].mean().unstack(fill_value=0)
if 0 in dec.columns and 1 in dec.columns:
    dec.columns = ["ctrl_rate", "bo_rate"]
    dec["edge"] = dec["bo_rate"] - dec["ctrl_rate"]
    print(f"Edge by RS decile (Target={best_tp:.0f}%, SL=-3%):")
    print((dec[["ctrl_rate", "bo_rate", "edge"]].multiply(100).round(2)).to_string())

    if len(dec) > 1:
        mono, mono_p = stats.spearmanr(np.arange(len(dec)), dec["edge"].to_numpy())
        print(f"\nSpearman correlation (decile vs edge): rho={mono:.3f}, p={mono_p:.4g}")
        if mono_p < 0.05:
            if mono > 0:
                print("  --> High-RS shorts have BETTER edge (counterintuitive)")
            else:
                print("  --> Low-RS shorts have BETTER edge (intuitive)")

print("\nDone.")
