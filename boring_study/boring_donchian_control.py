"""
boring_donchian_control.py — control-group experiment for the boring
Donchian study. Does the breakout event itself carry information, or would
a random entry on the same stock do just as well?

Design: for every breakout occurrence already found (80,744, in
boring_donchian_occurrences.csv), draw ONE random entry on the SAME symbol,
from a date that is (a) not itself a flagged breakout day for that symbol,
and (b) at trading-day index >= 20 within that symbol's history (same
eligibility floor breakouts themselves require, so the two groups draw from
the same pool of "possible days" per stock — not skewed by early-history-
only or late-history-only bias).

Same outcome measurement as the breakout study: forward return at
5/10/20/30/60/90 trading days, MFE/MAE over the (up to) 90-day window using
high/low, and the TP-before-(-6%)-stop race at +5/10/20/30/50%. Same
same-day-tie rule (stop wins).

Random seed fixed (42) for reproducibility. Read-only against psx_data.db.
"""

import sqlite3
import numpy as np
import pandas as pd
from scipy import stats

DB = "psx_data.db"
LOOKBACK = 20
STOP = -0.06
THRESHOLDS = [5, 10, 20, 30, 50]
HORIZONS = [5, 10, 20, 30, 60, 90]
MAX_HORIZON = 90
SEED = 42

occ = pd.read_csv("boring_donchian_occurrences.csv")
print(f"Breakout occurrences: {len(occ):,}")

breakout_days = set(zip(occ["symbol"], occ["date"]))

con = sqlite3.connect(DB)
symbols = occ["symbol"].unique().tolist()
placeholders = ",".join("?" for _ in symbols)
prices = pd.read_sql_query(
    f"SELECT symbol, date, high, low, close FROM prices_adjusted "
    f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
    con, params=symbols
)
con.close()

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }

# ── eligible non-breakout day pool per symbol (index >= LOOKBACK, not a
# flagged breakout day) ──
rng = np.random.default_rng(SEED)
eligible_pool = {}
for sym, pf in by_symbol.items():
    dates = pf["dates"]
    n = len(dates)
    idxs = np.arange(LOOKBACK, n)
    non_breakout_idxs = [i for i in idxs if (sym, dates[i]) not in breakout_days]
    eligible_pool[sym] = np.array(non_breakout_idxs)

# ── draw one random control entry per breakout occurrence ──
control_rows = []
skipped_no_pool = 0
for _, row in occ.iterrows():
    sym = row["symbol"]
    pool = eligible_pool.get(sym)
    if pool is None or len(pool) == 0:
        skipped_no_pool += 1
        continue
    t = int(rng.choice(pool))
    pf = by_symbol[sym]
    dates, high, low, close = pf["dates"], pf["high"], pf["low"], pf["close"]
    n = len(dates)
    entry = close[t]
    if entry is None or np.isnan(entry) or entry <= 0:
        skipped_no_pool += 1
        continue

    crow = {"symbol": sym, "date": dates[t], "entry_close": entry}
    for h in HORIZONS:
        j = t + h
        if j < n and not np.isnan(close[j]):
            crow[f"ret_{h}d"] = (close[j] - entry) / entry * 100
        else:
            crow[f"ret_{h}d"] = None

    end_j = min(t + MAX_HORIZON, n - 1)
    if end_j > t:
        fwd_high = high[t + 1:end_j + 1]
        fwd_low = low[t + 1:end_j + 1]
        valid_h = fwd_high[~np.isnan(fwd_high)]
        valid_l = fwd_low[~np.isnan(fwd_low)]
        crow["mfe_pct"] = (valid_h.max() - entry) / entry * 100 if len(valid_h) else None
        crow["mae_pct"] = (valid_l.min() - entry) / entry * 100 if len(valid_l) else None
        crow["days_tracked"] = end_j - t
    else:
        crow["mfe_pct"] = None
        crow["mae_pct"] = None
        crow["days_tracked"] = 0

    control_rows.append(crow)

ctrl = pd.DataFrame(control_rows)
print(f"Control entries generated: {len(ctrl):,} (skipped, no eligible pool: {skipped_no_pool})")
ctrl.to_csv("boring_donchian_control_occurrences.csv", index=False)
print("Saved to boring_donchian_control_occurrences.csv\n")

# ── TP-vs-stop race, control group ──
def race(df):
    results = {th: {"TP_FIRST": 0, "STOP_FIRST": 0, "NEITHER": 0} for th in THRESHOLDS}
    con2 = sqlite3.connect(DB)
    for _, row in df.iterrows():
        sym, date, entry = row["symbol"], row["date"], row["entry_close"]
        pf = by_symbol.get(sym)
        if pf is None:
            continue
        dates, high, low = pf["dates"], pf["high"], pf["low"]
        idx = np.searchsorted(dates, date)
        if idx >= len(dates) or dates[idx] != date:
            continue
        n = len(dates)
        end_j = min(idx + MAX_HORIZON, n - 1)
        if end_j <= idx:
            continue
        fwd_high = high[idx + 1:end_j + 1]
        fwd_low = low[idx + 1:end_j + 1]
        stop_level = entry * (1 + STOP)
        stop_hits = np.where(fwd_low <= stop_level)[0]
        stop_day = stop_hits[0] if len(stop_hits) else None
        for th in THRESHOLDS:
            target_level = entry * (1 + th / 100)
            target_hits = np.where(fwd_high >= target_level)[0]
            target_day = target_hits[0] if len(target_hits) else None
            if target_day is None and stop_day is None:
                results[th]["NEITHER"] += 1
            elif target_day is not None and (stop_day is None or target_day < stop_day):
                results[th]["TP_FIRST"] += 1
            else:
                results[th]["STOP_FIRST"] += 1
    con2.close()
    return results

print("Racing control group vs -6% stop...")
ctrl_race = race(ctrl)
print("Racing breakout group vs -6% stop (recompute for consistency)...")
breakout_race = race(occ)

# ── summary tables ──
def summarize(df, label):
    print(f"\n{'='*80}\n{label} — N={len(df):,}\n{'='*80}")
    print(f"{'Horizon':<10}{'N':<9}{'Mean%':<10}{'Median%':<10}{'% Positive'}")
    for h in HORIZONS:
        s = df[f"ret_{h}d"].dropna()
        print(f"{h}d{'':<8}{len(s):<9}{s.mean():<10.2f}{s.median():<10.2f}{(s>0).mean()*100:.1f}%")
    mfe = df["mfe_pct"].dropna()
    mae = df["mae_pct"].dropna()
    print(f"\nMFE: N={len(mfe):,}, mean={mfe.mean():.2f}%, median={mfe.median():.2f}%")
    print(f"MAE: N={len(mae):,}, mean={mae.mean():.2f}%, median={mae.median():.2f}%")

summarize(occ, "BREAKOUT GROUP")
summarize(ctrl, "CONTROL GROUP (random entry, same stock)")

print(f"\n{'='*80}\nTP-before-(-6%)-stop race, both groups\n{'='*80}")
print(f"{'Threshold':<12}{'Breakout: Hit TP first':<26}{'Control: Hit TP first'}")
for th in THRESHOLDS:
    br = breakout_race[th]
    cr = ctrl_race[th]
    br_tot = sum(br.values())
    cr_tot = sum(cr.values())
    br_pct = br["TP_FIRST"] / br_tot * 100
    cr_pct = cr["TP_FIRST"] / cr_tot * 100
    print(f"+{th}%{'':<8}{br_pct:>6.1f}% ({br['TP_FIRST']:,}/{br_tot:,}){'':<4}"
          f"{cr_pct:>6.1f}% ({cr['TP_FIRST']:,}/{cr_tot:,})")

# ── statistical comparison ──
print(f"\n{'='*80}\nSTATISTICAL COMPARISON — breakout vs control\n{'='*80}")

def cliffs_delta_via_mwu(x, y):
    u1, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    return (2 * u1) / (len(x) * len(y)) - 1

print(f"\n{'Metric':<10}{'BO mean':<10}{'Ctrl mean':<11}{'MWU p (2-sided)':<18}{'Cliffs delta'}")
for h in HORIZONS:
    bo = occ[f"ret_{h}d"].dropna()
    ct = ctrl[f"ret_{h}d"].dropna()
    u_two, p_two = stats.mannwhitneyu(bo, ct, alternative="two-sided")
    delta = cliffs_delta_via_mwu(bo, ct)
    print(f"{h}d{'':<8}{bo.mean():<10.2f}{ct.mean():<11.2f}{p_two:<18.6f}{delta:.4f}")

bo_mfe = occ["mfe_pct"].dropna()
ct_mfe = ctrl["mfe_pct"].dropna()
_, p_mfe = stats.mannwhitneyu(bo_mfe, ct_mfe, alternative="two-sided")
delta_mfe = cliffs_delta_via_mwu(bo_mfe, ct_mfe)
print(f"{'MFE':<10}{bo_mfe.mean():<10.2f}{ct_mfe.mean():<11.2f}{p_mfe:<18.6f}{delta_mfe:.4f}")

bo_mae = occ["mae_pct"].dropna()
ct_mae = ctrl["mae_pct"].dropna()
_, p_mae = stats.mannwhitneyu(bo_mae, ct_mae, alternative="two-sided")
delta_mae = cliffs_delta_via_mwu(bo_mae, ct_mae)
print(f"{'MAE':<10}{bo_mae.mean():<10.2f}{ct_mae.mean():<11.2f}{p_mae:<18.6f}{delta_mae:.4f}")

print(f"\n{'Threshold':<12}{'BO TP%':<10}{'Ctrl TP%':<11}{'z-stat':<10}{'p-value'}")
for th in THRESHOLDS:
    br = breakout_race[th]
    cr = ctrl_race[th]
    br_tot = sum(br.values())
    cr_tot = sum(cr.values())
    p1 = br["TP_FIRST"] / br_tot
    p2 = cr["TP_FIRST"] / cr_tot
    p_pool = (br["TP_FIRST"] + cr["TP_FIRST"]) / (br_tot + cr_tot)
    se = (p_pool * (1 - p_pool) * (1 / br_tot + 1 / cr_tot)) ** 0.5
    z = (p1 - p2) / se
    p_val = 2 * (1 - stats.norm.cdf(abs(z)))
    print(f"+{th}%{'':<8}{p1*100:<10.2f}{p2*100:<11.2f}{z:<10.4f}{p_val:.6f}")

print("\nDone.")
