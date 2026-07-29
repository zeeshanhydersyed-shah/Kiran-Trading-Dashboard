"""
short_donchian_focused_sector_downtrend.py — Focused reality check on post-2011 data.

Scope:
  - Date range: 2011 onwards (ignore 2008-2009 crash artifact)
  - Sectors: Insurance, Commercial Banks, Oil & Gas Exploration, Cable & Electrical Goods
  - Entry: N=60 Donchian breakdown
  - Sector filter: Sector is in downtrend (use sector_rs_rank as proxy for sector strength)
    * Downtrend = sector_rs_rank > 50th percentile (weak sector, rank > median)
  - Exit: TP = -10%, SL = -3%
  - Output: Aggregate edge, hit rate, sample size

Uses: prices_adjusted, sectors, sector_signals, market_regime
"""

import sqlite3
import numpy as np
import pandas as pd
import os
from scipy import stats

DB = os.path.join(os.path.dirname(__file__), "..", "psx_data.db")
LOOKBACK = 60
TP_TARGET = -10
STOP_PCT = -0.03
MAX_HORIZON = 90
SEED = 42
START_DATE = "2011-01-01"

# Target sectors (high-edge performers from Phase 1c)
TARGET_SECTORS = {
    "INSURANCE",
    "COMMERCIAL BANKS",
    "OIL & GAS EXPLORATION COMPANIES",
    "CABLE & ELECTRICAL GOODS"
}

# DFC symbols
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

print(f"Focused Test: Post-2011, Target Sectors, Sector Downtrend Filter")
print(f"TP={TP_TARGET}%, SL={STOP_PCT*100:.0f}%, N={LOOKBACK}\n")

# ── STEP 1: Load data ──
con = sqlite3.connect(DB)
placeholders = ",".join("?" for _ in DFC_SYMBOLS)

prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) AND date >= '{START_DATE}' ORDER BY symbol, date",
    con, params=list(DFC_SYMBOLS)
)

sectors = pd.read_sql_query(
    f"SELECT symbol, sector FROM sectors WHERE symbol IN ({placeholders})",
    con, params=list(DFC_SYMBOLS)
)

sector_signals = pd.read_sql_query(
    f"SELECT date, sector, rs_rank FROM sector_signals WHERE date >= '{START_DATE}'",
    con
)

con.close()

prices["date"] = pd.to_datetime(prices["date"])
sector_signals["date"] = pd.to_datetime(sector_signals["date"])

print(f"Data loaded:")
print(f"  Prices (2011+): {len(prices):,} rows, {prices['date'].min().date()} to {prices['date'].max().date()}")
print(f"  Sector signals: {len(sector_signals):,} rows")
print(f"  Target sectors: {TARGET_SECTORS}\n")

# ── STEP 2: Build lookups ──
by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }

sector_dict = dict(zip(sectors["symbol"], sectors["sector"]))

# Sector rank lookup: (date, sector) -> rank
# This tells us the sector's strength on a given date
sector_rank_lookup = {}
for _, row in sector_signals.iterrows():
    date = row["date"]
    sector = row["sector"]
    rank = row["rs_rank"]  # 1-100, lower = stronger
    sector_rank_lookup[(date, sector)] = rank

print(f"Lookups built.\n")

# ── STEP 3: Detect breakdowns (N=60, post-2011, target sectors only) ──
print(f"Detecting breakdowns (N={LOOKBACK}, target sectors only)...\n")

breakdowns = []
for sym, pf in by_symbol.items():
    # Filter: must be in target sector
    if sector_dict.get(sym) not in TARGET_SECTORS:
        continue

    close = pf["close"]
    low = pf["low"]
    dates = pf["dates"]
    n = len(close)

    for i in range(LOOKBACK, n):
        prior_low_min = np.nanmin(low[i - LOOKBACK:i])
        if prior_low_min > 0 and close[i] < prior_low_min * 0.99:
            entry_date = dates[i]
            stock_sector = sector_dict.get(sym)
            # Check: is the stock's sector in downtrend?
            # Lookup: (entry_date, stock_sector) -> sector_rs_rank
            sector_rank = sector_rank_lookup.get((entry_date, stock_sector))
            # Downtrend = rank > 50 (below median, weak sector)
            # Include None as conservative (assume downtrend if unknown)
            if sector_rank is None or sector_rank > 50:
                breakdowns.append({
                    "symbol": sym,
                    "date": entry_date,
                    "entry_close": close[i],
                    "idx": i,
                    "sector": stock_sector,
                    "sector_rank": sector_rank
                })

breakdowns_df = pd.DataFrame(breakdowns)
print(f"Breakdowns found: {len(breakdowns_df):,}\n")

if len(breakdowns_df) == 0:
    print("ERROR: No breakdowns found. Exiting.")
    exit(1)

print(f"Breakdown distribution by sector:")
for sector in sorted(breakdowns_df["sector"].unique()):
    count = len(breakdowns_df[breakdowns_df["sector"] == sector])
    print(f"  {sector:<35} {count:>5,}")
print()

# ── STEP 4: Generate matched controls ──
print(f"Generating matched controls (seed=42)...\n")

breakdown_days = set(zip(breakdowns_df["symbol"], breakdowns_df["date"]))

rng = np.random.default_rng(SEED)
eligible_pool = {}
for sym, pf in by_symbol.items():
    if sector_dict.get(sym) not in TARGET_SECTORS:
        continue
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
        "idx": t,
        "sector": sector_dict.get(sym)
    })

controls_df = pd.DataFrame(control_rows)
print(f"Control entries generated: {len(controls_df):,}\n")

# ── STEP 5: TP-race computation ──
print(f"Computing TP-race outcomes (TP={TP_TARGET}%, SL={STOP_PCT*100:.0f}%)...\n")

def race_trades(df, label):
    hit_tp = 0
    hit_sl = 0
    neither = 0
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

        # TP and SL levels
        stop_level = entry * (1 + STOP_PCT)
        target_level = entry * (1 + TP_TARGET / 100)

        stop_hits = np.where(fwd_high >= stop_level)[0]
        target_hits = np.where(fwd_low <= target_level)[0]

        stop_day = stop_hits[0] if len(stop_hits) else None
        target_day = target_hits[0] if len(target_hits) else None

        if target_day is not None and (stop_day is None or target_day < stop_day):
            hit_tp += 1
        elif stop_day is not None:
            hit_sl += 1
        else:
            neither += 1

    if n_processed > 0:
        tp_pct = hit_tp / n_processed * 100
        print(f"{label:<15} N={n_processed:>5,}  TP hit={tp_pct:>6.2f}%  ({hit_tp:>5,}/{n_processed:>5,})")
    return hit_tp, n_processed

print("Breakout group:")
bo_tp, bo_tot = race_trades(breakdowns_df, "  Breakouts")

print("\nControl group:")
ct_tp, ct_tot = race_trades(controls_df, "  Controls")

# ── STEP 6: Edge calculation ──
print(f"\n{'='*80}\nRESULTS\n{'='*80}\n")

if bo_tot > 0 and ct_tot > 0:
    bo_pct = bo_tp / bo_tot * 100
    ct_pct = ct_tp / ct_tot * 100
    edge = bo_pct - ct_pct

    # Z-test
    p_pool = (bo_tp + ct_tp) / (bo_tot + ct_tot)
    se = (p_pool * (1 - p_pool) * (1 / bo_tot + 1 / ct_tot)) ** 0.5
    z = (bo_pct/100 - ct_pct/100) / se if se > 0 else 0
    p_val = 2 * (1 - stats.norm.cdf(abs(z)))

    print(f"Breakout group:  {bo_pct:>6.2f}% TP hit rate  ({bo_tp:>5,} / {bo_tot:>5,} trades)")
    print(f"Control group:   {ct_pct:>6.2f}% TP hit rate  ({ct_tp:>5,} / {ct_tot:>5,} trades)")
    print(f"\nEdge (BO - Ctrl): {edge:>6.2f}%")
    print(f"Z-statistic:     {z:>7.3f}")
    print(f"p-value:         {p_val:.6f}")

    print(f"\n{'='*80}")
    if edge >= 3.0 and p_val < 0.05:
        print(f"RESULT: PASS - Edge is real and significant (edge >= 3%, p < 0.05)")
    elif edge >= 2.0 and p_val < 0.10:
        print(f"RESULT: CONDITIONAL - Weak signal (edge >= 2%, p < 0.10)")
    else:
        print(f"RESULT: FAIL - Edge is marginal or insignificant")

else:
    print("ERROR: No valid races computed.")

print("\nDone.")
