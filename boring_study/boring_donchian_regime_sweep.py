"""
boring_donchian_regime_sweep.py — cross the 5-lookback breakout study with
the existing market_regime classification (unchanged, reused as-is).

For every breakout occurrence (all 5 lookbacks), assign the regime in
effect on that date. Within each regime, build a matched control group:
same stock, random date NOT itself a breakout day for that lookback, AND
in the SAME regime. If a given occurrence's symbol has no eligible
same-regime, non-breakout day, that occurrence is DROPPED from this
regime-conditioned analysis (both breakout and control side) rather than
falling back to a cross-symbol or cross-regime draw — dropping keeps the
same-stock comparison clean; a fallback would reintroduce exactly the bias
the matched-control design exists to avoid. Drop rate reported per cell.

INSUFFICIENT_DATA (199 early-history days, 2005 warmup only) excluded from
the regime split.

Same -6% stop, same 5 targets, same seed (42) for reproducibility.
Read-only against psx_data.db.
"""

import sqlite3
import numpy as np
import pandas as pd

DB = "psx_data.db"
LOOKBACKS = [10, 20, 40, 60, 120]
BUFFER = 1.01
STOP = -0.06
THRESHOLDS = [5, 10, 20, 30, 50]
MAX_HORIZON = 90
SEED = 42
REGIMES = ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]

print("Loading prices_adjusted...")
con = sqlite3.connect(DB)
prices = pd.read_sql_query(
    "SELECT symbol, date, high, low, close FROM prices_adjusted ORDER BY symbol, date", con
)
regime_df = pd.read_sql_query("SELECT date, regime FROM market_regime", con)
con.close()
regime_lookup = dict(zip(regime_df["date"], regime_df["regime"]))
print(f"Loaded {len(prices):,} price rows, {prices['symbol'].nunique():,} symbols, "
      f"{len(regime_lookup):,} regime-dated days\n")

by_symbol = {}
for sym, g in prices.groupby("symbol"):
    g = g.reset_index(drop=True)
    by_symbol[sym] = {
        "dates": g["date"].to_numpy(),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
    }
del prices


def find_breakouts(lookback):
    occs = []
    for sym, pf in by_symbol.items():
        high, close, dates = pf["high"], pf["close"], pf["dates"]
        n = len(dates)
        if n < lookback + 1:
            continue
        prior_high = pd.Series(high).shift(1).rolling(lookback).max().to_numpy()
        c_ok = ~np.isnan(close)
        for t in range(lookback, n):
            ph = prior_high[t]
            if np.isnan(ph) or ph <= 0 or not c_ok[t]:
                continue
            if close[t] > ph * BUFFER:
                d = dates[t]
                occs.append((sym, d, close[t], t, regime_lookup.get(d)))
    return pd.DataFrame(occs, columns=["symbol", "date", "entry_close", "t_idx", "regime"])


def race_pairs(bo_rows, ctrl_rows):
    """Race a list of (symbol, entry, t_idx) breakout rows against the
    matching control rows, both already regime-matched and paired 1:1."""
    def _race_one(sym, entry, t):
        pf = by_symbol.get(sym)
        if pf is None:
            return None
        high, low = pf["high"], pf["low"]
        n = len(high)
        end_j = min(t + MAX_HORIZON, n - 1)
        if end_j <= t:
            return None
        fwd_high = high[t + 1:end_j + 1]
        fwd_low = low[t + 1:end_j + 1]
        stop_level = entry * (1 + STOP)
        stop_hits = np.where(fwd_low <= stop_level)[0]
        stop_day = stop_hits[0] if len(stop_hits) else None
        out = {}
        for th in THRESHOLDS:
            target_level = entry * (1 + th / 100)
            target_hits = np.where(fwd_high >= target_level)[0]
            target_day = target_hits[0] if len(target_hits) else None
            if target_day is None and stop_day is None:
                out[th] = "NEITHER"
            elif target_day is not None and (stop_day is None or target_day < stop_day):
                out[th] = "TP_FIRST"
            else:
                out[th] = "STOP_FIRST"
        return out

    bo_results = {th: {"TP_FIRST": 0, "STOP_FIRST": 0, "NEITHER": 0} for th in THRESHOLDS}
    ct_results = {th: {"TP_FIRST": 0, "STOP_FIRST": 0, "NEITHER": 0} for th in THRESHOLDS}
    for (sym, entry, t) in bo_rows:
        r = _race_one(sym, entry, t)
        if r is None:
            continue
        for th in THRESHOLDS:
            bo_results[th][r[th]] += 1
    for (sym, entry, t) in ctrl_rows:
        r = _race_one(sym, entry, t)
        if r is None:
            continue
        for th in THRESHOLDS:
            ct_results[th][r[th]] += 1
    return bo_results, ct_results


all_results = []
detail_rows = []

for lb in LOOKBACKS:
    print(f"\n{'#'*90}\nLOOKBACK = {lb} days\n{'#'*90}")
    occ = find_breakouts(lb)
    print(f"Total breakout occurrences (all regimes): {len(occ):,}")

    breakout_days = set(zip(occ["symbol"], occ["date"]))

    for regime in REGIMES:
        sub = occ[occ["regime"] == regime]
        rng = np.random.default_rng(SEED)

        # eligible non-breakout, same-regime pool per symbol
        eligible_pool = {}
        for sym, pf in by_symbol.items():
            dates = pf["dates"]
            n = len(dates)
            idxs = np.arange(lb, n)
            pool = [i for i in idxs
                    if (sym, dates[i]) not in breakout_days
                    and regime_lookup.get(dates[i]) == regime]
            eligible_pool[sym] = np.array(pool)

        matched_bo = []
        matched_ctrl = []
        n_dropped = 0
        for _, row in sub.iterrows():
            sym = row["symbol"]
            pool = eligible_pool.get(sym)
            if pool is None or len(pool) == 0:
                n_dropped += 1
                continue
            t_ctrl = int(rng.choice(pool))
            pf = by_symbol[sym]
            entry_ctrl = pf["close"][t_ctrl]
            if entry_ctrl is None or np.isnan(entry_ctrl) or entry_ctrl <= 0:
                n_dropped += 1
                continue
            matched_bo.append((sym, row["entry_close"], row["t_idx"]))
            matched_ctrl.append((sym, entry_ctrl, t_ctrl))

        n_pool = len(sub)
        n_matched = len(matched_bo)
        print(f"\n  Regime: {regime:<15} raw occurrences={n_pool:,}  "
              f"matched (same-stock, same-regime control found)={n_matched:,}  "
              f"dropped={n_dropped:,} ({n_dropped/n_pool*100 if n_pool else 0:.1f}%)")

        if n_matched < 30:
            print(f"    Too few matched pairs ({n_matched}) — skipping race, reporting as thin/unreliable.")
            for th in THRESHOLDS:
                detail_rows.append({
                    "lookback": lb, "regime": regime, "n_raw": n_pool, "n_matched": n_matched,
                    "n_dropped": n_dropped, "threshold": th, "bo_tp_pct": None,
                    "ctrl_tp_pct": None, "improvement_pp": None, "thin": True,
                })
            continue

        bo_race, ct_race = race_pairs(matched_bo, matched_ctrl)
        print(f"  {'Threshold':<12}{'Breakout TP%':<15}{'Control TP%':<14}{'Improvement (pp)'}")
        for th in THRESHOLDS:
            br = bo_race[th]
            cr = ct_race[th]
            br_tot = sum(br.values())
            cr_tot = sum(cr.values())
            br_pct = br["TP_FIRST"] / br_tot * 100 if br_tot else float("nan")
            cr_pct = cr["TP_FIRST"] / cr_tot * 100 if cr_tot else float("nan")
            improvement = br_pct - cr_pct
            print(f"  +{th}%{'':<8}{br_pct:<15.2f}{cr_pct:<14.2f}{improvement:+.2f}")
            detail_rows.append({
                "lookback": lb, "regime": regime, "n_raw": n_pool, "n_matched": n_matched,
                "n_dropped": n_dropped, "threshold": th, "bo_tp_pct": br_pct,
                "ctrl_tp_pct": cr_pct, "improvement_pp": improvement, "thin": False,
            })

detail_df = pd.DataFrame(detail_rows)
detail_df.to_csv("boring_donchian_regime_sweep_detail.csv", index=False)
print("\n\nSaved full detail to boring_donchian_regime_sweep_detail.csv")
print("Done.")
