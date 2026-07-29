"""
prebreakout_v2_phase5_confirmatory.py — PRE_BREAKOUT Phase 5 CONFIRMATORY
(single, locked run) — Stealth Relative Strength >= 2.

*** THIS IS A ONE-SHOT CONFIRMATORY TEST. LOCKED RULE, NO PARAMETER TUNING. ***
Every parameter below is copied verbatim from the Development-era exploratory
result (PRE_BREAKOUT_Specification_v1.0.md, Section 12.2) and MUST NOT be
adjusted based on the result:
  - Adverse index day: KSE-100 daily return <= -1.5%
  - Trailing window: exactly 20 trading days
  - Stealth day: adverse index day where the stock itself closed
    flat-or-positive (>=0%) AND had a non-null avg_vol_10d that day
    (existing liquidity-gate convention, applied per-day)
  - Comparison: stealth>=2 vs stealth=0 ONLY (no stealth=1 comparison, no new
    grouping — exactly the Development headline comparison, nothing else)

POPULATION: pre_breakout_v2_staging_full, Validation (2020-01-01..2022-12-31)
+ OOS (2023-01-01 onward) COMBINED into a single population, per explicit PI
instruction — reported as ONE primary confirmatory number. Era-by-era
(Validation alone / OOS alone) is reported separately, clearly labeled
secondary/informational, not the primary verdict.

READ access: pre_breakout_v2_staging_full, index_prices, prices_adjusted,
stock_signals. WRITE access: none. Read-only, no production writes.
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

CONFIRM_START = "2020-01-01"   # Validation start
VALIDATION_END = "2022-12-31"
OOS_START = "2023-01-01"

ADVERSE_THRESH = -1.5   # LOCKED — copied from Section 12, do not change
WINDOW = 20             # LOCKED
RIGHT_TAIL_THRESHOLD = 10.0  # LOCKED — matches Development's primary metric
WEAK_CONFIDENCE_FLOOR = 200


def log(msg):
    print(msg, flush=True)


# ══════════════════════════════════════════════════════════════════════════
# Load — Validation+OOS combined (2020-01-01 onward), same logic as Section 12
# ══════════════════════════════════════════════════════════════════════════

def load_population(con):
    return research_db.read_sql(
        f"SELECT symbol, date, bbw_pct, fwd_return_10d FROM {POP_TABLE} "
        f"WHERE date >= '{CONFIRM_START}' ORDER BY symbol, date",
        con,
    )


def load_index_prices(con):
    # Warmup history before CONFIRM_START is fine (needed for the 20-day
    # trailing window at the very start of the confirmatory population) —
    # this is standard trailing-window construction, not a boundary violation.
    return research_db.read_sql(
        "SELECT date, close FROM index_prices WHERE symbol='KSE-100' ORDER BY date", con
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


def load_stock_signals_full(con, symbols):
    q = """
        SELECT symbol, date, avg_vol_10d FROM stock_signals
        WHERE symbol IN ({})
        ORDER BY symbol, date
    """.format(",".join("?" for _ in symbols))
    df = research_db.read_sql(q, con, params=symbols)
    by_symbol = {}
    for sym, g in df.groupby("symbol"):
        by_symbol[sym] = {
            "dates": g["date"].to_numpy(),
            "avg_vol_10d": g["avg_vol_10d"].to_numpy(dtype=float),
        }
    return by_symbol


def analyze_kse100_returns(idx_df, thresh):
    idx_df = idx_df.copy()
    idx_df["ret"] = idx_df["close"].pct_change() * 100
    adverse_set = set(idx_df.loc[idx_df["ret"] < thresh, "date"].tolist())
    return idx_df, adverse_set


def build_stealth_counts(pop, prices_full, ss_full, adverse_days_set, window=WINDOW):
    n = len(pop)
    n_stealth_in_window = np.full(n, 0, dtype=np.int64)
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
            n_stealth = 0
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
                n_stealth += 1
            n_stealth_in_window[i] = n_stealth

    pop = pop.copy()
    pop["n_stealth_in_window"] = n_stealth_in_window
    pop["has_data"] = has_data
    return pop


def two_group_secondary_stats(hi, lo, hi_label, lo_label, thresh=RIGHT_TAIL_THRESHOLD):
    n_hi, n_lo = len(hi), len(lo)
    if n_hi < 5 or n_lo < 5:
        log(f"  Too few rows ({hi_label} n={n_hi}, {lo_label} n={n_lo}).")
        return None
    flagged = n_hi < WEAK_CONFIDENCE_FLOOR or n_lo < WEAK_CONFIDENCE_FLOOR
    if flagged:
        log(f"  ** FLAG: {hi_label} n={n_hi:,} / {lo_label} n={n_lo:,} — below the "
            f"~{WEAK_CONFIDENCE_FLOOR} Weak-confidence floor. **")
    u_two, p_two = stats.mannwhitneyu(hi, lo, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(hi, lo, alternative="greater")
    delta = (2 * u_two) / (n_hi * n_lo) - 1
    hit_hi = (hi > thresh).mean() * 100
    hit_lo = (lo > thresh).mean() * 100
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


def distribution_breakdown(hi, lo, hi_label, lo_label, thresh=RIGHT_TAIL_THRESHOLD):
    log(f"\n  Decile breakdown of fwd_return_10d — {hi_label} vs {lo_label}:")
    deciles = np.arange(0, 101, 10)
    hi_pct = np.percentile(hi, deciles)
    lo_pct = np.percentile(lo, deciles)
    rep = pd.DataFrame({"decile": deciles, hi_label: hi_pct, lo_label: lo_pct})
    log(rep.to_string(index=False))
    log(f"\n  Right-tail composition check — {hi_label}:")
    for cut in (10, 20, 30, 50):
        pct = (hi > cut).mean() * 100
        log(f"    P(fwd_return_10d > {cut}%) = {pct:.2f}%  (n={(hi > cut).sum():,})")
    log(f"  Right-tail composition check — {lo_label}:")
    for cut in (10, 20, 30, 50):
        pct = (lo > cut).mean() * 100
        log(f"    P(fwd_return_10d > {cut}%) = {pct:.2f}%  (n={(lo > cut).sum():,})")


def main():
    con = research_db.get_connection(DB)
    try:
        log("=" * 100)
        log("PRE_BREAKOUT Phase 5 CONFIRMATORY — Stealth Relative Strength >= 2")
        log("ONE-SHOT LOCKED RUN. Adverse threshold=-1.5%, window=20d, stealth>=2 vs stealth=0.")
        log(f"Population: Validation ({CONFIRM_START}..{VALIDATION_END}) + OOS ({OOS_START} onward), COMBINED.")
        log("=" * 100)

        pop = load_population(con)
        log(f"\nLoaded {POP_TABLE} (Validation+OOS combined): {len(pop):,} rows, "
            f"{pop['symbol'].nunique()} symbols, date range {pop['date'].min()} -> {pop['date'].max()}")

        symbols = pop["symbol"].unique().tolist()
        idx_df = load_index_prices(con)
        prices_full = load_prices_full(con, symbols)
        ss_full = load_stock_signals_full(con, symbols)

        idx_df, adverse_days_set = analyze_kse100_returns(idx_df, ADVERSE_THRESH)
        log(f"\nAdverse days (KSE-100 return < {ADVERSE_THRESH}%), full index history "
            f"(warmup + confirmatory period): {len(adverse_days_set):,}")

        log("\nComputing stealth counts (locked: 20-day trailing window)...")
        pop = build_stealth_counts(pop, prices_full, ss_full, adverse_days_set, window=WINDOW)
        n_no_data = (~pop["has_data"]).sum()
        log(f"Rows with no price-history match (excluded): {n_no_data:,}")
        pop = pop[pop["has_data"]]

        log("\nFull stealth-count distribution (combined Validation+OOS population, for reference only):")
        log(pop["n_stealth_in_window"].value_counts().sort_index().to_string())

        group0 = pop[pop["n_stealth_in_window"] == 0]["fwd_return_10d"].dropna()
        group2p = pop[pop["n_stealth_in_window"] >= 2]["fwd_return_10d"].dropna()

        log("\n" + "=" * 100)
        log("PRIMARY VERDICT — Combined Validation+OOS, stealth>=2 vs stealth=0")
        log("=" * 100)
        confirm_stats = two_group_secondary_stats(group2p, group0, "stealth>=2", "stealth=0")

        log("\nDistribution breakdown (combined Validation+OOS):")
        if len(group2p) > 0 and len(group0) > 0:
            distribution_breakdown(group2p, group0, "stealth>=2", "stealth=0")

        # ── Secondary / informational: era-by-era ──
        log("\n" + "=" * 100)
        log("SECONDARY, NOT THE PRIMARY VERDICT — era-by-era breakdown")
        log("=" * 100)

        val_pop = pop[(pop["date"] >= CONFIRM_START) & (pop["date"] <= VALIDATION_END)]
        oos_pop = pop[pop["date"] >= OOS_START]

        for era_name, era_pop in [("Validation (2020-2022) — secondary", val_pop),
                                   ("OOS (2023+) — secondary", oos_pop)]:
            log(f"\n--- {era_name} ---")
            g0 = era_pop[era_pop["n_stealth_in_window"] == 0]["fwd_return_10d"].dropna()
            g2p = era_pop[era_pop["n_stealth_in_window"] >= 2]["fwd_return_10d"].dropna()
            two_group_secondary_stats(g2p, g0, "stealth>=2", "stealth=0")

        # ── Direct comparison table vs Development ──
        log("\n" + "=" * 100)
        log("DIRECT COMPARISON — Development (Section 12.2) vs Combined Validation+OOS (this run)")
        log("=" * 100)
        dev_n, dev_hit_delta, dev_delta, dev_p_one = 1028, 4.87, 0.0747, 0.000019
        if confirm_stats:
            confirm_n_str = str(confirm_stats["n_hi"])
            confirm_hit_str = f"{confirm_stats['hit_delta']:+.2f}"
            confirm_delta_str = f"{confirm_stats['cliffs_delta']:.4f}"
            confirm_p_str = f"{confirm_stats['mwu_one_p']:.6f}"
            log(f"{'Metric':<30}{'Development':<20}{'Validation+OOS (confirmatory)':<30}")
            log(f"{'-'*80}")
            log(f"{'N (stealth>=2)':<30}{dev_n:<20}{confirm_n_str:<30}")
            log(f"{'Hit-rate lift (pp)':<30}{'+' + str(dev_hit_delta):<20}{confirm_hit_str:<30}")
            log(f"{'Cliffs delta':<30}{dev_delta:<20}{confirm_delta_str:<30}")
            log(f"{'MWU one-sided p':<30}{dev_p_one:<20}{confirm_p_str:<30}")

        # ── Verdict ──
        log("\n" + "=" * 100)
        log("FINAL VERDICT")
        log("=" * 100)
        if confirm_stats:
            same_direction = confirm_stats["cliffs_delta"] > 0 and confirm_stats["hit_delta"] > 0
            significant = confirm_stats["mwu_one_p"] < 0.05
            if same_direction and significant:
                ratio = confirm_stats["cliffs_delta"] / dev_delta if dev_delta != 0 else float("nan")
                if ratio >= 0.5:
                    verdict = "CONFIRMED — comparable direction and magnitude to Development, statistically significant."
                else:
                    verdict = "WEAKENED — same direction, meaningfully smaller effect, still significant."
            elif same_direction and not significant:
                verdict = "WEAKENED (not statistically significant) — same direction but does not clear p<0.05."
            else:
                verdict = "DEAD — null or reversed."
            log(verdict)
        else:
            log("DEAD — insufficient data to run the confirmatory test.")

        # ── Save ──
        rows = []
        if confirm_stats:
            r = dict(confirm_stats)
            r["test"] = "phase5_confirmatory_stealth2plus_vs_0_combined"
            rows.append(r)
        results_df = pd.DataFrame(rows)
        out_csv = Path(__file__).parent / "prebreakout_v2_phase5_confirmatory_results.csv"
        results_df.to_csv(out_csv, index=False)
        log(f"\nResults saved to {out_csv.name}.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
