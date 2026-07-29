"""
short_donchian_phase1b_statistical_validation.py — Phase 1b validation for N=60 shorts.

For N=60 breakdowns (and matched controls, seed=42):
1. Build matched panels with covariates (RS, liquidity, volatility)
2. Compute forward returns at horizons: 5d, 10d, 20d, 30d, 60d, 90d
3. Run statistical tests (Mann-Whitney U, Cliffs delta)
4. Test RS heterogeneity: does edge vary by stock momentum?
5. Cross-check with N=20 panel for replication

Uses prices_adjusted, stock_signals (for RS), and DFC_SYMBOLS universe.
Outcome measure: TP-before-SL race (binary), plus forward returns.
"""

import sqlite3
import numpy as np
import pandas as pd
import os
from scipy import stats
import statsmodels.api as sm

DB = os.path.join(os.path.dirname(__file__), "..", "psx_data.db")
LOOKBACK_PRIMARY = 60
LOOKBACK_CROSS = 20
STOP_PCT = -0.03
TARGET_PCT = -0.10
MAX_HORIZON = 90
SEED = 42
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

print(f"Loading data for Phase 1b (N={LOOKBACK_PRIMARY}, SL={STOP_PCT*100:.0f}%, Target={TARGET_PCT*100:.0f}%)...\n")

# ── STEP 1: Load price data ──
con = sqlite3.connect(DB)
placeholders = ",".join("?" for _ in DFC_SYMBOLS)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=list(DFC_SYMBOLS)
)

# Load stock_signals for RS and liquidity data
stock_signals = pd.read_sql_query(
    f"SELECT symbol, date, rs_score_20, avg_vol_10d FROM stock_signals "
    f"WHERE symbol IN ({placeholders})",
    con, params=list(DFC_SYMBOLS)
)
con.close()

print(f"Prices: {len(prices):,} rows")
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

# ── STEP 2: Detect breakdowns for both N=60 and N=20 ──
def detect_breakdowns(lookback):
    breakdowns = []
    for sym, pf in by_symbol.items():
        close = pf["close"]
        low = pf["low"]
        dates = pf["dates"]
        n = len(close)

        for i in range(lookback, n):
            prior_low_min = np.nanmin(low[i - lookback:i])
            if prior_low_min > 0 and close[i] < prior_low_min * 0.99:
                breakdowns.append({
                    "symbol": sym,
                    "date": dates[i],
                    "entry_close": close[i],
                    "idx": i
                })
    return pd.DataFrame(breakdowns)

print(f"Detecting breakdowns...")
breakdowns_60 = detect_breakdowns(LOOKBACK_PRIMARY)
breakdowns_20 = detect_breakdowns(LOOKBACK_CROSS)
print(f"  N=60: {len(breakdowns_60):,} breakdowns")
print(f"  N=20: {len(breakdowns_20):,} breakdowns\n")

# ── STEP 3: Generate matched controls ──
def generate_controls(breakdowns_df):
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
    return pd.DataFrame(control_rows)

controls_60 = generate_controls(breakdowns_60)
controls_20 = generate_controls(breakdowns_20)
print(f"Control entries generated:")
print(f"  N=60: {len(controls_60):,}")
print(f"  N=20: {len(controls_20):,}\n")

# ── STEP 4: Compute forward returns and TP-race outcome ──
def add_forward_returns_and_race(df_breakdowns, df_controls):
    """Add forward returns and TP-race binary outcome to both groups."""

    def compute_metrics(df, breakout_flag):
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

            # Forward returns at horizons
            out_row = {
                "symbol": sym,
                "date": date,
                "entry_close": entry,
                "breakout": breakout_flag,
                "rs_score_20": rs_lookup.get(sym, {}).get(date, np.nan)
            }

            for h in HORIZONS:
                j = idx + h
                if j < n and not np.isnan(close[j]):
                    out_row[f"ret_{h}d"] = (close[j] - entry) / entry * 100
                else:
                    out_row[f"ret_{h}d"] = None

            # MFE/MAE
            fwd_high = high[idx + 1:end_j + 1]
            fwd_low = low[idx + 1:end_j + 1]
            valid_h = fwd_high[~np.isnan(fwd_high)]
            valid_l = fwd_low[~np.isnan(fwd_low)]
            out_row["mfe_pct"] = (valid_h.max() - entry) / entry * 100 if len(valid_h) else None
            out_row["mae_pct"] = (valid_l.min() - entry) / entry * 100 if len(valid_l) else None

            # TP-race outcome (binary: hit -10% before -3% SL)
            stop_level = entry * (1 + STOP_PCT)
            target_level = entry * (1 + TARGET_PCT)
            stop_hits = np.where(fwd_high >= stop_level)[0]
            target_hits = np.where(fwd_low <= target_level)[0]
            stop_day = stop_hits[0] if len(stop_hits) else None
            target_day = target_hits[0] if len(target_hits) else None

            if target_day is not None and (stop_day is None or target_day < stop_day):
                out_row["hit_tp_10"] = 1
            else:
                out_row["hit_tp_10"] = 0

            rows.append(out_row)

        return pd.DataFrame(rows)

    bo_panel = compute_metrics(df_breakdowns, 1)
    ctrl_panel = compute_metrics(df_controls, 0)
    return pd.concat([bo_panel, ctrl_panel], ignore_index=True)

print("Computing forward returns and TP-race outcomes...")
panel_60 = add_forward_returns_and_race(breakdowns_60, controls_60)
panel_20 = add_forward_returns_and_race(breakdowns_20, controls_20)
print(f"  N=60 panel: {len(panel_60):,} rows")
print(f"  N=20 panel: {len(panel_20):,} rows\n")

# Save panels for later analysis
panel_60.to_csv("short_panel_60d_phase1b.csv", index=False)
panel_20.to_csv("short_panel_20d_phase1b.csv", index=False)
print("Panels saved: short_panel_60d_phase1b.csv, short_panel_20d_phase1b.csv\n")

# ── STEP 5: Statistical tests (primary panel N=60) ──
print(f"\n{'='*100}\nSTATISTICAL ANALYSIS — N={LOOKBACK_PRIMARY}, SL={STOP_PCT*100:.0f}%, Target={TARGET_PCT*100:.0f}%\n{'='*100}\n")

d = panel_60.dropna(subset=["hit_tp_10", "rs_score_20"]).copy()
bo_count = (d["breakout"] == 1).sum()
ctrl_count = (d["breakout"] == 0).sum()
print(f"Sample: {len(d):,} rows (breakout={bo_count:,}, control={ctrl_count:,})\n")

# Forward returns summary
print(f"FORWARD RETURNS BY HORIZON\n{'-'*80}")
print(f"{'Horizon':<10}{'BO mean%':<12}{'Ctrl mean%':<12}{'MWU p':<12}{'Cliffs delta'}")
print("-" * 80)

def cliffs_delta_via_mwu(x, y):
    u1, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    return (2 * u1) / (len(x) * len(y)) - 1

for h in HORIZONS:
    bo = d[d["breakout"] == 1][f"ret_{h}d"].dropna()
    ct = d[d["breakout"] == 0][f"ret_{h}d"].dropna()
    if len(bo) > 0 and len(ct) > 0:
        u_two, p_two = stats.mannwhitneyu(bo, ct, alternative="two-sided")
        delta = cliffs_delta_via_mwu(bo, ct)
        print(f"{h}d{'':<8}{bo.mean():<12.2f}{ct.mean():<12.2f}{p_two:<12.6f}{delta:.4f}")

# TP-race outcome
print(f"\nTP-RACE OUTCOME (hit -10% before -3% SL)\n{'-'*80}")
bo_tp = d[d["breakout"] == 1]["hit_tp_10"].sum()
bo_tot = len(d[d["breakout"] == 1])
ct_tp = d[d["breakout"] == 0]["hit_tp_10"].sum()
ct_tot = len(d[d["breakout"] == 0])
bo_pct = bo_tp / bo_tot * 100 if bo_tot > 0 else 0
ct_pct = ct_tp / ct_tot * 100 if ct_tot > 0 else 0
edge = bo_pct - ct_pct

p_pool = (bo_tp + ct_tp) / (bo_tot + ct_tot)
se = (p_pool * (1 - p_pool) * (1 / bo_tot + 1 / ct_tot)) ** 0.5
z = (bo_pct/100 - ct_pct/100) / se if se > 0 else 0
p_val = 2 * (1 - stats.norm.cdf(abs(z)))

print(f"Breakout: {bo_pct:.1f}% ({bo_tp:,}/{bo_tot:,})")
print(f"Control:  {ct_pct:.1f}% ({ct_tp:,}/{ct_tot:,})")
print(f"Edge:     {edge:.2f}%")
print(f"Z-stat:   {z:.4f}  p-value: {p_val:.6f}")

# ── STEP 6: RS Heterogeneity ──
print(f"\n{'='*100}\nRS HETEROGENEITY ANALYSIS — N={LOOKBACK_PRIMARY}\n{'='*100}\n")

d["rs_decile"] = pd.qcut(d["rs_score_20"], 10, labels=False, duplicates="drop")
dec = d.groupby(["rs_decile", "breakout"])["hit_tp_10"].mean().unstack(fill_value=0)
if 0 in dec.columns and 1 in dec.columns:
    dec.columns = ["ctrl_rate", "bo_rate"]
    dec["edge"] = dec["bo_rate"] - dec["ctrl_rate"]
    print("Edge by RS decile (0=low RS, 9=high RS):")
    print(dec[["ctrl_rate", "bo_rate", "edge"]].multiply(100).round(2).to_string())
    mono, mono_p = stats.spearmanr(np.arange(len(dec)), dec["edge"].to_numpy())
    print(f"\nSpearman correlation (decile vs edge): rho={mono:.3f}, p={mono_p:.4g}")

# ── STEP 7: Regression model (RS heterogeneity) ──
print(f"\n{'='*100}\nREGRESSION ANALYSIS\n{'='*100}\n")

def zscore(s):
    return (s - s.mean()) / s.std()

d["z_rs"] = zscore(d["rs_score_20"])
d["bo_x_rs"] = d["breakout"] * d["z_rs"]

m1 = sm.OLS(d["hit_tp_10"], sm.add_constant(d[["breakout"]]), missing="drop").fit()
m2 = sm.OLS(d["hit_tp_10"], sm.add_constant(d[["breakout", "z_rs", "bo_x_rs"]]), missing="drop").fit()

print(f"Model 1: hit_tp_10 ~ breakout")
print(f"  N={int(m1.nobs):,}  R^2={m1.rsquared:.5f}")
for name in m1.params.index:
    ci = m1.conf_int()
    print(f"    {name:<20} coef={m1.params[name]:+.5f}  p={m1.pvalues[name]:.4g}")

print(f"\nModel 2: hit_tp_10 ~ breakout + rs(z) + breakout*rs(z)")
print(f"  N={int(m2.nobs):,}  R^2={m2.rsquared:.5f}  Delta R^2={m2.rsquared - m1.rsquared:+.5f}")
for name in m2.params.index:
    ci = m2.conf_int()
    print(f"    {name:<20} coef={m2.params[name]:+.5f}  p={m2.pvalues[name]:.4g}")

# ── STEP 8: Cross-definition check (N=20 replication) ──
print(f"\n{'='*100}\nREPLICATION CHECK — N={LOOKBACK_CROSS}\n{'='*100}\n")

d20 = panel_20.dropna(subset=["hit_tp_10", "rs_score_20"]).copy()
bo20_tp = (d20[d20["breakout"] == 1]["hit_tp_10"] == 1).sum()
bo20_tot = len(d20[d20["breakout"] == 1])
ct20_tp = (d20[d20["breakout"] == 0]["hit_tp_10"] == 1).sum()
ct20_tot = len(d20[d20["breakout"] == 0])
bo20_pct = bo20_tp / bo20_tot * 100 if bo20_tot > 0 else 0
ct20_pct = ct20_tp / ct20_tot * 100 if ct20_tot > 0 else 0
edge20 = bo20_pct - ct20_pct

print(f"N=20 TP-race outcome:")
print(f"  Breakout: {bo20_pct:.1f}% ({bo20_tp:,}/{bo20_tot:,})")
print(f"  Control:  {ct20_pct:.1f}% ({ct20_tp:,}/{ct20_tot:,})")
print(f"  Edge:     {edge20:.2f}%")
print(f"\nComparison:")
print(f"  N=60 edge: {edge:.2f}%")
print(f"  N=20 edge: {edge20:.2f}%")
print(f"  Difference: {edge - edge20:+.2f}%")
if abs(edge - edge20) / edge * 100 < 15:
    print(f"  Status: REPLICATES (within 15% variation)")
else:
    print(f"  Status: DIVERGES (>15% variation)")

print("\nDone.")
