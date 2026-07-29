"""
prebreakout_v2_phase6_regime_conditional.py — PRE_BREAKOUT Phase 6
(EXPLORATORY) — Regime-Conditional Re-Test of Dead Constructs Inside vs.
Outside a "Runaway Bull" Filter.

*** EXPLORATORY ONLY. Both clean eras (Development for exploration,
Validation+OOS for confirmation) have already been spent this session on
these exact constructs. No fresh held-out data remains. This script uses the
FULL 2015-2026 dataset, per explicit task instruction, since no confirmatory
claim is being made here — this is forensic/diagnostic re-slicing of already-
tested, already-closed findings, not a new confirmatory test. ***

STEP 1: RUNAWAY_BULL_THRESHOLD is derived ONCE from the 2015-2022 (Development
+Validation) portion of KSE-100's trailing-252-day return distribution (90th
percentile), then applied blindly forward across the full 2015-2026 dataset.
Not adjusted after seeing Step 2's results.

STEP 2: three already-closed/dead constructs are re-tested, split by
runaway-bull day status:
  (a) Stealth RS >=2 vs stealth=0 (Section 12 locked definition)
  (b) tightness pct_rank_252, Q1 (tight) vs Q4 (loose) (Section 9/10 definition)
  (c) ROC_10, Q4 (fast) vs Q1 (slow) (Section 11 definition)

Primary metric for this re-test: right-tail hit rate P(fwd_return_10d>+10%),
per task instruction (overrides each construct's original primary metric,
for consistency across this specific investigation). Cliff's delta and MWU
reported as secondary.

READ access: pre_breakout_v2_staging_full, index_prices, prices_adjusted,
stock_signals, market_regime. WRITE access: none.
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

DEV_VAL_END = "2022-12-31"   # 2015-2022 portion used to derive the threshold
ADVERSE_THRESH = -1.5        # locked, Section 12 definition
STEALTH_WINDOW = 20          # locked, Section 12 definition
RIGHT_TAIL_THRESHOLD = 10.0
WEAK_CONFIDENCE_FLOOR = 200


def log(msg):
    print(msg, flush=True)


# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — define RUNAWAY_BULL_THRESHOLD from 2015-2022 only
# ══════════════════════════════════════════════════════════════════════════

def load_index_full(con):
    return research_db.read_sql(
        "SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con
    )


def compute_trailing_252d_return(idx_df):
    idx_df = idx_df.copy()
    close = idx_df["close"].to_numpy(dtype=float)
    n = len(close)
    trailing = np.full(n, np.nan)
    for i in range(252, n):
        c0 = close[i - 252]
        if c0 and not np.isnan(c0) and c0 != 0:
            trailing[i] = (close[i] - c0) / c0 * 100
    idx_df["trailing_252d_ret"] = trailing
    return idx_df


def step1_define_threshold(con):
    log("\n" + "=" * 100)
    log("STEP 1 — Define RUNAWAY_BULL_THRESHOLD from 2015-2022 (Development+Validation) ONLY")
    log("=" * 100)

    idx_df = load_index_full(con)
    idx_df = compute_trailing_252d_return(idx_df)

    dev_val = idx_df[(idx_df["date"] >= "2015-01-01") & (idx_df["date"] <= DEV_VAL_END)]
    dev_val_valid = dev_val["trailing_252d_ret"].dropna()
    log(f"\n2015-2022 trailing-252d return distribution (N={len(dev_val_valid):,} valid days):")
    pctiles = dev_val_valid.quantile([0.50, 0.75, 0.90, 0.95])
    log(pctiles.to_string())

    threshold = dev_val_valid.quantile(0.90)
    log(f"\nRUNAWAY_BULL_THRESHOLD (90th percentile of 2015-2022 trailing-252d return) = "
        f"{threshold:.4f}%  — FIXED, will not be adjusted after Step 2.")

    # join regime
    regime_df = research_db.read_sql(
        "SELECT date, regime FROM market_regime WHERE regime != 'INSUFFICIENT_DATA' ORDER BY date", con
    )
    idx_df = idx_df.merge(regime_df, on="date", how="left")
    idx_df["runaway_bull"] = (idx_df["regime"] == "TRENDING_UP") & (idx_df["trailing_252d_ret"] > threshold)

    idx_df["year"] = idx_df["date"].str[:4].astype(int)
    full_range = idx_df[(idx_df["year"] >= 2015) & (idx_df["year"] <= 2026)]
    by_year = full_range.groupby("year")["runaway_bull"].mean() * 100
    log("\nRunaway-bull day %, by year (2015-2026):")
    log(by_year.round(1).to_string())

    pre2023 = by_year[by_year.index < 2023].mean()
    post2023 = by_year[(by_year.index >= 2023) & (by_year.index <= 2025)].mean()
    log(f"\n2015-2022 avg: {pre2023:.1f}%  |  2023-2025 avg (excl. partial 2026): {post2023:.1f}%")
    log("Sanity check: does 2023-2025 concentrate most runaway-bull days relative to 2015-2022?")
    log(f"  {'YES' if post2023 > pre2023 * 1.5 else ('MODEST' if post2023 > pre2023 else 'NO')} "
        f"— {post2023:.1f}% vs {pre2023:.1f}%")

    runaway_dates = set(idx_df.loc[idx_df["runaway_bull"], "date"].tolist())
    log(f"\nTotal runaway-bull dates identified (full 2015-2026 history): {len(runaway_dates):,}")
    return threshold, runaway_dates, by_year


# ══════════════════════════════════════════════════════════════════════════
# Load population + features (full 2015-2026, no era restriction — exploratory)
# ══════════════════════════════════════════════════════════════════════════

def load_population(con):
    return research_db.read_sql(
        f"SELECT symbol, date, bbw_pct, pct_rank_252, fwd_return_10d FROM {POP_TABLE} ORDER BY symbol, date",
        con,
    )


def load_prices_full(con, symbols):
    q = """
        SELECT symbol, date, close, volume FROM prices_adjusted
        WHERE symbol IN ({}) ORDER BY symbol, date
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


def load_stock_signals_full(con, symbols):
    q = """
        SELECT symbol, date, avg_vol_10d FROM stock_signals
        WHERE symbol IN ({}) ORDER BY symbol, date
    """.format(",".join("?" for _ in symbols))
    df = research_db.read_sql(q, con, params=symbols)
    by_symbol = {}
    for sym, g in df.groupby("symbol"):
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "avg_vol_10d": g["avg_vol_10d"].to_numpy(dtype=float),
        }
    return by_symbol


def compute_roc10(pop, prices_full):
    n = len(pop)
    roc10 = np.full(n, np.nan)
    for sym, idx in pop.groupby("symbol").groups.items():
        pf = prices_full.get(sym)
        if pf is None:
            continue
        dates = pf["dates"]
        close = pf["close"]
        for i in idx:
            d = pop.at[i, "date"]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue
            if pos >= 10:
                c0 = close[pos - 10]
                if c0 and not np.isnan(c0) and c0 != 0:
                    roc10[i] = (close[pos] - c0) / c0 * 100
    pop = pop.copy()
    pop["roc_10"] = roc10
    return pop


def compute_stealth_counts(pop, prices_full, ss_full, adverse_days_set, window=STEALTH_WINDOW):
    n = len(pop)
    n_stealth = np.full(n, 0, dtype=np.int64)
    has_data = np.full(n, False)
    for sym, idx in pop.groupby("symbol").groups.items():
        pf = prices_full.get(sym)
        sf = ss_full.get(sym)
        if pf is None or sf is None:
            continue
        dates = pf["dates"]
        close = pf["close"]
        stock_ret = np.full(len(dates), np.nan)
        stock_ret[1:] = (close[1:] - close[:-1]) / close[:-1] * 100

        ss_dates = sf["dates"]
        ss_avgvol = sf["avg_vol_10d"]
        ss_date_to_idx = {d: i for i, d in enumerate(ss_dates)}

        for i in idx:
            d = pop.at[i, "date"]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue
            lo = max(0, pos - window + 1)
            has_data[i] = True
            cnt = 0
            for p in range(lo, pos + 1):
                dt = dates[p]
                if dt not in adverse_days_set:
                    continue
                r = stock_ret[p]
                if r is None or np.isnan(r) or r < 0:
                    continue
                ssi = ss_date_to_idx.get(dt)
                if ssi is None:
                    continue
                av = ss_avgvol[ssi]
                if av is None or np.isnan(av):
                    continue
                cnt += 1
            n_stealth[i] = cnt
    pop = pop.copy()
    pop["n_stealth_in_window"] = n_stealth
    pop["has_data_stealth"] = has_data
    return pop


# ══════════════════════════════════════════════════════════════════════════
# Statistical suite
# ══════════════════════════════════════════════════════════════════════════

def two_group_stats(hi, lo, hi_label, lo_label, thresh=RIGHT_TAIL_THRESHOLD):
    n_hi, n_lo = len(hi), len(lo)
    if n_hi < 5 or n_lo < 5:
        log(f"    Too few rows ({hi_label} n={n_hi}, {lo_label} n={n_lo}).")
        return None
    flagged = n_hi < WEAK_CONFIDENCE_FLOOR or n_lo < WEAK_CONFIDENCE_FLOOR
    u_two, p_two = stats.mannwhitneyu(hi, lo, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(hi, lo, alternative="greater")
    delta = (2 * u_two) / (n_hi * n_lo) - 1
    hit_hi = (hi > thresh).mean() * 100
    hit_lo = (lo > thresh).mean() * 100
    flag_str = "  ** BELOW WEAK-CONFIDENCE FLOOR (~200-500) **" if flagged else ""
    log(f"    {hi_label}: n={n_hi:,}, hit_rate={hit_hi:.2f}%{flag_str if n_hi < WEAK_CONFIDENCE_FLOOR else ''}")
    log(f"    {lo_label}: n={n_lo:,}, hit_rate={hit_lo:.2f}%{flag_str if n_lo < WEAK_CONFIDENCE_FLOOR else ''}")
    log(f"    Hit-rate delta: {hit_hi - hit_lo:+.2f}pp  |  Cliff's delta={delta:.4f}  |  "
        f"MWU one-sided(hi>lo) p={p_one:.6f}  |  MWU two-sided p={p_two:.6f}")
    return {
        "n_hi": n_hi, "n_lo": n_lo, "hit_hi": hit_hi, "hit_lo": hit_lo,
        "hit_delta": hit_hi - hit_lo, "cliffs_delta": delta,
        "mwu_one_p": p_one, "mwu_two_p": p_two, "insufficient_n_flag": flagged,
    }


def test_stealth(sub, label):
    log(f"\n  --- Stealth RS (>=2 vs =0) — {label} ---")
    s = sub.dropna(subset=["fwd_return_10d"])
    g0 = s[s["n_stealth_in_window"] == 0]["fwd_return_10d"]
    g2p = s[s["n_stealth_in_window"] >= 2]["fwd_return_10d"]
    return two_group_stats(g2p, g0, "stealth>=2", "stealth=0")


def test_tightness(sub, label):
    log(f"\n  --- Tightness pct_rank_252 (Q1 tight vs Q4 loose) — {label} ---")
    s = sub.dropna(subset=["pct_rank_252", "fwd_return_10d"])
    if len(s) < 40:
        log(f"    Too few rows (n={len(s)}) for quartile split.")
        return None
    q = pd.qcut(s["pct_rank_252"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
    if len(q.cat.categories) < 4:
        log(f"    Degenerate bins (n={len(s)}), skipped.")
        return None
    tight = s[q == "Q1"]["fwd_return_10d"]
    loose = s[q == "Q4"]["fwd_return_10d"]
    # tightness's original hypothesized direction was "tight is better" (tight>loose);
    # report using that same directional convention for comparability with Sections 9/10.
    return two_group_stats(tight, loose, "tight(Q1)", "loose(Q4)")


def test_roc10(sub, label):
    log(f"\n  --- ROC_10 (Q4 fast vs Q1 slow) — {label} ---")
    s = sub.dropna(subset=["roc_10", "fwd_return_10d"])
    if len(s) < 40:
        log(f"    Too few rows (n={len(s)}) for quartile split.")
        return None
    q = pd.qcut(s["roc_10"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
    if len(q.cat.categories) < 4:
        log(f"    Degenerate bins (n={len(s)}), skipped.")
        return None
    fast = s[q == "Q4"]["fwd_return_10d"]
    slow = s[q == "Q1"]["fwd_return_10d"]
    return two_group_stats(fast, slow, "ROC10-Q4(fast)", "ROC10-Q1(slow)")


def main():
    con = research_db.get_connection(DB)
    try:
        log("=" * 100)
        log("PRE_BREAKOUT Phase 6 (EXPLORATORY) — Regime-Conditional Re-Test of Dead Constructs")
        log("EXPLORATORY ONLY — no held-out data remains this session. Not a confirmatory test.")
        log("=" * 100)

        threshold, runaway_dates, by_year = step1_define_threshold(con)

        log("\n" + "=" * 100)
        log("STEP 2 — Re-test three dead constructs, split by runaway-bull status (FULL 2015-2026)")
        log("=" * 100)

        pop = load_population(con)
        log(f"\nLoaded {POP_TABLE} (full 2015-2026): {len(pop):,} rows, {pop['symbol'].nunique()} symbols")

        symbols = pop["symbol"].unique().tolist()
        prices_full = load_prices_full(con, symbols)
        ss_full = load_stock_signals_full(con, symbols)

        log("\nComputing ROC_10 (Section 11 definition)...")
        pop = compute_roc10(pop, prices_full)

        log("Computing stealth counts (Section 12 locked definition)...")
        idx_df = load_index_full(con)
        idx_df["ret"] = idx_df["close"].pct_change() * 100
        adverse_days_set = set(idx_df.loc[idx_df["ret"] < ADVERSE_THRESH, "date"].tolist())
        pop = compute_stealth_counts(pop, prices_full, ss_full, adverse_days_set)
        pop = pop[pop["has_data_stealth"]]

        pop["runaway_bull"] = pop["date"].isin(runaway_dates)
        n_rb = pop["runaway_bull"].sum()
        log(f"\nPopulation rows flagged runaway_bull=True: {n_rb:,} / {len(pop):,} ({n_rb/len(pop)*100:.2f}%)")

        rb_pop = pop[pop["runaway_bull"]]
        non_rb_pop = pop[~pop["runaway_bull"]]

        log(f"\nRUNAWAY-BULL subset: {len(rb_pop):,} rows")
        log(f"NON-RUNAWAY-BULL subset: {len(non_rb_pop):,} rows")

        results = {}
        log("\n" + "#" * 100)
        log("CONSTRUCT (a) — Stealth Relative Strength")
        log("#" * 100)
        results["stealth_runaway_bull"] = test_stealth(rb_pop, "RUNAWAY BULL")
        results["stealth_non_runaway_bull"] = test_stealth(non_rb_pop, "NON-RUNAWAY BULL")

        log("\n" + "#" * 100)
        log("CONSTRUCT (b) — Tightness (pct_rank_252)")
        log("#" * 100)
        results["tightness_runaway_bull"] = test_tightness(rb_pop, "RUNAWAY BULL")
        results["tightness_non_runaway_bull"] = test_tightness(non_rb_pop, "NON-RUNAWAY BULL")

        log("\n" + "#" * 100)
        log("CONSTRUCT (c) — ROC_10 Velocity")
        log("#" * 100)
        results["roc10_runaway_bull"] = test_roc10(rb_pop, "RUNAWAY BULL")
        results["roc10_non_runaway_bull"] = test_roc10(non_rb_pop, "NON-RUNAWAY BULL")

        log("\n" + "=" * 100)
        log("SUMMARY TABLE — all 6 cells")
        log("=" * 100)
        for k, v in results.items():
            if v is None:
                log(f"  {k:<35} SKIPPED (insufficient data)")
                continue
            flag = " **INSUFFICIENT-N**" if v["insufficient_n_flag"] else ""
            log(f"  {k:<35} n_hi={v['n_hi']:>7,} n_lo={v['n_lo']:>7,}  hit_delta={v['hit_delta']:+7.2f}pp  "
                f"cliffs_delta={v['cliffs_delta']:+.4f}  mwu_1p={v['mwu_one_p']:.6f}{flag}")

        rows = []
        for k, v in results.items():
            if v is None:
                continue
            r = dict(v)
            r["cell"] = k
            rows.append(r)
        results_df = pd.DataFrame(rows)
        out_csv = Path(__file__).parent / "prebreakout_v2_phase6_results.csv"
        results_df.to_csv(out_csv, index=False)
        by_year.to_csv(Path(__file__).parent / "prebreakout_v2_phase6_runaway_bull_by_year.csv")
        log(f"\nResults saved to {out_csv.name} and prebreakout_v2_phase6_runaway_bull_by_year.csv")

    finally:
        con.close()


if __name__ == "__main__":
    main()
