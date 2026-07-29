"""
prebreakout_v2_phase4b_conditional_tightness.py — PRE_BREAKOUT Phase 4b:
Conditional Tightness Test.

Tests whether pct_rank_252 (the measure recommended in the closed standalone
tightness test) predicts fwd_return_10d WITHIN the population already
pre-qualified by sec_global_rank <= 8 (the validated, live sector-strength
gate used in weinstein_combined_backtest.py), rather than as a standalone
filter on the full PRE_BREAKOUT population again.

READ access: pre_breakout_v2_staging_full, sectors, sector_signals.
WRITE access: none (no production writes, no live-system changes).

Join logic for sec_global_rank reused verbatim from
weinstein_combined_backtest.py: sectors (symbol -> sector), then
sector_signals (date, sector) -> rs_rank AS sec_global_rank.

Statistical suite (MWU one/two-sided, Welch's t, Cliff's delta) reused
verbatim from prebreakout_v2_rebuild_and_test.py's quartile_test().
Era boundaries reused verbatim from the same script.
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
SEC_RANK_GATE = 8
MEASURE = "pct_rank_252"
TIGHT_IS_LOW = True  # tight = LOW percentile rank

ERAS = [
    ("Development", "2015-01-01", "2019-12-31"),
    ("Validation",  "2020-01-01", "2022-12-31"),
    ("OOS",         "2023-01-01", "2026-12-31"),
]

WEAK_CONFIDENCE_FLOOR = 200  # per-group minimum before flagging insufficient N


def log(msg):
    print(msg, flush=True)


def load_population(con):
    return research_db.read_sql(
        f"SELECT symbol, date, {MEASURE}, fwd_return_10d FROM {POP_TABLE} ORDER BY symbol, date",
        con,
    )


def load_sector_rank(con):
    """Reused verbatim join logic from weinstein_combined_backtest.py:
    sectors (symbol->sector) LEFT JOIN sector_signals (date, sector) -> rs_rank."""
    return research_db.read_sql(
        """
        SELECT p.symbol, p.date, sec.rs_rank AS sec_global_rank
        FROM (SELECT DISTINCT symbol, date FROM %s) p
        JOIN sectors s ON p.symbol = s.symbol
        LEFT JOIN sector_signals sec ON sec.date = p.date AND sec.sector = s.sector
        """ % POP_TABLE,
        con,
    )


def cliffs_delta_via_mwu(x, y):
    u1, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    return (2 * u1) / (len(x) * len(y)) - 1


def quartile_test(sub, col, tight_is_low, label):
    s = sub.dropna(subset=[col, "fwd_return_10d"]).copy()
    n = len(s)
    log(f"\n{'-'*90}")
    log(f"{label} — {col} (n={n:,})")
    log(f"{'-'*90}")
    if n < 40:
        log("  Too few rows for a reliable quartile split.")
        return None

    s["quartile"], bins = pd.qcut(s[col], 4, labels=["Q1", "Q2", "Q3", "Q4"], retbins=True, duplicates="drop")
    if len(bins) - 1 < 4:
        log(f"  NOTE: collapsed to {len(bins)-1} groups (duplicate bin edges).")

    rep = s.groupby("quartile", observed=True)["fwd_return_10d"].agg(["count", "mean", "median", "std"])
    log(rep.to_string())

    tight_label = "Q1" if tight_is_low else "Q4"
    loose_label = "Q4" if tight_is_low else "Q1"
    if tight_label not in s["quartile"].cat.categories or loose_label not in s["quartile"].cat.categories:
        log("  Cannot form tight-vs-loose comparison (missing quartile).")
        return None

    tight = s[s["quartile"] == tight_label]["fwd_return_10d"]
    loose = s[s["quartile"] == loose_label]["fwd_return_10d"]
    if len(tight) < 5 or len(loose) < 5:
        log("  Too few rows in tight/loose group.")
        return None

    flagged = False
    if len(tight) < WEAK_CONFIDENCE_FLOOR or len(loose) < WEAK_CONFIDENCE_FLOOR:
        flagged = True
        log(f"  ** FLAG: tight n={len(tight):,} / loose n={len(loose):,} — below the "
            f"~{WEAK_CONFIDENCE_FLOOR} Weak-confidence floor used elsewhere in this project. "
            f"Reporting numbers below but flagging as insufficient-N, not a trustworthy result. **")

    u_two, p_two = stats.mannwhitneyu(tight, loose, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(tight, loose, alternative="greater")  # tight > loose = "tighter is better"
    t_stat, p_t = stats.ttest_ind(tight, loose, equal_var=False)
    delta = cliffs_delta_via_mwu(tight, loose)
    mean_delta = tight.mean() - loose.mean()

    log(f"\n  TIGHT ({tight_label}, n={len(tight):,}, mean={tight.mean():+.4f}%, median={tight.median():+.4f}%) "
        f"vs LOOSE ({loose_label}, n={len(loose):,}, mean={loose.mean():+.4f}%, median={loose.median():+.4f}%)")
    log(f"  Mean delta (tight minus loose): {mean_delta:+.4f}pp")
    log(f"  MWU two-sided: p = {p_two:.6f}")
    log(f"  MWU one-sided (tight > loose, 'tighter is better'): p = {p_one:.6f}")
    log(f"  Welch's t (tight vs loose): t = {t_stat:.4f}, p = {p_t:.6f}")
    log(f"  Cliff's delta (tight vs loose): {delta:.4f}")

    return {
        "measure": col, "era": label, "n": n,
        "tight_n": len(tight), "tight_mean": tight.mean(), "tight_median": tight.median(),
        "loose_n": len(loose), "loose_mean": loose.mean(), "loose_median": loose.median(),
        "mean_delta": mean_delta, "mwu_two_p": p_two, "mwu_one_p": p_one,
        "t_stat": t_stat, "t_p": p_t, "cliffs_delta": delta,
        "insufficient_n_flag": flagged,
    }


def main():
    con = research_db.get_connection(DB)
    try:
        log("=" * 100)
        log("PRE_BREAKOUT Phase 4b — Conditional Tightness Test (sec_global_rank <= %d)" % SEC_RANK_GATE)
        log("=" * 100)

        pop = load_population(con)
        n_full = len(pop)
        log(f"\nLoaded {POP_TABLE}: {n_full:,} rows")

        sec = load_sector_rank(con)
        log(f"Sector-rank join rows: {len(sec):,} (distinct symbol/date pairs)")

        pop = pop.merge(sec, on=["symbol", "date"], how="left")
        n_rank_null = pop["sec_global_rank"].isna().sum()
        log(f"sec_global_rank NULL after join (no sector_signals row for that date/sector): "
            f"{n_rank_null:,} ({n_rank_null/n_full*100:.2f}%)")

        cond = pop[pop["sec_global_rank"].notna() & (pop["sec_global_rank"] <= SEC_RANK_GATE)].copy()
        n_cond = len(cond)
        log(f"\n--- Conditioning result ---")
        log(f"Full population:                 {n_full:,} rows")
        log(f"Conditioned (sec_global_rank<={SEC_RANK_GATE}): {n_cond:,} rows "
            f"({n_cond/n_full*100:.2f}% retained)")

        log("\n" + "=" * 100)
        log(f"CONDITIONED POPULATION — {MEASURE} quartile test (all eras combined)")
        log("=" * 100)
        full_result = quartile_test(cond, MEASURE, TIGHT_IS_LOW, "CONDITIONED (sec_global_rank<=8), all eras")

        log("\n" + "=" * 100)
        log("ERA CONSISTENCY — conditioned population")
        log("=" * 100)
        era_results = []
        for era_name, start, end in ERAS:
            era_sub = cond[(cond["date"] >= start) & (cond["date"] <= end)]
            r = quartile_test(era_sub, MEASURE, TIGHT_IS_LOW, f"{era_name} ({start} -> {end}), conditioned")
            if r:
                era_results.append(r)

        results = ([full_result] if full_result else []) + era_results
        results_df = pd.DataFrame(results)
        out_csv = Path(__file__).parent / "prebreakout_v2_phase4b_results.csv"
        results_df.to_csv(out_csv, index=False)
        log(f"\nResults saved to {out_csv.name} ({len(results_df)} rows).")

        # Direct comparison vs unconditioned baseline (from PRE_BREAKOUT_Specification_v1.0.md Section 5.1)
        BASELINE_MEAN_DELTA = -1.138
        log("\n" + "=" * 100)
        log("COMPARISON — conditioned vs unconditioned baseline")
        log("=" * 100)
        if full_result:
            log(f"  Unconditioned (full population, pct_rank_252): mean delta = {BASELINE_MEAN_DELTA:+.3f}pp "
                f"(tight underperforms loose)")
            log(f"  Conditioned   (sec_global_rank<=8, pct_rank_252): mean delta = {full_result['mean_delta']:+.3f}pp")
            diff = full_result["mean_delta"] - BASELINE_MEAN_DELTA
            if full_result["mean_delta"] < 0 and BASELINE_MEAN_DELTA < 0:
                if abs(full_result["mean_delta"]) > abs(BASELINE_MEAN_DELTA):
                    verdict = "STRENGTHENED (same direction, larger magnitude)"
                elif abs(full_result["mean_delta"]) < abs(BASELINE_MEAN_DELTA):
                    verdict = "WEAKENED (same direction, smaller magnitude)"
                else:
                    verdict = "UNCHANGED (same direction, same magnitude)"
            elif full_result["mean_delta"] > 0 and BASELINE_MEAN_DELTA < 0:
                verdict = "REVERSED (direction flipped: tight now outperforms loose)"
            else:
                verdict = "AMBIGUOUS"
            log(f"  Delta-of-deltas: {diff:+.3f}pp")
            log(f"  Verdict: {verdict}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
