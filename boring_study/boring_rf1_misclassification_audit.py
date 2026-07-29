"""
boring_rf1_misclassification_audit.py -- quantifies RF#1 (boring_signals.py's
scan_boring_breakouts() computes rs_60_decile via pd.qcut over the full
UNGATED eligible universe, then applies the liquidity gate afterward as a
separate AND condition -- contradicting the module's own header comment,
"applied BEFORE ranking (Addendum B: gating after the fact is not
equivalent)"). Read-only, no production files touched.

Method: for every historical N=20 breakout occurrence whose symbol falls in
today's stock_metadata-defined eligible universe (the only universe
scan_boring_breakouts() ever considers -- see caveat below), reconstruct the
full daily cross-section of RS_60 + avg_vol_10d for the ENTIRE eligible
universe as of that date, exactly as _rs60_and_liquidity_asof() /
scan_boring_breakouts() do, then compute BOTH decile assignments:

  (a) CURRENT (buggy):    qcut over the full ungated eligible universe,
                           liquidity checked afterward as a separate AND.
  (b) CORRECTED:          filter to liquidity-passing symbols FIRST, then
                           qcut only within that filtered set.

strategy_confirmed(a) = decile_a == 9 AND liquidity_pass
strategy_confirmed(b) = decile_b == 9   (liquidity already applied via the filter)

Caveat, stated up front: _eligible_universe() in boring_signals.py is NOT
date-parameterized -- it always reflects TODAY's stock_metadata.is_active
roster (305 symbols), with no historical awareness of delisted/renamed
symbols. This script inherits that exact behavior (deliberately, since the
goal is to reconstruct what the CODE actually does, bugs and all) --
meaning historical occurrences for symbols outside today's active roster
are excluded from this analysis, same as they always would have been from
a live scan. Of 80,744 raw N=20 occurrences, 48,196 (59.7%) fall within
today's 305-symbol eligible universe across 5,004 distinct dates.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "../psx_data.db"
LIQ_THRESHOLD = 200_000
RS_WINDOW = 60
TOP_DECILE = 9

# ---------------------------------------------------------------------------
# Step 1: eligible universe -- IDENTICAL query to _eligible_universe()
# ---------------------------------------------------------------------------
con = sqlite3.connect(DB)
q = """
    SELECT sm.symbol FROM stock_metadata sm
    JOIN sectors s ON s.symbol = sm.symbol
    WHERE sm.is_active = 1
"""
uni_df = pd.read_sql_query(q, con)
universe = set(uni_df["symbol"])
import sys
sys.path.insert(0, "..")
from config import EXCLUDED_SECTORS
excl_df = pd.read_sql_query("SELECT symbol, sector FROM sectors", con)
excluded = set(excl_df[excl_df["sector"].isin(EXCLUDED_SECTORS)]["symbol"])
eligible = universe - excluded
print(f"Eligible universe (today's stock_metadata, as boring_signals.py always uses): {len(eligible)} symbols")

placeholders = ",".join("?" for _ in eligible)
prices = pd.read_sql_query(
    f"SELECT symbol, date, close, volume FROM prices_adjusted WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=list(eligible)
)
kse = pd.read_sql_query("SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {"dates": g["date"].to_numpy(), "close": g["close"].to_numpy(dtype=float),
                       "volume": g["volume"].to_numpy(dtype=float)}
kse_dates = kse["date"].to_numpy()
kse_close = kse["close"].to_numpy(dtype=float)

# ---------------------------------------------------------------------------
# Step 2: RS_60 + avg_vol_10d lookup, IDENTICAL math to _rs60_and_liquidity_asof()
# ---------------------------------------------------------------------------
def rs60_liq_asof(sym, asof_date):
    pf = by_symbol.get(sym)
    if pf is None:
        return None, None
    dates = pf["dates"]
    idx = np.searchsorted(dates, asof_date, side="right") - 1
    if idx < RS_WINDOW or idx >= len(dates):
        return None, None
    close_now, close_then = pf["close"][idx], pf["close"][idx - RS_WINDOW]
    if close_then <= 0 or np.isnan(close_now) or np.isnan(close_then):
        return None, None
    stock_ret = close_now / close_then - 1
    k_idx = np.searchsorted(kse_dates, asof_date, side="right") - 1
    if k_idx < RS_WINDOW or k_idx >= len(kse_dates):
        return None, None
    k_now, k_then = kse_close[k_idx], kse_close[k_idx - RS_WINDOW]
    if k_then <= 0 or np.isnan(k_now) or np.isnan(k_then):
        return None, None
    kse_ret = k_now / k_then - 1
    rs_60 = (stock_ret - kse_ret) * 100
    vol10 = pf["volume"][max(0, idx - 9):idx + 1]
    avg_vol_10d = np.nanmean(vol10) if len(vol10) else None
    return rs_60, avg_vol_10d


def prior_date(sym, date):
    pf = by_symbol.get(sym)
    if pf is None:
        return None
    idx = np.searchsorted(pf["dates"], date) - 1
    return pf["dates"][idx] if idx >= 0 else None


# ---------------------------------------------------------------------------
# Step 3: distinct occurrence dates within the eligible universe
# ---------------------------------------------------------------------------
occ = pd.read_csv("boring_donchian_occurrences.csv")
occ_elig = occ[occ["symbol"].isin(eligible)].copy()
print(f"N=20 occurrences within eligible universe: {len(occ_elig):,} rows, "
      f"{occ_elig['date'].nunique():,} distinct dates")

dates_to_check = sorted(occ_elig["date"].unique())
occ_by_date = occ_elig.groupby("date")["symbol"].apply(set).to_dict()

rows = []
for date in dates_to_check:
    # freeze RS_60 / liquidity as of t-1, per symbol, exactly as scan_boring_breakouts() does
    rs_rows = []
    for sym in eligible:
        t1 = prior_date(sym, date)
        if t1 is None:
            continue
        rs_60, avg_vol_10d = rs60_liq_asof(sym, t1)
        if rs_60 is None:
            continue
        rs_rows.append((sym, rs_60, avg_vol_10d))
    if not rs_rows:
        continue
    cross = pd.DataFrame(rs_rows, columns=["symbol", "rs_60", "avg_vol_10d"])

    # (a) CURRENT: qcut over full ungated cross-section
    cross["decile_current"] = pd.qcut(cross["rs_60"], 10, labels=False, duplicates="drop")
    cross["liquidity_pass"] = (cross["avg_vol_10d"].fillna(0) > LIQ_THRESHOLD).astype(int)

    # (b) CORRECTED: filter to liquidity-passing symbols FIRST, then qcut within that subset
    gated_cross = cross[cross["liquidity_pass"] == 1].copy()
    if len(gated_cross) >= 10:
        gated_cross["decile_corrected"] = pd.qcut(gated_cross["rs_60"], 10, labels=False, duplicates="drop")
    else:
        gated_cross["decile_corrected"] = np.nan

    cross = cross.merge(gated_cross[["symbol", "decile_corrected"]], on="symbol", how="left")
    lookup = cross.set_index("symbol")

    fired_syms = occ_by_date.get(date, set())
    for sym in fired_syms:
        if sym not in lookup.index:
            continue
        r = lookup.loc[sym]
        dc = r["decile_current"]
        dcorr = r["decile_corrected"]
        liq = r["liquidity_pass"]
        sc_current = int((dc == TOP_DECILE) and (liq == 1))
        sc_corrected = int((not pd.isna(dcorr)) and (dcorr == TOP_DECILE))
        rows.append({"symbol": sym, "date": date, "decile_current": dc, "decile_corrected": dcorr,
                      "liquidity_pass": liq, "sc_current": sc_current, "sc_corrected": sc_corrected})

result = pd.DataFrame(rows)
result.to_csv("boring_rf1_misclassification_detail.csv", index=False)

n = len(result)
print(f"\nTotal (symbol, date) breakout-occurrence observations evaluated: {n:,}")
print(f"strategy_confirmed under CURRENT (buggy) logic:   {result['sc_current'].sum():,} ({result['sc_current'].mean()*100:.2f}%)")
print(f"strategy_confirmed under CORRECTED logic:          {result['sc_corrected'].sum():,} ({result['sc_corrected'].mean()*100:.2f}%)")

false_neg = result[(result["sc_current"] == 0) & (result["sc_corrected"] == 1)]
false_pos = result[(result["sc_current"] == 1) & (result["sc_corrected"] == 0)]
agree_confirmed = result[(result["sc_current"] == 1) & (result["sc_corrected"] == 1)]

print(f"\nFALSE NEGATIVES (should be Strategy Confirmed under correct logic, but current code says NO): "
      f"{len(false_neg):,} observations, {false_neg['symbol'].nunique():,} distinct symbols")
print(f"FALSE POSITIVES (current code says Strategy Confirmed, but correct logic says NO): "
      f"{len(false_pos):,} observations, {false_pos['symbol'].nunique():,} distinct symbols")
print(f"AGREE (confirmed under both): {len(agree_confirmed):,} observations")

if len(false_neg):
    print(f"\nFalse-negative symbols (sample, up to 20): {sorted(false_neg['symbol'].unique())[:20]}")
if len(false_pos):
    print(f"False-positive symbols (sample, up to 20): {sorted(false_pos['symbol'].unique())[:20]}")

print(f"\nDone. Full per-observation detail: boring_rf1_misclassification_detail.csv")
