"""
prebreakout_v2_phase4c_velocity_volume.py — PRE_BREAKOUT Phase 4c:
Velocity/Volume Test (ROC + Volume Multiplier).

Tightness (standalone, Section 5, and sector-conditioned, Section 10) is
closed dead/reversed. This tests a different construct: rate-of-change
(velocity) leading into the PRE_BREAKOUT window, combined with a volume
expansion gate — motivated by BREAKOUT V1's H-005 (Volume Expansion Ratio),
this project's strongest individual factor result before decaying to null
at OOS (Cliff's delta 0.0690 Dev -> 0.0445 Val -> -0.0037 OOS).

READ access: pre_breakout_v2_staging_full, prices_adjusted, stock_signals.
WRITE access: none. Read-only, no production writes.

Variable definitions:
  ROC_5  = (close_t - close_t-5) / close_t-5 * 100    (5 TRADING days back,
  ROC_10 = (close_t - close_t-10) / close_t-10 * 100   position-based lookup
                                                        against each symbol's
                                                        full continuous
                                                        prices_adjusted
                                                        history -- NOT the
                                                        gapped PRE_BREAKOUT
                                                        staging table -- same
                                                        discipline as Section
                                                        2.1's already_broken
                                                        derivation correction)

  vol_multiplier = avg_vol_10d / avg_vol_20d
    avg_vol_10d: reused verbatim from stock_signals (existing column, strict
      all-non-null-nonzero 10-day window per _compute_bt_vc).
    avg_vol_20d: NO stored column exists in stock_signals for this. Checked
      before inventing anything new -- an established convention for
      avg_vol_20d already exists identically in backtest_recovery_bases.py
      and backtest_recovery_sim.py: `volumes[max(0, t-19):t+1].mean()`, a
      simple trailing 20-trading-day mean (today inclusive), reused verbatim
      here. This is deliberately NOT stock_signals.vol_contraction (which is
      a 10d/50d ratio with a stricter no-null/no-zero exclusion rule) --
      vol_contraction is a different, non-equivalent construct (50-day, not
      20-day, denominator) and using it would silently substitute a
      different variable than the one this task specifies.

Statistical suite (MWU 2-sided/1-sided, Welch's t, Cliff's delta) reused
verbatim from prebreakout_v2_rebuild_and_test.py's quartile_test(), extended
with a two-group (above/below threshold) variant for the volume-multiplier
and combined tests.

Bonferroni correction per Decision D-001 (Decisions.md): this task runs a
family of 6 primary variable/threshold combinations (ROC_5 quartile, ROC_10
quartile, vol_multiplier>1.5x, vol_multiplier>2.0x, combined ROC10+vol>1.5x,
combined ROC10+vol>2.0x) -- alpha_adjusted = 0.05 / 6 = 0.008333, reported
alongside every raw p-value, not only on request.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import research_db  # opt-in Postgres path — DATABASE_URL/SUPABASE_DB_URL env
                     # var set -> Supabase; unset -> local SQLite, unchanged.

DB = str(Path(__file__).parent / "psx_data.db")
POP_TABLE = "pre_breakout_v2_staging_full"

ERAS = [
    ("Development", "2015-01-01", "2019-12-31"),
    ("Validation",  "2020-01-01", "2022-12-31"),
    ("OOS",         "2023-01-01", "2026-12-31"),
]

# NOTE: vol_multiplier = avg_vol_10d / avg_vol_20d has a hard mathematical
# ceiling approaching 2.0 (never reaching it) because the numerator's 10-day
# window is NESTED inside the denominator's 20-day window, sharing the same
# end date: avg_vol_20d is a weighted blend of the same 10-day window used
# for avg_vol_10d and the preceding 10 days, so the ratio can only approach
# 2.0x as the preceding window's volume goes to zero -- it structurally
# cannot exceed it. Confirmed empirically below (observed max ~1.999). This
# means the "2.0x" threshold candidate specified in the task is structurally
# unreachable, not merely rare -- 0 rows will ever clear it, in any era. The
# real primary-test family is therefore 4 tests (ROC_5 quartile, ROC_10
# quartile, vol_multiplier@1.5x, combined ROC10-Q4+vol>1.5x), not 6 --
# the 2.0x variants never execute a comparison at all, so they are excluded
# from the Bonferroni family denominator rather than counted as "tested and
# failed."
N_PRIMARY_TESTS = 4
ALPHA = 0.05
ALPHA_ADJ = ALPHA / N_PRIMARY_TESTS

WEAK_CONFIDENCE_FLOOR = 200


def log(msg):
    print(msg, flush=True)


# ══════════════════════════════════════════════════════════════════════════
# Load population + full continuous price history (for ROC + avg_vol_20d)
# ══════════════════════════════════════════════════════════════════════════

def load_population(con):
    return research_db.read_sql(
        f"SELECT symbol, date, fwd_return_10d FROM {POP_TABLE} ORDER BY symbol, date", con
    )


def load_prices_full(con, symbols):
    q = """
        SELECT symbol, date, close, volume FROM prices_adjusted
        WHERE symbol IN ({})
        ORDER BY symbol, date
    """.format(",".join("?" for _ in symbols))
    df = research_db.read_sql(q, con, params=symbols)
    by_symbol = {}
    for sym, g in df.groupby("symbol"):
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "close": g["close"].to_numpy(dtype=float),
            "volume": g["volume"].to_numpy(dtype=float),
        }
    return by_symbol


def load_avg_vol_10d(con):
    return research_db.read_sql(
        "SELECT symbol, date, avg_vol_10d FROM stock_signals ORDER BY symbol, date", con
    )


def compute_row_features(pop, prices_full):
    n = len(pop)
    roc5 = np.full(n, np.nan)
    roc10 = np.full(n, np.nan)
    vol20 = np.full(n, np.nan)

    for sym, idx in pop.groupby("symbol").groups.items():
        pf = prices_full.get(sym)
        if pf is None:
            continue
        dates = pf["dates"]
        close = pf["close"]
        volume = pf["volume"]
        for i in idx:
            d = pop.at[i, "date"]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue

            if pos >= 5:
                c0 = close[pos - 5]
                if c0 and not np.isnan(c0) and c0 != 0:
                    roc5[i] = (close[pos] - c0) / c0 * 100

            if pos >= 10:
                c0 = close[pos - 10]
                if c0 and not np.isnan(c0) and c0 != 0:
                    roc10[i] = (close[pos] - c0) / c0 * 100

            # avg_vol_20d: trailing 20-trading-day mean, today inclusive,
            # convention reused verbatim from backtest_recovery_bases.py /
            # backtest_recovery_sim.py.
            window = volume[max(0, pos - 19): pos + 1]
            window = window[~np.isnan(window)]
            if len(window) > 0:
                vol20[i] = window.mean()

    pop = pop.copy()
    pop["roc_5"] = roc5
    pop["roc_10"] = roc10
    pop["avg_vol_20d"] = vol20
    return pop


# ══════════════════════════════════════════════════════════════════════════
# Statistical suite
# ══════════════════════════════════════════════════════════════════════════

def cliffs_delta_via_mwu(x, y):
    u1, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    return (2 * u1) / (len(x) * len(y)) - 1


def two_group_test(hi, lo, hi_label, lo_label, test_label, alpha_adj=ALPHA_ADJ):
    """hi is hypothesized to have HIGHER fwd_return_10d than lo (one-sided direction)."""
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
            f"~{WEAK_CONFIDENCE_FLOOR} Weak-confidence floor. Reporting but flagging "
            f"as insufficient-N. **")

    u_two, p_two = stats.mannwhitneyu(hi, lo, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(hi, lo, alternative="greater")
    t_stat, p_t = stats.ttest_ind(hi, lo, equal_var=False)
    delta = cliffs_delta_via_mwu(hi, lo)
    mean_delta = hi.mean() - lo.mean()

    survives = p_one < alpha_adj
    log(f"\n  {hi_label} (n={n_hi:,}, mean={hi.mean():+.4f}%, median={hi.median():+.4f}%) vs "
        f"{lo_label} (n={n_lo:,}, mean={lo.mean():+.4f}%, median={lo.median():+.4f}%)")
    log(f"  Mean delta (hi minus lo): {mean_delta:+.4f}pp")
    log(f"  MWU two-sided: p = {p_two:.6f}")
    log(f"  MWU one-sided (hi > lo, hypothesized direction): p = {p_one:.6f}")
    log(f"  Welch's t: t = {t_stat:.4f}, p = {p_t:.6f}")
    log(f"  Cliff's delta (hi vs lo): {delta:.4f}")
    log(f"  Survives Bonferroni-corrected alpha={alpha_adj:.6f} (one-sided)? {'YES' if survives else 'no'}")

    return {
        "test": test_label, "n_hi": n_hi, "n_lo": n_lo,
        "hi_mean": hi.mean(), "hi_median": hi.median(),
        "lo_mean": lo.mean(), "lo_median": lo.median(),
        "mean_delta": mean_delta, "mwu_two_p": p_two, "mwu_one_p": p_one,
        "t_stat": t_stat, "t_p": p_t, "cliffs_delta": delta,
        "insufficient_n_flag": flagged, "survives_bonferroni": survives,
    }


def quartile_extremes(s, col):
    """Return (top25, bottom25) Series of fwd_return_10d for a column's
    top/bottom quartile by value."""
    s = s.dropna(subset=[col, "fwd_return_10d"])
    if len(s) < 40:
        return None, None, 0
    q = pd.qcut(s[col], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
    if len(q.cat.categories) < 4:
        return None, None, len(s)
    top = s[q == "Q4"]["fwd_return_10d"]
    bot = s[q == "Q1"]["fwd_return_10d"]
    return top, bot, len(s)


def run_family(pop, era_label):
    """Run the 6-test primary family on a given (sub)population, return list
    of result dicts."""
    results = []

    # 3a. ROC_5 quartile (top vs bottom)
    top, bot, n = quartile_extremes(pop, "roc_5")
    if top is not None:
        r = two_group_test(top, bot, "ROC_5 Q4 (fastest)", "ROC_5 Q1 (slowest)",
                            f"[{era_label}] ROC_5 quartile (n={n:,})")
        if r:
            r["family"] = "ROC_5 quartile"
            results.append(r)
    else:
        log(f"\n[{era_label}] ROC_5 quartile — insufficient rows/degenerate bins (n={n:,}), skipped.")

    # 3b. ROC_10 quartile
    top, bot, n = quartile_extremes(pop, "roc_10")
    if top is not None:
        r = two_group_test(top, bot, "ROC_10 Q4 (fastest)", "ROC_10 Q1 (slowest)",
                            f"[{era_label}] ROC_10 quartile (n={n:,})")
        if r:
            r["family"] = "ROC_10 quartile"
            results.append(r)
    else:
        log(f"\n[{era_label}] ROC_10 quartile — insufficient rows/degenerate bins (n={n:,}), skipped.")

    # 3c. Volume multiplier thresholds. 2.0x is structurally unreachable
    # (see module docstring/N_PRIMARY_TESTS note) -- report it as such, do
    # not run a test that can never have any rows above threshold.
    for thresh in (1.5, 2.0):
        s = pop.dropna(subset=["vol_multiplier", "fwd_return_10d"])
        n_above = (s["vol_multiplier"] > thresh).sum()
        if thresh == 2.0 and n_above == 0:
            log(f"\n[{era_label}] Volume multiplier @ 2.0x — STRUCTURALLY UNREACHABLE "
                f"(0 rows above threshold; max observed vol_multiplier={s['vol_multiplier'].max():.4f} "
                f"< 2.0 by construction, see docstring). Not counted as a test.")
            continue
        hi = s[s["vol_multiplier"] > thresh]["fwd_return_10d"]
        lo = s[s["vol_multiplier"] <= thresh]["fwd_return_10d"]
        r = two_group_test(hi, lo, f"vol_multiplier>{thresh}x", f"vol_multiplier<={thresh}x",
                            f"[{era_label}] Volume multiplier @ {thresh}x (n={len(s):,})")
        if r:
            r["family"] = f"vol_multiplier@{thresh}x"
            results.append(r)

    # 3d. Combined: ROC_10 top quartile AND vol_multiplier > threshold vs rest
    s = pop.dropna(subset=["roc_10", "vol_multiplier", "fwd_return_10d"])
    if len(s) >= 40:
        q = pd.qcut(s["roc_10"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        roc10_top = q == "Q4"
        for thresh in (1.5, 2.0):
            combo_mask = roc10_top & (s["vol_multiplier"] > thresh)
            if thresh == 2.0 and combo_mask.sum() == 0:
                log(f"\n[{era_label}] Combined ROC_10-Q4 + vol>2.0x — STRUCTURALLY UNREACHABLE "
                    f"(vol_multiplier can never exceed 2.0x, see docstring). Not counted as a test.")
                continue
            rest_mask = ~combo_mask
            hi = s[combo_mask]["fwd_return_10d"]
            lo = s[rest_mask]["fwd_return_10d"]
            r = two_group_test(hi, lo, f"ROC10-Q4 & vol>{thresh}x", "rest of population",
                                f"[{era_label}] Combined ROC_10-Q4 + vol>{thresh}x (n={len(s):,})")
            if r:
                r["family"] = f"combined_vol@{thresh}x"
                results.append(r)
    else:
        log(f"\n[{era_label}] Combined ROC_10+volume — insufficient rows (n={len(s):,}), skipped.")

    return results


def main():
    con = research_db.get_connection(DB)
    try:
        log("=" * 100)
        log("PRE_BREAKOUT Phase 4c — Velocity/Volume Test (ROC + Volume Multiplier)")
        log("=" * 100)

        pop = load_population(con)
        n_full = len(pop)
        log(f"\nLoaded {POP_TABLE}: {n_full:,} rows")

        symbols = pop["symbol"].unique().tolist()
        log(f"Loading full continuous prices_adjusted history for {len(symbols)} symbols...")
        prices_full = load_prices_full(con, symbols)

        log("Computing ROC_5, ROC_10, avg_vol_20d (position-based lookup against full history)...")
        pop = compute_row_features(pop, prices_full)

        log("Joining avg_vol_10d from stock_signals (existing column)...")
        avg10 = load_avg_vol_10d(con)
        pop = pop.merge(avg10, on=["symbol", "date"], how="left")

        pop["vol_multiplier"] = pop["avg_vol_10d"] / pop["avg_vol_20d"]
        pop.loc[(pop["avg_vol_20d"].isna()) | (pop["avg_vol_20d"] == 0), "vol_multiplier"] = np.nan

        for col in ["roc_5", "roc_10", "avg_vol_10d", "avg_vol_20d", "vol_multiplier"]:
            nn = pop[col].notna().sum()
            log(f"  {col}: {nn:,} / {n_full:,} non-null ({nn/n_full*100:.1f}%)")

        vm_max = pop["vol_multiplier"].max()
        log(f"\n  ** vol_multiplier max observed = {vm_max:.6f} **")
        log(f"  Structural note: avg_vol_10d's 10-day window is nested inside avg_vol_20d's "
            f"20-day window (same end date), so avg_vol_20d = (10*avg_vol_10d + "
            f"k*avg_vol_prior10)/(10+k) for k<=10 valid prior-window days. As the preceding "
            f"10-day volume approaches zero, vol_multiplier approaches but cannot reach or "
            f"exceed 2.0x — this is a mathematical ceiling of the ratio's own construction, "
            f"not a data-quality issue. The observed max ({vm_max:.4f}) is consistent with "
            f"this derivation. The task's 2.0x threshold candidate is therefore structurally "
            f"unreachable and is excluded from the primary-test family below (real family "
            f"size = {N_PRIMARY_TESTS}, not the naively-counted 6).")

        # ── Descriptive stats ──
        log("\n" + "=" * 100)
        log("DESCRIPTIVE STATISTICS (full population)")
        log("=" * 100)
        desc = pop[["roc_5", "roc_10", "vol_multiplier"]].describe(
            percentiles=[0.25, 0.5, 0.75]
        )
        log(desc.to_string())

        # ── Primary tests: pooled (all eras) ──
        log("\n" + "=" * 100)
        log(f"PRIMARY TEST FAMILY — pooled, all eras (n_tests={N_PRIMARY_TESTS}, "
            f"Bonferroni alpha_adj = {ALPHA} / {N_PRIMARY_TESTS} = {ALPHA_ADJ:.6f})")
        log("=" * 100)
        pooled_results = run_family(pop, "ALL ERAS")

        # ── Era consistency ──
        log("\n" + "=" * 100)
        log("ERA CONSISTENCY — same 6-test family repeated per era")
        log("=" * 100)
        era_results = []
        for era_name, start, end in ERAS:
            era_sub = pop[(pop["date"] >= start) & (pop["date"] <= end)]
            log(f"\n{'#'*100}")
            log(f"ERA: {era_name} ({start} -> {end}), n_rows={len(era_sub):,}")
            log(f"{'#'*100}")
            era_results.extend(run_family(era_sub, era_name))

        # ── Bonferroni summary ──
        log("\n" + "=" * 100)
        log("BONFERRONI-CORRECTED VERDICT SUMMARY (pooled, all-eras family)")
        log("=" * 100)
        log(f"Family size: {N_PRIMARY_TESTS} tests. Uncorrected alpha=0.05. "
            f"Bonferroni-adjusted alpha = {ALPHA_ADJ:.6f} (one-sided).")
        for r in pooled_results:
            uncorrected_sig = "significant" if r["mwu_one_p"] < ALPHA else "n.s."
            corrected_sig = "SURVIVES" if r["survives_bonferroni"] else "does not survive"
            log(f"  {r['test']:<55} p(one-sided)={r['mwu_one_p']:.6f}  "
                f"uncorrected@0.05={uncorrected_sig:<11}  bonferroni@{ALPHA_ADJ:.4f}={corrected_sig}")

        all_results = pooled_results + era_results
        results_df = pd.DataFrame(all_results)
        out_csv = Path(__file__).parent / "prebreakout_v2_phase4c_results.csv"
        results_df.to_csv(out_csv, index=False)
        log(f"\nResults saved to {out_csv.name} ({len(results_df)} rows).")

    finally:
        con.close()


if __name__ == "__main__":
    main()
