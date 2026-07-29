"""
short_donchian_phase1c_regime_sector.py — Phase 1c: Regime and Sector Analysis.

For N=60 breakdowns (N=20 cross-check):
1. Test TP-race outcomes at -15% (primary) and -10% (sensitivity)
2. Split by market regime (trending/ranging/bearish)
3. Split by sector
4. Compute edge, hit rates, statistical tests
5. Identify regime/sector combinations with strong, replicable edges

Uses full sample (no RS filtering). Regime from market_regime table.
Sector from sectors table. SL locked at -3%.
"""

import sqlite3
import numpy as np
import pandas as pd
import os
from scipy import stats

DB = os.path.join(os.path.dirname(__file__), "..", "psx_data.db")
LOOKBACK_PRIMARY = 60
LOOKBACK_CROSS = 20
STOP_PCT = -0.03
TP_PRIMARY = -15
TP_SENSITIVITY = -10
MAX_HORIZON = 90
SEED = 42

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

print(f"Phase 1c: Regime & Sector Analysis (N={LOOKBACK_PRIMARY}, TP_primary={TP_PRIMARY}%, TP_sensitivity={TP_SENSITIVITY}%)\n")

# ── STEP 1: Load data ──
con = sqlite3.connect(DB)
placeholders = ",".join("?" for _ in DFC_SYMBOLS)

prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=list(DFC_SYMBOLS)
)

# Load regime data
regime_data = pd.read_sql_query(
    "SELECT date, regime FROM market_regime ORDER BY date",
    con
)

# Load sector mapping
sectors_map = pd.read_sql_query(
    f"SELECT symbol, sector FROM sectors WHERE symbol IN ({placeholders})",
    con, params=list(DFC_SYMBOLS)
)

con.close()

print(f"Prices: {len(prices):,} rows")
print(f"Regime data: {len(regime_data):,} dates")
print(f"Sectors: {len(sectors_map):,} symbol mappings\n")

# Build lookup dicts
by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }

regime_dict = dict(zip(regime_data["date"], regime_data["regime"]))
sector_dict = dict(zip(sectors_map["symbol"], sectors_map["sector"]))

# ── STEP 2: Detect breakdowns (N=60 and N=20) ──
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

print("Detecting breakdowns...")
breakdowns_60 = detect_breakdowns(LOOKBACK_PRIMARY)
breakdowns_20 = detect_breakdowns(LOOKBACK_CROSS)
print(f"  N=60: {len(breakdowns_60):,}")
print(f"  N=20: {len(breakdowns_20):,}\n")

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
print(f"Controls generated:")
print(f"  N=60: {len(controls_60):,}")
print(f"  N=20: {len(controls_20):,}\n")

# ── STEP 4: Compute TP-race outcomes and add metadata ──
def compute_panel_with_metadata(df_breakdowns, df_controls, lookback):
    """Compute TP-race + regime/sector metadata."""

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
            high = pf["high"]
            low = pf["low"]
            idx = np.searchsorted(dates, date)
            if idx >= len(dates) or dates[idx] != date:
                continue

            n = len(dates)
            end_j = min(idx + MAX_HORIZON, n - 1)
            if end_j <= idx:
                continue

            fwd_high = high[idx + 1:end_j + 1]
            fwd_low = low[idx + 1:end_j + 1]

            out_row = {
                "symbol": sym,
                "date": date,
                "entry_close": entry,
                "breakout": breakout_flag,
                "lookback": lookback,
                "regime": regime_dict.get(date, "Unknown"),
                "sector": sector_dict.get(sym, "Unknown")
            }

            # SL check
            stop_level = entry * (1 + STOP_PCT)
            stop_hits = np.where(fwd_high >= stop_level)[0]
            out_row["hit_sl"] = 1 if len(stop_hits) else 0

            # TP-race at primary and sensitivity targets
            for tp in [TP_PRIMARY, TP_SENSITIVITY]:
                tp_pct = tp / 100
                target_level = entry * (1 + tp_pct)
                target_hits = np.where(fwd_low <= target_level)[0]
                target_day = target_hits[0] if len(target_hits) else None
                stop_day = stop_hits[0] if len(stop_hits) else None

                if target_day is not None and (stop_day is None or target_day < stop_day):
                    out_row[f"hit_tp_{abs(tp)}"] = 1
                else:
                    out_row[f"hit_tp_{abs(tp)}"] = 0

            rows.append(out_row)

        return pd.DataFrame(rows)

    bo_panel = process_trades(df_breakdowns, 1)
    ctrl_panel = process_trades(df_controls, 0)
    return pd.concat([bo_panel, ctrl_panel], ignore_index=True)

print("Computing TP-race outcomes + metadata...")
panel_60 = compute_panel_with_metadata(breakdowns_60, controls_60, LOOKBACK_PRIMARY)
panel_20 = compute_panel_with_metadata(breakdowns_20, controls_20, LOOKBACK_CROSS)
print(f"  N=60 panel: {len(panel_60):,} rows")
print(f"  N=20 panel: {len(panel_20):,} rows\n")

# Save panels
panel_60.to_csv("short_panel_60d_phase1c.csv", index=False)
panel_20.to_csv("short_panel_20d_phase1c.csv", index=False)

# ── STEP 5: Analysis by Regime (Primary Target -15%) ──
print(f"{'='*100}")
print(f"REGIME ANALYSIS (TP={TP_PRIMARY}%, SL=-3%)")
print(f"{'='*100}\n")

def analyze_regime_sector(panel, label, tp_target):
    tp_col = f"hit_tp_{abs(tp_target)}"
    if tp_col not in panel.columns:
        print(f"  Column {tp_col} not found")
        return

    # By Regime
    print(f"BY REGIME ({label}):")
    print(f"{'Regime':<12}{'Breakouts':<12}{'BO Rate':<12}{'Controls':<12}{'Ctrl Rate':<12}{'Edge':<10}{'p-value'}")
    print("-" * 80)

    regimes = panel["regime"].unique()
    regime_results = []
    for regime in sorted(regimes):
        subset = panel[panel["regime"] == regime]
        bo = subset[subset["breakout"] == 1][tp_col].sum()
        bo_tot = len(subset[subset["breakout"] == 1])
        ct = subset[subset["breakout"] == 0][tp_col].sum()
        ct_tot = len(subset[subset["breakout"] == 0])

        if bo_tot > 0 and ct_tot > 0:
            bo_pct = bo / bo_tot * 100
            ct_pct = ct / ct_tot * 100
            edge = bo_pct - ct_pct

            # Z-test
            p_pool = (bo + ct) / (bo_tot + ct_tot)
            se = (p_pool * (1 - p_pool) * (1 / bo_tot + 1 / ct_tot)) ** 0.5
            z = (bo_pct/100 - ct_pct/100) / se if se > 0 else 0
            p_val = 2 * (1 - stats.norm.cdf(abs(z)))

            print(f"{regime:<12}{bo_tot:<12,}{bo_pct:<12.2f}{ct_tot:<12,}{ct_pct:<12.2f}{edge:<10.2f}{p_val:.6f}")
            regime_results.append({"regime": regime, "bo_tot": bo_tot, "bo_pct": bo_pct, "edge": edge, "p_val": p_val})

    # By Sector
    print(f"\nBY SECTOR ({label}):")
    print(f"{'Sector':<30}{'Breakouts':<12}{'BO Rate':<12}{'Controls':<12}{'Ctrl Rate':<12}{'Edge':<10}")
    print("-" * 90)

    sectors = panel[panel["sector"] != "Unknown"]["sector"].unique()
    sector_results = []
    for sector in sorted(sectors):
        subset = panel[panel["sector"] == sector]
        bo = subset[subset["breakout"] == 1][tp_col].sum()
        bo_tot = len(subset[subset["breakout"] == 1])
        ct = subset[subset["breakout"] == 0][tp_col].sum()
        ct_tot = len(subset[subset["breakout"] == 0])

        if bo_tot >= 10:  # Min sample size
            bo_pct = bo / bo_tot * 100
            ct_pct = ct / ct_tot * 100
            edge = bo_pct - ct_pct
            print(f"{sector:<30}{bo_tot:<12,}{bo_pct:<12.2f}{ct_tot:<12,}{ct_pct:<12.2f}{edge:<10.2f}")
            sector_results.append({"sector": sector, "bo_tot": bo_tot, "bo_pct": bo_pct, "edge": edge})

    return regime_results, sector_results

regime_60, sector_60 = analyze_regime_sector(panel_60, "N=60", TP_PRIMARY)

# ── STEP 6: Sensitivity Check on -10% ──
print(f"\n{'='*100}")
print(f"SENSITIVITY CHECK (TP={TP_SENSITIVITY}%, SL=-3%)")
print(f"{'='*100}\n")

regime_60_sens, sector_60_sens = analyze_regime_sector(panel_60, "N=60 Sensitivity", TP_SENSITIVITY)

# ── STEP 7: Replication Check (N=60 vs N=20) ──
print(f"\n{'='*100}")
print(f"REPLICATION CHECK: N=60 vs N=20 (TP={TP_PRIMARY}%)")
print(f"{'='*100}\n")

tp_col = f"hit_tp_{abs(TP_PRIMARY)}"

# Overall replication
bo60 = panel_60[panel_60["breakout"] == 1][tp_col].sum()
bo60_tot = len(panel_60[panel_60["breakout"] == 1])
ct60 = panel_60[panel_60["breakout"] == 0][tp_col].sum()
ct60_tot = len(panel_60[panel_60["breakout"] == 0])
edge60 = (bo60 / bo60_tot - ct60 / ct60_tot) * 100 if bo60_tot > 0 and ct60_tot > 0 else 0

bo20 = panel_20[panel_20["breakout"] == 1][tp_col].sum()
bo20_tot = len(panel_20[panel_20["breakout"] == 1])
ct20 = panel_20[panel_20["breakout"] == 0][tp_col].sum()
ct20_tot = len(panel_20[panel_20["breakout"] == 0])
edge20 = (bo20 / bo20_tot - ct20 / ct20_tot) * 100 if bo20_tot > 0 and ct20_tot > 0 else 0

print(f"Overall Edge:")
print(f"  N=60: {edge60:.2f}%")
print(f"  N=20: {edge20:.2f}%")
diff_pct = abs(edge60 - edge20) / edge60 * 100 if edge60 > 0 else 0
print(f"  Difference: {diff_pct:.1f}%")
if diff_pct < 15:
    print(f"  Status: REPLICATES\n")
else:
    print(f"  Status: DIVERGES\n")

# Regime replication
if regime_60:
    print(f"Edge by Regime:")
    print(f"{'Regime':<15}{'N=60':<10}{'N=20':<10}{'Match'}")
    print("-" * 40)
    for r60 in regime_60:
        r20 = [r for r in regime_60_sens if r["regime"] == r60["regime"]]
        if r20:
            print(f"{r60['regime']:<15}{r60['edge']:<10.2f}{r20[0]['edge']:<10.2f}OK")

print("\nDone.")
