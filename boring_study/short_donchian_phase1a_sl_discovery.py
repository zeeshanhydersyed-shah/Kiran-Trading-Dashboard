"""
short_donchian_phase1a_sl_discovery.py — Empirical stop-loss discovery for short breakdowns.

For every breakdown occurrence on DFC_SYMBOLS only, race each profit target
(-5%, -10%, -20%, -30%, -50%) against a range of fixed stop-loss levels
(-3%, -4%, -5%, -6%, -7%, -8%, -10%), using daily low (target) / high (stop).

Breakdown: close[t] < MIN(low[t-N..t-1]) × 0.99, N ∈ {10,20,40,60,120}
Uses prices_adjusted. Horizon: 90 trading days max.
Tie rule: both target and stop touched same day → stop wins (conservative).

Compares breakdown group vs. matched control group (seed=42) to quantify edge.
Output: summary table of TP-hit rate edge at each SL level.
"""

import sqlite3
import numpy as np
import pandas as pd
import os

DB = os.path.join(os.path.dirname(__file__), "..", "psx_data.db")
LOOKBACKS = [10, 20, 40, 60, 120]
STOP_LEVELS = [-0.03, -0.04, -0.05, -0.06, -0.07, -0.08, -0.10]
TARGETS = [-5, -10, -20, -30, -50]
MAX_HORIZON = 90
SEED = 42

# DFC-eligible symbols (shortable on PSX)
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

print(f"DFC-eligible symbols: {len(DFC_SYMBOLS)}\n")

# ── STEP 1: Detect breakdowns on DFC_SYMBOLS ──
con = sqlite3.connect(DB)
placeholders = ",".join("?" for _ in DFC_SYMBOLS)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=list(DFC_SYMBOLS)
)
con.close()

print(f"Price data rows (DFC symbols): {len(prices):,}\n")

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }

# Detect breakdowns: close[t] < MIN(low[t-N..t-1]) × 0.99
breakdowns = []
for sym, pf in by_symbol.items():
    close = pf["close"]
    low = pf["low"]
    dates = pf["dates"]
    n = len(close)

    for lookback in LOOKBACKS:
        for i in range(lookback, n):
            prior_low_min = np.nanmin(low[i - lookback:i])
            if prior_low_min > 0 and close[i] < prior_low_min * 0.99:
                breakdowns.append({
                    "symbol": sym,
                    "date": dates[i],
                    "entry_close": close[i],
                    "lookback": lookback,
                    "idx": i
                })

breakdowns_df = pd.DataFrame(breakdowns)
print(f"Breakdown occurrences (DFC, all lookbacks): {len(breakdowns_df):,}")
if len(breakdowns_df) > 0:
    print(f"  Symbols with breakdowns: {breakdowns_df['symbol'].nunique()}\n")
else:
    print("ERROR: No breakdowns found. Exiting.\n")
    exit(1)

# ── STEP 2: Generate matched control group (seed=42) ──
breakdown_days = set(zip(breakdowns_df["symbol"], breakdowns_df["date"]))

rng = np.random.default_rng(SEED)
eligible_pool = {}
for sym, pf in by_symbol.items():
    dates = pf["dates"]
    n = len(dates)
    idxs = np.arange(20, n)  # Same eligibility floor as long-side
    non_breakdown_idxs = [i for i in idxs if (sym, dates[i]) not in breakdown_days]
    eligible_pool[sym] = np.array(non_breakdown_idxs)

control_rows = []
skipped = 0
for _, row in breakdowns_df.iterrows():
    sym = row["symbol"]
    pool = eligible_pool.get(sym)
    if pool is None or len(pool) == 0:
        skipped += 1
        continue
    t = int(rng.choice(pool))
    pf = by_symbol[sym]
    dates, high, low, close = pf["dates"], pf["high"], pf["low"], pf["close"]
    entry = close[t]
    if entry is None or np.isnan(entry) or entry <= 0:
        skipped += 1
        continue

    control_rows.append({
        "symbol": sym,
        "date": dates[t],
        "entry_close": entry,
        "idx": t
    })

controls_df = pd.DataFrame(control_rows)
print(f"Control entries generated: {len(controls_df):,} (skipped: {skipped})\n")

# ── STEP 3: Race function — test multiple SL levels ──
def race_all_stops(df, label):
    """
    For each row in df, race targets against all stop levels.
    Returns dict: {stop_pct: {target_pct: {"TP_FIRST": count, "STOP_FIRST": count, "NEITHER": count}}}
    """
    results = {
        stop: {
            target: {"TP_FIRST": 0, "STOP_FIRST": 0, "NEITHER": 0}
            for target in TARGETS
        }
        for stop in STOP_LEVELS
    }

    n_processed = 0
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

        # Forward high/low from entry+1 onward (for SHORT: target is low, stop is high)
        fwd_high = high[idx + 1:end_j + 1]
        fwd_low = low[idx + 1:end_j + 1]
        n_processed += 1

        for stop in STOP_LEVELS:
            stop_level = entry * (1 + stop)  # Entry * (1 - |stop|), e.g., entry * 0.94 for -6%
            stop_hits = np.where(fwd_high >= stop_level)[0]
            stop_day = stop_hits[0] if len(stop_hits) else None

            for target in TARGETS:
                target_pct = target / 100  # e.g., -10% → -0.10
                target_level = entry * (1 + target_pct)  # Entry * 0.90 for -10%
                target_hits = np.where(fwd_low <= target_level)[0]
                target_day = target_hits[0] if len(target_hits) else None

                if target_day is None and stop_day is None:
                    results[stop][target]["NEITHER"] += 1
                elif target_day is not None and (stop_day is None or target_day < stop_day):
                    results[stop][target]["TP_FIRST"] += 1
                else:
                    results[stop][target]["STOP_FIRST"] += 1

    print(f"{label}: {n_processed:,} rows processed")
    return results

print("Racing breakdown group...")
bo_results = race_all_stops(breakdowns_df, "BREAKDOWN GROUP")
print("Racing control group...")
ctrl_results = race_all_stops(controls_df, "CONTROL GROUP")

# ── STEP 4: Summarize and compute edge ──
print(f"\n{'='*100}\nEDGE ANALYSIS: TP-hit % at each SL level (target = -10%)\n{'='*100}\n")
print(f"{'SL%':<6}{'BO TP% (-10%)':<18}{'Ctrl TP% (-10%)':<18}{'Edge (BO-Ctrl)':<18}{'BO N':<10}{'Ctrl N':<10}")
print("-" * 100)

edge_by_sl = {}
for stop in sorted(STOP_LEVELS):
    target = -10
    bo = bo_results[stop][target]
    ct = ctrl_results[stop][target]
    bo_tot = sum(bo.values())
    ct_tot = sum(ct.values())

    if bo_tot > 0 and ct_tot > 0:
        bo_pct = bo["TP_FIRST"] / bo_tot * 100
        ct_pct = ct["TP_FIRST"] / ct_tot * 100
        edge = bo_pct - ct_pct
        edge_by_sl[stop] = edge

        print(f"{stop*100:>5.0f}% {bo_pct:>6.1f}% ({bo['TP_FIRST']:,}/{bo_tot:,}){'':<4}"
              f"{ct_pct:>6.1f}% ({ct['TP_FIRST']:,}/{ct_tot:,}){'':<4}"
              f"{edge:>6.2f}%{'':<10}{bo_tot:>9,}{'':<4}{ct_tot:>9,}")

# Find best SL
best_sl = max(edge_by_sl, key=edge_by_sl.get)
best_edge = edge_by_sl[best_sl]
print(f"\n{'RECOMMENDATION:':<20} SL = {best_sl*100:.0f}% (edge = {best_edge:.2f}%)")

# ── STEP 5: Full matrix at recommended SL ──
print(f"\n{'='*100}\nFULL MATRIX at recommended SL = {best_sl*100:.0f}%\n{'='*100}\n")
print(f"{'Target':<10}{'BO TP%':<15}{'Ctrl TP%':<15}{'Edge':<15}")
print("-" * 55)

for target in TARGETS:
    bo = bo_results[best_sl][target]
    ct = ctrl_results[best_sl][target]
    bo_tot = sum(bo.values())
    ct_tot = sum(ct.values())

    if bo_tot > 0 and ct_tot > 0:
        bo_pct = bo["TP_FIRST"] / bo_tot * 100
        ct_pct = ct["TP_FIRST"] / ct_tot * 100
        edge = bo_pct - ct_pct
        print(f"{target:>5}%{'':<4}{bo_pct:>6.1f}%{'':<8}{ct_pct:>6.1f}%{'':<8}{edge:>6.2f}%")

print("\nDone.")
