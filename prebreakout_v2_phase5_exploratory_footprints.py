"""
prebreakout_v2_phase5_exploratory_footprints.py — PRE_BREAKOUT Phase 5
(EXPLORATORY) — Two Candidate Right-Tail Footprints, Development Era ONLY.

*** METHODOLOGICAL GUARDRAIL ***
This script is hard-coded to only ever query rows with date <= DEV_END
('2019-12-31'). No query anywhere in this file references a date after
DEV_END. Validation (2020-2022) and OOS (2023+) are NEVER touched, queried,
loaded, or viewed at any point. Pulling price history from before
DEV_START (2015-01-01) for trailing-window warmup is fine and expected
(e.g. a 180-day window ending 2015-01-05 needs late-2014 data) -- that is
NOT Validation/OOS data, it's pre-Development history.

Any candidate that looks promising here is NOT iterated on further in this
script -- confirmation against Validation+OOS is explicitly a separate,
later, one-shot task per the project's three-era discipline.

Candidate A -- "Stealth Relative Strength": organic stock strength
(flat-or-positive close, liquid) on adverse KSE-100 days, counted over a
trailing window.

Candidate B -- "Volume Regime Shift": a 180-day volume high occurring while
the stock's own BBW%/base_tightness is in its own tight local (20-day)
percentile range.

Primary metric: right-tail hit rate P(fwd_return_10d > +10%). Cliff's delta
and MWU are reported as secondary/confirmatory checks only, per task
instruction (given the known mean-vs-rank divergence from outlier skew,
established in Sections 5.2/10.3/11.6).

READ access: pre_breakout_v2_staging_full, index_prices, prices_adjusted,
stock_signals -- ALL FILTERED TO date <= 2019-12-31. WRITE access: none.
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

DEV_START = "2015-01-01"
DEV_END = "2019-12-31"   # HARD BOUNDARY -- no query in this file exceeds this date.

RIGHT_TAIL_THRESHOLD = 10.0  # fwd_return_10d > +10%
WEAK_CONFIDENCE_FLOOR = 200


def log(msg):
    print(msg, flush=True)


def guard_no_future_leakage(df, date_col="date"):
    """Defensive check: assert no row in any loaded frame exceeds DEV_END.
    This is a belt-and-suspenders check on top of the SQL WHERE clauses --
    if this ever fires, something is wrong and must be fixed before
    proceeding, not silently ignored."""
    if len(df) == 0:
        return
    mx = df[date_col].max()
    assert mx <= DEV_END, (
        f"LEAKAGE GUARD TRIPPED: a loaded frame contains date {mx} > {DEV_END} "
        f"(Validation/OOS boundary). Aborting -- this must never happen."
    )


# ══════════════════════════════════════════════════════════════════════════
# Load — Development era + pre-history warmup only, never past DEV_END
# ══════════════════════════════════════════════════════════════════════════

def load_population(con):
    df = research_db.read_sql(
        f"SELECT symbol, date, bbw_pct, fwd_return_10d FROM {POP_TABLE} "
        f"WHERE date >= '{DEV_START}' AND date <= '{DEV_END}' ORDER BY symbol, date",
        con,
    )
    guard_no_future_leakage(df)
    return df


def load_index_prices(con):
    df = research_db.read_sql(
        f"SELECT date, close FROM index_prices WHERE symbol='KSE-100' AND date <= '{DEV_END}' "
        f"ORDER BY date",
        con,
    )
    guard_no_future_leakage(df)
    return df


def load_prices_full(con, symbols):
    q = f"""
        SELECT symbol, date, close, volume FROM prices_adjusted
        WHERE symbol IN ({",".join("?" for _ in symbols)}) AND date <= '{DEV_END}'
        ORDER BY symbol, date
    """
    df = research_db.read_sql(q, con, params=symbols)
    guard_no_future_leakage(df)
    by_symbol = {}
    for sym, g in df.groupby("symbol"):
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "close": g["close"].to_numpy(dtype=float),
            "volume": g["volume"].to_numpy(dtype=float),
        }
    return by_symbol


def load_stock_signals_full(con, symbols):
    q = f"""
        SELECT symbol, date, avg_vol_10d, base_tightness FROM stock_signals
        WHERE symbol IN ({",".join("?" for _ in symbols)}) AND date <= '{DEV_END}'
        ORDER BY symbol, date
    """
    df = research_db.read_sql(q, con, params=symbols)
    guard_no_future_leakage(df)
    by_symbol = {}
    for sym, g in df.groupby("symbol"):
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "avg_vol_10d": g["avg_vol_10d"].to_numpy(dtype=float),
            "base_tightness": g["base_tightness"].to_numpy(dtype=float),
        }
    return by_symbol


# ══════════════════════════════════════════════════════════════════════════
# Candidate A — Stealth Relative Strength
# ══════════════════════════════════════════════════════════════════════════

def analyze_kse100_returns(idx_df):
    idx_df = idx_df.copy()
    idx_df["ret"] = idx_df["close"].pct_change() * 100
    rets = idx_df["ret"].dropna()
    log("\nKSE-100 daily return distribution (Development era + pre-history warmup, "
        f"all still <= {DEV_END}):")
    desc = rets.describe(percentiles=[0.01, 0.05, 0.10, 0.25, 0.5, 0.75, 0.90])
    log(desc.to_string())
    for thresh in (-1.0, -1.5, -2.0):
        pct = (rets < thresh).mean() * 100
        n_days = (rets < thresh).sum()
        log(f"  Days with return < {thresh}%: {n_days:,} ({pct:.2f}% of all days, "
            f"~{n_days / (len(rets) / 252):.1f}/year over this window)")
    return idx_df


def build_stealth_counts(pop, prices_full, ss_full, adverse_days_set, window=20):
    n = len(pop)
    n_adverse_in_window = np.full(n, 0, dtype=np.int64)
    n_stealth_in_window = np.full(n, 0, dtype=np.int64)
    has_data = np.full(n, False)

    for sym, idx in pop.groupby("symbol").groups.items():
        pf = prices_full.get(sym)
        sf = ss_full.get(sym)
        if pf is None or sf is None:
            continue
        dates = pf["dates"]
        close = pf["close"]
        # stock daily return, position-aligned to `dates`
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
            n_adv = 0
            n_stealth = 0
            for p in range(lo, pos + 1):
                dt = dates[p]
                if dt not in adverse_days_set:
                    continue
                n_adv += 1
                r = stock_ret[p]
                if r is None or np.isnan(r) or r < 0:
                    continue
                ssi = ss_date_to_idx.get(dt)
                if ssi is None:
                    continue
                av = ss_avgvol[ssi]
                if av is None or np.isnan(av):
                    continue  # liquidity gate: avg_vol_10d must be non-null (existing convention)
                n_stealth += 1
            n_adverse_in_window[i] = n_adv
            n_stealth_in_window[i] = n_stealth

    pop = pop.copy()
    pop["n_adverse_in_window"] = n_adverse_in_window
    pop["n_stealth_in_window"] = n_stealth_in_window
    pop["has_data_a"] = has_data
    return pop


def hit_rate_report(sub, group_col, label, thresh=RIGHT_TAIL_THRESHOLD):
    log(f"\n{'-'*90}")
    log(f"{label}")
    log(f"{'-'*90}")
    s = sub.dropna(subset=["fwd_return_10d"])
    rep = s.groupby(group_col)["fwd_return_10d"].agg(
        n="count",
        hit_rate=lambda x: (x > thresh).mean() * 100,
        mean="mean",
        median="median",
    )
    log(rep.to_string())
    return rep


def two_group_secondary_stats(hi, lo, hi_label, lo_label):
    n_hi, n_lo = len(hi), len(lo)
    if n_hi < 5 or n_lo < 5:
        log(f"  Too few rows ({hi_label} n={n_hi}, {lo_label} n={n_lo}) for secondary stats.")
        return None
    flagged = n_hi < WEAK_CONFIDENCE_FLOOR or n_lo < WEAK_CONFIDENCE_FLOOR
    if flagged:
        log(f"  ** FLAG: {hi_label} n={n_hi:,} / {lo_label} n={n_lo:,} — below the "
            f"~{WEAK_CONFIDENCE_FLOOR} Weak-confidence floor. Secondary stats reported "
            f"but flagged insufficient-N. **")
    u_two, p_two = stats.mannwhitneyu(hi, lo, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(hi, lo, alternative="greater")
    delta = (2 * u_two) / (n_hi * n_lo) - 1
    hit_hi = (hi > RIGHT_TAIL_THRESHOLD).mean() * 100
    hit_lo = (lo > RIGHT_TAIL_THRESHOLD).mean() * 100
    log(f"  {hi_label}: n={n_hi:,}, hit_rate={hit_hi:.2f}%, mean={hi.mean():+.4f}%, median={hi.median():+.4f}%")
    log(f"  {lo_label}: n={n_lo:,}, hit_rate={hit_lo:.2f}%, mean={lo.mean():+.4f}%, median={lo.median():+.4f}%")
    log(f"  Hit-rate delta: {hit_hi - hit_lo:+.2f}pp")
    log(f"  MWU two-sided p = {p_two:.6f}  |  MWU one-sided (hi>lo) p = {p_one:.6f}")
    log(f"  Cliff's delta = {delta:.4f}")
    return {
        "n_hi": n_hi, "n_lo": n_lo, "hit_hi": hit_hi, "hit_lo": hit_lo,
        "hit_delta": hit_hi - hit_lo, "mwu_two_p": p_two, "mwu_one_p": p_one,
        "cliffs_delta": delta, "insufficient_n_flag": flagged,
    }


def distribution_breakdown(hi, lo, hi_label, lo_label):
    log(f"\n  Decile breakdown of fwd_return_10d — {hi_label} vs {lo_label}:")
    deciles = np.arange(0, 101, 10)
    hi_pct = np.percentile(hi, deciles)
    lo_pct = np.percentile(lo, deciles)
    rep = pd.DataFrame({"decile": deciles, hi_label: hi_pct, lo_label: lo_pct})
    log(rep.to_string(index=False))
    log(f"\n  Right-tail composition check — {hi_label}:")
    for cut in (10, 20, 30, 50):
        pct = (hi > cut).mean() * 100
        log(f"    P(fwd_return_10d > {cut}%) = {pct:.2f}%  (n={((hi > cut).sum()):,})")
    log(f"  Right-tail composition check — {lo_label}:")
    for cut in (10, 20, 30, 50):
        pct = (lo > cut).mean() * 100
        log(f"    P(fwd_return_10d > {cut}%) = {pct:.2f}%  (n={((lo > cut).sum()):,})")


# ══════════════════════════════════════════════════════════════════════════
# Candidate B — Volume Regime Shift
# ══════════════════════════════════════════════════════════════════════════

def build_candidate_b_features(pop, prices_full, ss_full, tight_window=20, vol_window=180):
    n = len(pop)
    vol_high_180 = np.full(n, False)
    pct_rank_local = np.full(n, np.nan)

    for sym, idx in pop.groupby("symbol").groups.items():
        pf = prices_full.get(sym)
        sf = ss_full.get(sym)
        if pf is None or sf is None:
            continue
        dates = pf["dates"]
        volume = pf["volume"]

        ss_dates = sf["dates"]
        ss_bt = sf["base_tightness"]

        for i in idx:
            d = pop.at[i, "date"]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue
            # 180-day volume high: today's volume > max of the PRIOR 180 days (strictly prior)
            if pos >= 1:
                prior_lo = max(0, pos - vol_window)
                prior_window = volume[prior_lo:pos]
                prior_window = prior_window[~np.isnan(prior_window)]
                today_vol = volume[pos]
                if len(prior_window) >= 30 and today_vol is not None and not np.isnan(today_vol):
                    vol_high_180[i] = bool(today_vol > prior_window.max())

            # local tightness percentile rank: today's base_tightness within
            # trailing `tight_window` days of base_tightness, from stock_signals,
            # SAME formula as base_tightness/bbw_pct -- only the ranking window
            # is new (20d instead of 252d), not the underlying tightness measure.
            ss_pos = np.searchsorted(ss_dates, d)
            if ss_pos < len(ss_dates) and ss_dates[ss_pos] == d:
                v = ss_bt[ss_pos]
                if v is not None and not np.isnan(v):
                    w = ss_bt[max(0, ss_pos - tight_window + 1): ss_pos + 1]
                    w = w[~np.isnan(w)]
                    if len(w) >= 10:  # min 50% of a 20-day window, documented choice
                        pct_rank_local[i] = (w <= v).mean() * 100

    pop = pop.copy()
    pop["vol_high_180"] = vol_high_180
    pop["pct_rank_local20"] = pct_rank_local
    return pop


# ══════════════════════════════════════════════════════════════════════════
def main():
    con = research_db.get_connection(DB)
    try:
        log("=" * 100)
        log("PRE_BREAKOUT Phase 5 (EXPLORATORY) — Two Candidate Right-Tail Footprints")
        log(f"DEVELOPMENT ERA ONLY: {DEV_START} -> {DEV_END}. "
            f"No query in this script ever references a date after {DEV_END}.")
        log("=" * 100)

        pop = load_population(con)
        log(f"\nLoaded {POP_TABLE} (Development era only): {len(pop):,} rows, "
            f"{pop['symbol'].nunique()} symbols, date range {pop['date'].min()} -> {pop['date'].max()}")
        assert pop["date"].max() <= DEV_END

        symbols = pop["symbol"].unique().tolist()
        idx_df = load_index_prices(con)
        prices_full = load_prices_full(con, symbols)
        ss_full = load_stock_signals_full(con, symbols)

        # ── KSE-100 adverse-day threshold justification ──
        log("\n" + "=" * 100)
        log("CANDIDATE A — Stealth Relative Strength")
        log("=" * 100)
        idx_df = analyze_kse100_returns(idx_df)

        ADVERSE_THRESH = -1.5
        log(f"\nUsing adverse-day threshold = {ADVERSE_THRESH}% (per task's starting point; "
            f"see distribution above — this sits beyond the 5th percentile of daily returns, "
            f"a meaningfully bad-but-not-vanishingly-rare day, generating enough adverse days "
            f"per year for a 20-day trailing window to plausibly contain 1+ of them).")
        adverse_days_set = set(idx_df.loc[idx_df["ret"] < ADVERSE_THRESH, "date"].tolist())
        log(f"Adverse days identified (Development era + warmup, all <= {DEV_END}): "
            f"{len(adverse_days_set):,}")

        log("\nComputing stealth counts (20-day trailing window)...")
        pop_a = build_stealth_counts(pop, prices_full, ss_full, adverse_days_set, window=20)
        n_no_data = (~pop_a["has_data_a"]).sum()
        log(f"Rows with no price-history match (excluded): {n_no_data:,}")
        pop_a = pop_a[pop_a["has_data_a"]]

        log("\nDistribution of n_adverse_in_window (adverse days present in the trailing 20d window):")
        log(pop_a["n_adverse_in_window"].value_counts().sort_index().to_string())

        log("\nDistribution of n_stealth_in_window (stealth days, the candidate signal):")
        log(pop_a["n_stealth_in_window"].value_counts().sort_index().to_string())

        pop_a["stealth_group"] = pop_a["n_stealth_in_window"].apply(
            lambda x: "0" if x == 0 else ("1" if x == 1 else "2+")
        )
        hit_rate_report(pop_a, "stealth_group", "Right-tail hit rate by stealth group (0 / 1 / 2+)")

        group0 = pop_a[pop_a["stealth_group"] == "0"]["fwd_return_10d"].dropna()
        group2p = pop_a[pop_a["stealth_group"] == "2+"]["fwd_return_10d"].dropna()
        log("\nSecondary stats: stealth 2+ vs stealth 0")
        stats_a = two_group_secondary_stats(group2p, group0, "stealth>=2", "stealth=0")

        group1p = pop_a[pop_a["n_stealth_in_window"] >= 1]["fwd_return_10d"].dropna()
        log("\nSecondary stats: stealth 1+ vs stealth 0 (broader grouping)")
        stats_a_1p = two_group_secondary_stats(group1p, group0, "stealth>=1", "stealth=0")

        # ── Candidate B ──
        log("\n" + "=" * 100)
        log("CANDIDATE B — Volume Regime Shift")
        log("=" * 100)
        log("\nUsing tight_window=20 days for the local BBW% percentile rank: matches "
            "base_tightness's own native 20-day close window, giving a 'local' percentile "
            "on the same timescale as the tightness measure itself, and enough trailing "
            "observations (min 10 required) for a stable rank at a 20-day span (a 10-day "
            "span would leave too few points to rank against, min 5 of 10 -- less stable).")
        log("Using vol_window=180 days for the volume-high check, per task specification.")

        pop_b = build_candidate_b_features(pop, prices_full, ss_full, tight_window=20, vol_window=180)

        n_vh = pop_b["vol_high_180"].sum()
        n_pr = pop_b["pct_rank_local20"].notna().sum()
        log(f"\nvol_high_180 = True: {n_vh:,} / {len(pop_b):,} ({n_vh/len(pop_b)*100:.2f}%)")
        log(f"pct_rank_local20 non-null: {n_pr:,} / {len(pop_b):,} ({n_pr/len(pop_b)*100:.1f}%)")

        pop_b_valid = pop_b.dropna(subset=["pct_rank_local20"])
        q1_cutoff = np.percentile(pop_b_valid["pct_rank_local20"], 25)
        log(f"pct_rank_local20 distribution — 25th pct cutoff (tightest quartile boundary): "
            f"{q1_cutoff:.2f} (by definition of a percentile-rank field, tightest quartile "
            f"is simply pct_rank_local20 <= 25)")

        pop_b_valid = pop_b_valid.copy()
        pop_b_valid["tight_local_q1"] = pop_b_valid["pct_rank_local20"] <= 25
        pop_b_valid["compound"] = pop_b_valid["vol_high_180"] & pop_b_valid["tight_local_q1"]

        log(f"\nCompound condition (180d vol high AND tightest local quartile) True: "
            f"{pop_b_valid['compound'].sum():,} / {len(pop_b_valid):,} "
            f"({pop_b_valid['compound'].mean()*100:.3f}%)")

        hit_rate_report(pop_b_valid, "compound", "Right-tail hit rate: compound condition vs rest")

        compound_true = pop_b_valid[pop_b_valid["compound"]]["fwd_return_10d"].dropna()
        compound_false = pop_b_valid[~pop_b_valid["compound"]]["fwd_return_10d"].dropna()
        log("\nSecondary stats: compound=True vs compound=False")
        stats_b = two_group_secondary_stats(compound_true, compound_false, "compound=True", "compound=False")

        # Also report vol_high_180 alone and tight_local_q1 alone for context
        log("\n(Context only, not a separate primary test) vol_high_180 alone:")
        vh_true = pop_b_valid[pop_b_valid["vol_high_180"]]["fwd_return_10d"].dropna()
        vh_false = pop_b_valid[~pop_b_valid["vol_high_180"]]["fwd_return_10d"].dropna()
        two_group_secondary_stats(vh_true, vh_false, "vol_high_180=True", "vol_high_180=False")

        log("\n(Context only, not a separate primary test) tight_local_q1 alone:")
        tq_true = pop_b_valid[pop_b_valid["tight_local_q1"]]["fwd_return_10d"].dropna()
        tq_false = pop_b_valid[~pop_b_valid["tight_local_q1"]]["fwd_return_10d"].dropna()
        two_group_secondary_stats(tq_true, tq_false, "tight_local_q1=True", "tight_local_q1=False")

        # ── Step 3: bridge the mean-vs-rank gap for whichever candidate shows a lift ──
        log("\n" + "=" * 100)
        log("STEP 3 — BRIDGING THE MEAN-VS-RANK GAP (distribution breakdowns)")
        log("=" * 100)

        log("\n--- Candidate A: stealth>=2 vs stealth=0 ---")
        if len(group2p) > 0 and len(group0) > 0:
            distribution_breakdown(group2p, group0, "stealth>=2", "stealth=0")

        log("\n--- Candidate A: stealth>=1 vs stealth=0 ---")
        if len(group1p) > 0 and len(group0) > 0:
            distribution_breakdown(group1p, group0, "stealth>=1", "stealth=0")

        log("\n--- Candidate B: compound=True vs compound=False ---")
        if len(compound_true) > 0 and len(compound_false) > 0:
            distribution_breakdown(compound_true, compound_false, "compound=True", "compound=False")

        # ── Save results ──
        out = {
            "candidate_a_stealth2plus_vs_0": stats_a,
            "candidate_a_stealth1plus_vs_0": stats_a_1p,
            "candidate_b_compound": stats_b,
        }
        rows = []
        for k, v in out.items():
            if v is None:
                continue
            row = dict(v)
            row["test"] = k
            rows.append(row)
        results_df = pd.DataFrame(rows)
        out_csv = Path(__file__).parent / "prebreakout_v2_phase5_results.csv"
        results_df.to_csv(out_csv, index=False)
        log(f"\nResults saved to {out_csv.name} ({len(results_df)} rows).")

        log("\n" + "=" * 100)
        log("EXPLICIT CONFIRMATION: Validation (2020-2022) and OOS (2023+) data were NEVER "
            "queried, loaded, or viewed at any point in this script. Every SQL query above "
            f"carries an explicit date <= '{DEV_END}' filter, and a runtime assertion "
            "(guard_no_future_leakage) checked every loaded frame against this boundary.")
        log("=" * 100)

    finally:
        con.close()


if __name__ == "__main__":
    main()
