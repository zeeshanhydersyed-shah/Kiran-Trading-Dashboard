"""
regime_transition_age_test.py — Test: does days-since-TRENDING_UP-transition
predict fwd_return_10d? And: does VOLATILE regime show worse fwd_return_10d
than other regimes? Market-only test of a PI personal-journal observation
(242 trades, 20 months, confounded by execution/sizing/discretion).

Read-only against psx_data.db. No production writes.

Population/methodology notes (investigated before running, not assumed):
- stock_signals has NO fwd_return_10d column (task framing assumed it did —
  checked via PRAGMA table_info, confirmed absent). fwd_return_10d is
  computed fresh here from prices_adjusted, using the exact same formula as
  compute_forward_returns.py: (close at pos+10 trading days - close at pos)
  / close at pos * 100, using each symbol's full continuous prices_adjusted
  sequence (not the liquidity-gated stock_signals dates, which have gaps) —
  same convention used to build pre_breakout_v2_staging_full's fwd_return_10d.
- market_regime.regime_days is NOT used to compute days-since-transition.
  CLAUDE.md's "Known Gaps: Postgres Parity" section documents regime_days as
  confirmed ~2x inflated across same-date re-runs, and dashboard_pg.py's
  get_regime_status_pg() already deliberately ignores the stored column for
  this reason. Per this project's production-DB-discipline convention
  (independent re-verification, not trust), days-since-transition is
  recomputed here directly from the raw `regime` label sequence.
- Convention: the transition day itself (first day of the new regime) = 0
  days since transition. Day 1 = the next trading day in that regime, etc.
  This matches "days after transition" in the journal's own framing (a
  trade taken ON the transition day is 0 days after it).
- Era boundaries reused verbatim from prebreakout_v2_phase4c_velocity_volume.py:
  Development 2015-01-01..2019-12-31, Validation 2020-01-01..2022-12-31,
  OOS 2023-01-01 onward.
- Cliff's delta / MWU / Welch's t formulas reused verbatim from
  prebreakout_v2_phase4c_velocity_volume.py's two_group_test().
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DB = str(Path(__file__).parent / "psx_data.db")
LIQUIDITY_GATE = 200_000
FWD_WINDOW = 10

ERAS = [
    ("Development", "2015-01-01", "2019-12-31"),
    ("Validation",  "2020-01-01", "2022-12-31"),
    ("OOS",         "2023-01-01", "2026-12-31"),
]

WEAK_CONFIDENCE_FLOOR = 200


def log(msg):
    print(msg, flush=True)


def cliffs_delta_via_mwu(x, y):
    u1, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    return (2 * u1) / (len(x) * len(y)) - 1


def two_group_test(hi, lo, hi_label, lo_label, test_label):
    log(f"\n{'-'*90}")
    log(f"{test_label}")
    log(f"{'-'*90}")
    n_hi, n_lo = len(hi), len(lo)
    if n_hi < 5 or n_lo < 5:
        log(f"  Too few rows ({hi_label} n={n_hi}, {lo_label} n={n_lo}) — skipped.")
        return None

    flagged = n_hi < WEAK_CONFIDENCE_FLOOR or n_lo < WEAK_CONFIDENCE_FLOOR
    if flagged:
        log(f"  ** FLAG: {hi_label} n={n_hi:,} / {lo_label} n={n_lo:,} — below the "
            f"~{WEAK_CONFIDENCE_FLOOR} Weak-confidence floor. **")

    u_two, p_two = stats.mannwhitneyu(hi, lo, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(hi, lo, alternative="greater")
    t_stat, p_t = stats.ttest_ind(hi, lo, equal_var=False)
    delta = cliffs_delta_via_mwu(hi, lo)
    mean_delta = hi.mean() - lo.mean()

    log(f"\n  {hi_label} (n={n_hi:,}, mean={hi.mean():+.4f}%, median={hi.median():+.4f}%) vs "
        f"{lo_label} (n={n_lo:,}, mean={lo.mean():+.4f}%, median={lo.median():+.4f}%)")
    log(f"  Mean delta (hi minus lo): {mean_delta:+.4f}pp")
    log(f"  MWU two-sided: p = {p_two:.6f}")
    log(f"  MWU one-sided (hi > lo, journal's hypothesized direction): p = {p_one:.6f}")
    log(f"  Welch's t: t = {t_stat:.4f}, p = {p_t:.6f}")
    log(f"  Cliff's delta (hi vs lo): {delta:.4f}")

    return {
        "test": test_label, "n_hi": n_hi, "n_lo": n_lo,
        "hi_mean": hi.mean(), "hi_median": hi.median(),
        "lo_mean": lo.mean(), "lo_median": lo.median(),
        "mean_delta": mean_delta, "mwu_two_p": p_two, "mwu_one_p": p_one,
        "welch_t": t_stat, "welch_p": p_t, "cliffs_delta": delta,
        "insufficient_n_flag": flagged,
    }


def main():
    con = sqlite3.connect(DB)

    # ── Step 1: days-since-transition, recomputed independently from the raw
    # regime label sequence (NOT from the known-buggy regime_days column) ──
    log("=" * 90)
    log("STEP 1: recomputing days-since-transition from market_regime.regime "
        "(independent of the flagged-unreliable regime_days column)")
    log("=" * 90)

    reg = pd.read_sql_query(
        "SELECT date, regime FROM market_regime ORDER BY date ASC", con
    )
    log(f"market_regime: {len(reg):,} rows, {reg['date'].min()} -> {reg['date'].max()}")

    days_since = np.zeros(len(reg), dtype=int)
    for i in range(1, len(reg)):
        if reg["regime"].iat[i] == reg["regime"].iat[i - 1]:
            days_since[i] = days_since[i - 1] + 1
        else:
            days_since[i] = 0
    reg["days_since_transition"] = days_since

    n_transitions = int((reg["days_since_transition"] == 0).sum())
    log(f"Total regime transitions detected (incl. the very first row): {n_transitions:,}")

    tu = reg[reg["regime"] == "TRENDING_UP"]
    log(f"TRENDING_UP rows in market_regime: {len(tu):,}, "
        f"days_since_transition range: {tu['days_since_transition'].min()}-{tu['days_since_transition'].max()}")

    # ── Load liquidity-gated stock_signals population (all regimes, needed
    # for both the transition-age test and the regime-type test) ──
    log("\n" + "=" * 90)
    log("Loading liquidity-gated stock_signals population (avg_vol_10d > "
        f"{LIQUIDITY_GATE:,})")
    log("=" * 90)

    ss = pd.read_sql_query(
        f"SELECT symbol, date, avg_vol_10d FROM stock_signals "
        f"WHERE avg_vol_10d > {LIQUIDITY_GATE} ORDER BY symbol, date", con
    )
    log(f"Liquidity-gated stock_signals rows: {len(ss):,}, "
        f"{ss['symbol'].nunique()} symbols, {ss['date'].min()} -> {ss['date'].max()}")

    symbols = ss["symbol"].unique().tolist()
    placeholders = ",".join("?" for _ in symbols)
    prices = pd.read_sql_query(
        f"SELECT symbol, date, close FROM prices_adjusted "
        f"WHERE symbol IN ({placeholders}) ORDER BY symbol, date",
        con, params=symbols,
    )

    log(f"\nComputing fwd_return_10d fresh from prices_adjusted "
        f"({FWD_WINDOW} trading days forward, close-to-close, per-symbol "
        f"continuous sequence — same formula as compute_forward_returns.py)...")

    by_symbol = {}
    for sym, g in prices.groupby("symbol"):
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "close": g["close"].to_numpy(dtype=float),
        }

    fwd10 = np.full(len(ss), np.nan)
    ss_sym = ss["symbol"].to_numpy()
    ss_date = ss["date"].to_numpy()
    for sym, idx in ss.groupby("symbol").groups.items():
        pf = by_symbol.get(sym)
        if pf is None:
            continue
        dates = pf["dates"]
        close = pf["close"]
        for i in idx:
            d = ss_date[i]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue
            if pos + FWD_WINDOW >= len(dates):
                continue
            c0 = close[pos]
            c10 = close[pos + FWD_WINDOW]
            if c0 == 0 or np.isnan(c0) or np.isnan(c10):
                continue
            fwd10[i] = (c10 - c0) / c0 * 100

    ss["fwd_return_10d"] = fwd10
    ss = ss.merge(reg[["date", "regime", "days_since_transition"]], on="date", how="left")

    valid = ss.dropna(subset=["fwd_return_10d"]).copy()
    log(f"\nRows with valid fwd_return_10d (window closed + price data present): "
        f"{len(valid):,} / {len(ss):,} ({len(valid)/len(ss)*100:.1f}%)")

    # ══════════════════════════════════════════════════════════════════════
    # STEP 2-6: TRENDING_UP transition-age test
    # ══════════════════════════════════════════════════════════════════════
    log("\n\n" + "=" * 90)
    log("STEP 2: Population — stock_signals rows, valid fwd_return_10d, "
        f"avg_vol_10d > {LIQUIDITY_GATE:,}, regime = TRENDING_UP")
    log("=" * 90)

    pop = valid[valid["regime"] == "TRENDING_UP"].copy()
    log(f"Population N = {len(pop):,}, {pop['symbol'].nunique()} symbols, "
        f"date range {pop['date'].min()} -> {pop['date'].max()}")

    log("\n" + "=" * 90)
    log("STEP 3-4: Group split — 0-2 / 3-5 / 6+ days since transition "
        "(transition day itself = 0)")
    log("=" * 90)

    grp_0_2 = pop[pop["days_since_transition"].between(0, 2)]["fwd_return_10d"]
    grp_3_5 = pop[pop["days_since_transition"].between(3, 5)]["fwd_return_10d"]
    grp_6p  = pop[pop["days_since_transition"] >= 6]["fwd_return_10d"]

    for label, g in [("0-2 days", grp_0_2), ("3-5 days", grp_3_5), ("6+ days", grp_6p)]:
        log(f"  {label}: n={len(g):,}, mean={g.mean():+.4f}%, median={g.median():+.4f}%")

    log("\n" + "=" * 90)
    log("STEP 5: Statistical suite, 0-2 days vs 6+ days "
        "(journal's claim: 6+ outperforms 0-2, i.e. hi=6+, lo=0-2)")
    log("=" * 90)

    main_result = two_group_test(grp_6p, grp_0_2, "6+ days", "0-2 days",
                                  "PRIMARY: 6+ days since TRENDING_UP transition vs 0-2 days")

    log("\n" + "=" * 90)
    log("STEP 6: Era consistency (0-2 vs 6+, repeated per era — NOT pooled-only)")
    log("=" * 90)

    era_results = []
    for era_name, start, end in ERAS:
        era_pop = pop[(pop["date"] >= start) & (pop["date"] <= end)]
        e_0_2 = era_pop[era_pop["days_since_transition"].between(0, 2)]["fwd_return_10d"]
        e_3_5 = era_pop[era_pop["days_since_transition"].between(3, 5)]["fwd_return_10d"]
        e_6p  = era_pop[era_pop["days_since_transition"] >= 6]["fwd_return_10d"]
        log(f"\n>>> ERA: {era_name} ({start} -> {end}), n_rows={len(era_pop):,}")
        log(f"    0-2 days: n={len(e_0_2):,}, mean={e_0_2.mean():+.4f}%, median={e_0_2.median():+.4f}%" if len(e_0_2) else "    0-2 days: n=0")
        log(f"    3-5 days: n={len(e_3_5):,}, mean={e_3_5.mean():+.4f}%, median={e_3_5.median():+.4f}%" if len(e_3_5) else "    3-5 days: n=0")
        log(f"    6+ days : n={len(e_6p):,}, mean={e_6p.mean():+.4f}%, median={e_6p.median():+.4f}%" if len(e_6p) else "    6+ days: n=0")
        res = two_group_test(e_6p, e_0_2, "6+ days", "0-2 days", f"ERA: {era_name} — 6+ vs 0-2")
        era_results.append((era_name, res))

    # ══════════════════════════════════════════════════════════════════════
    # STEP 7: Regime-type test (VOLATILE vs others)
    # ══════════════════════════════════════════════════════════════════════
    log("\n\n" + "=" * 90)
    log("STEP 7: Regime-type test — fwd_return_10d by regime "
        "(TRENDING_UP / RANGING / VOLATILE / TRENDING_DOWN), full population")
    log("=" * 90)

    regime_pop = valid[valid["regime"].isin(
        ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"])].copy()
    log(f"Full regime-type population N = {len(regime_pop):,}")

    log("\nFull population, by regime:")
    for rtype in ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]:
        g = regime_pop[regime_pop["regime"] == rtype]["fwd_return_10d"]
        log(f"  {rtype:<15}: n={len(g):,}, mean={g.mean():+.4f}%, median={g.median():+.4f}%")

    log("\nVOLATILE vs TRENDING_UP:")
    vol_g = regime_pop[regime_pop["regime"] == "VOLATILE"]["fwd_return_10d"]
    tu_g = regime_pop[regime_pop["regime"] == "TRENDING_UP"]["fwd_return_10d"]
    ra_g = regime_pop[regime_pop["regime"] == "RANGING"]["fwd_return_10d"]
    td_g = regime_pop[regime_pop["regime"] == "TRENDING_DOWN"]["fwd_return_10d"]
    two_group_test(tu_g, vol_g, "TRENDING_UP", "VOLATILE",
                    "VOLATILE vs TRENDING_UP (journal claim: VOLATILE worse)")
    log("\nVOLATILE vs RANGING:")
    two_group_test(ra_g, vol_g, "RANGING", "VOLATILE",
                    "VOLATILE vs RANGING (journal claim: VOLATILE worse)")

    log("\n" + "=" * 90)
    log("STEP 7 era breakdown — mean/median fwd_return_10d by regime, per era")
    log("=" * 90)

    for era_name, start, end in ERAS:
        era_pop = regime_pop[(regime_pop["date"] >= start) & (regime_pop["date"] <= end)]
        log(f"\n>>> ERA: {era_name} ({start} -> {end}), n_rows={len(era_pop):,}")
        for rtype in ["TRENDING_UP", "RANGING", "VOLATILE", "TRENDING_DOWN"]:
            g = era_pop[era_pop["regime"] == rtype]["fwd_return_10d"]
            if len(g):
                log(f"    {rtype:<15}: n={len(g):,}, mean={g.mean():+.4f}%, median={g.median():+.4f}%")
            else:
                log(f"    {rtype:<15}: n=0")

    con.close()
    log("\n\nDone.")


if __name__ == "__main__":
    main()
