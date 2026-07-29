"""
short_donchian_phase1a_by_lookback.py — Empirical stop-loss discovery for short breakdowns.

For every breakdown occurrence on DFC_SYMBOLS only, for EACH lookback period separately,
race each profit target (-5%, -10%, -20%, -30%, -50%) against a range of fixed stop-loss
levels (-3%, -4%, -5%, -6%, -7%, -8%, -10%), using daily low (target) / high (stop).

Breakdown: close[t] < MIN(low[t-N..t-1]) × 0.99
Tests each N ∈ {10,20,40,60,120} separately (not pooled).
Uses prices_adjusted. Horizon: 90 trading days max.
Tie rule: both target and stop touched same day → stop wins (conservative).

Compares breakdown group vs. matched control group (seed=42) to quantify edge per lookback.
Output: per-lookback summary tables of TP-hit rate edge at each SL level.
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

# ── STEP 1: Load price data ──
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

# ── STEP 2: Process each lookback separately ──
results_by_lookback = {}

for lookback in LOOKBACKS:
    print(f"\n{'='*100}")
    print(f"LOOKBACK N = {lookback}")
    print(f"{'='*100}\n")

    # Detect breakdowns for this lookback only
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

    breakdowns_df = pd.DataFrame(breakdowns)
    print(f"Breakdown occurrences (N={lookback}): {len(breakdowns_df):,}")
    if len(breakdowns_df) == 0:
        print("  → No breakdowns for this lookback. Skipping.\n")
        continue
    print(f"  Symbols with breakdowns: {breakdowns_df['symbol'].nunique()}\n")

    # Generate matched control group (seed=42)
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

    # ── Race function ──
    def race_all_stops(df, label):
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

            fwd_high = high[idx + 1:end_j + 1]
            fwd_low = low[idx + 1:end_j + 1]
            n_processed += 1

            for stop in STOP_LEVELS:
                stop_level = entry * (1 + stop)
                stop_hits = np.where(fwd_high >= stop_level)[0]
                stop_day = stop_hits[0] if len(stop_hits) else None

                for target in TARGETS:
                    target_pct = target / 100
                    target_level = entry * (1 + target_pct)
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

    # ── Summary at -10% target ──
    print(f"\n{'-'*100}\nEDGE at each SL level (target = -10%)\n{'-'*100}\n")
    print(f"{'SL%':<6}{'BO TP%':<18}{'Ctrl TP%':<18}{'Edge':<15}")
    print("-" * 60)

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

            print(f"{stop*100:>5.0f}% {bo_pct:>6.1f}% ({bo['TP_FIRST']:,}/{bo_tot:,}){'':<2}"
                  f"{ct_pct:>6.1f}% ({ct['TP_FIRST']:,}/{ct_tot:,}){'':<2}"
                  f"{edge:>6.2f}%")

    if edge_by_sl:
        best_sl = max(edge_by_sl, key=edge_by_sl.get)
        best_edge = edge_by_sl[best_sl]
        print(f"\nRecommended SL for N={lookback}: {best_sl*100:.0f}% (edge = {best_edge:.2f}%)")
    else:
        print(f"\nNo valid results for N={lookback}")
        continue

    # ── Full matrix at recommended SL ──
    print(f"\n{'-'*100}\nFull matrix at SL = {best_sl*100:.0f}%\n{'-'*100}\n")
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

    # Store results for this lookback
    results_by_lookback[lookback] = {
        "n_breakdowns": len(breakdowns_df),
        "n_controls": len(controls_df),
        "best_sl": best_sl,
        "best_edge": best_edge,
        "bo_results": bo_results,
        "ctrl_results": ctrl_results
    }

# ── Final summary across all lookbacks ──
print(f"\n\n{'='*100}\nSUMMARY: OPTIMAL SL BY LOOKBACK PERIOD\n{'='*100}\n")
print(f"{'N':<6}{'Breakdowns':<15}{'Controls':<15}{'Best SL':<10}{'Edge @ -10%':<15}")
print("-" * 65)

for lookback in LOOKBACKS:
    if lookback in results_by_lookback:
        r = results_by_lookback[lookback]
        print(f"{lookback:<6}{r['n_breakdowns']:<15,}{r['n_controls']:<15,}{r['best_sl']*100:>5.0f}%{'':<5}{r['best_edge']:>6.2f}%")
    else:
        print(f"{lookback:<6}{'(no data)':<15}")

print("\nDone.")
