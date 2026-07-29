"""
prebreakout_v2_rebuild_and_test.py — PRE_BREAKOUT Phase 4 (Research Reopening):
rebuild against the corrected BREAKOUT V2 population, recover volume-coupling
casualties at the research level, compute the three candidate tightness
measures, and run the first hypothesis test (does tightness predict
fwd_return_10d?).

READ access:  stock_signals_breakout_v2_staging_full, stock_signals, prices_adjusted
WRITE access: pre_breakout_v2_staging_full ONLY (new table). No production
table is modified; stock_signals.py is not touched. The volume-coupling
recovery lives only inside this research pipeline (Part B) -- it does not
change stock_signals.base_tightness anywhere.

Reuses:
  - _compute_bt_vc from stock_signals.py (imported, not reimplemented) for the
    volume-coupling recovery, exactly as prior sessions' diagnostic did.
  - The same already_broken "eligibility" derivation validated in the prior
    PRE_BREAKOUT inventory session (re-derived here from the stored
    active_resistance/breakout_event/close sequence, not re-litigated).
  - compute_forward_returns.py's exact fwd_return_10d formula.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from stock_signals import _compute_bt_vc
from breakout_events_v2 import compute_breakout_events

DB = str(Path(__file__).parent / "psx_data.db")
SRC_STAGING = "stock_signals_breakout_v2_staging_full"
OLD_PRE_STAGING = "pre_breakout_v2_staging"
OUT_STAGING = "pre_breakout_v2_staging_full"

MIN_TRAILING_OBS = 60
LIQUIDITY_NOTE = "source table is already rolling-liquidity-gated (BREAKOUT V2 fix)"

ERAS = [
    ("Development", "2015-01-01", "2019-12-31"),
    ("Validation",  "2020-01-01", "2022-12-31"),
    ("OOS",         "2023-01-01", "2026-12-31"),
]


def log(msg):
    print(msg, flush=True)


# ══════════════════════════════════════════════════════════════════════════
# PART A — population rebuild
# ══════════════════════════════════════════════════════════════════════════

def load_breakout_staging(con):
    return pd.read_sql_query(
        f"SELECT symbol, date, close, active_resistance, breakout_event "
        f"FROM {SRC_STAGING} ORDER BY symbol, date",
        con,
    )


def derive_already_broken_from_full_history(con, symbols):
    """CORRECTED derivation: stock_signals_breakout_v2_staging_full has date
    GAPS per symbol (only liquidity-eligible dates are stored, per the BREAKOUT
    V2 rolling-liquidity fix). Walking that gapped table directly to derive
    already_broken -- as the prior PRE_BREAKOUT inventory session validly did
    against the OLD, gapless 243-symbol table -- is invalid here: an initial
    attempt produced 91 mismatches, the exact same failure mode diagnosed in
    the BREAKOUT V2 rolling-liquidity session (a gap-blind incremental walk
    misattributes state across the gaps).

    Fix: recompute compute_breakout_events() (imported, unmodified) fresh from
    each symbol's FULL continuous prices_adjusted history, derive
    already_broken on that gapless sequence (valid, same technique as before),
    then filter down to the liquidity-eligible dates afterward. This also
    re-validates every stored (close, active_resistance, breakout_event) in
    the source table against an independent fresh recompute."""
    full = {}
    for sym in symbols:
        prices = con.execute(
            "SELECT date, close, high FROM prices_adjusted WHERE symbol=? ORDER BY date", (sym,)
        ).fetchall()
        if not prices:
            continue
        results = compute_breakout_events(prices)

        broken_state = False
        prev_resistance = None
        rows = []
        for r in results:
            ar = r["active_resistance"]
            close = r["close"]
            if ar is not None and ar != prev_resistance:
                broken_state = False
            eligibility_broken = broken_state  # state used for the event test THIS day

            ev = 0
            if ar is not None and close is not None:
                if close > ar:
                    if not broken_state:
                        ev = 1
                        broken_state = True
                else:
                    broken_state = False
            rows.append((r["date"], close, ar, ev, eligibility_broken))
            prev_resistance = ar if ar is not None else prev_resistance

        full[sym] = pd.DataFrame(
            rows, columns=["date", "close", "active_resistance", "breakout_event_recomputed",
                            "already_broken_eligibility"]
        )
    return full


def part_a(con):
    log("=" * 100)
    log("PART A — PRE_BREAKOUT population rebuild against stock_signals_breakout_v2_staging_full")
    log("=" * 100)

    raw = load_breakout_staging(con)
    log(f"\nLoaded {SRC_STAGING}: {len(raw):,} rows, {raw['symbol'].nunique()} symbols, "
        f"date range {raw['date'].min()} -> {raw['date'].max()}")
    log(f"NOTE: {LIQUIDITY_NOTE} — this source table only contains dates where the "
        f"symbol was liquidity-eligible, unlike the deprecated 243-symbol table which "
        f"contained a symbol's full unconditional history. Expect the new PRE_BREAKOUT "
        f"population to be considerably smaller for this reason alone, independent of "
        f"anything about the PRE_BREAKOUT definition itself.")

    symbols = raw["symbol"].unique().tolist()
    full_by_symbol = derive_already_broken_from_full_history(con, symbols)

    # Join: for each stored eligible row, pull the TRUE already_broken/close/
    # active_resistance/breakout_event from the fresh full-history recompute.
    merged_rows = []
    mismatches = 0
    for sym, g in raw.groupby("symbol"):
        full_df = full_by_symbol.get(sym)
        if full_df is None:
            continue
        full_idx = full_df.set_index("date")
        for row in g.itertuples():
            if row.date not in full_idx.index:
                continue  # shouldn't happen -- stored date must exist in full history
            fr = full_idx.loc[row.date]

            def _eq(a, b):
                a_null = a is None or (isinstance(a, float) and pd.isna(a))
                b_null = b is None or (isinstance(b, float) and pd.isna(b))
                if a_null and b_null:
                    return True
                if a_null != b_null:
                    return False
                return a == b

            if not _eq(fr["close"], row.close) or not _eq(fr["active_resistance"], row.active_resistance) \
                    or not _eq(fr["breakout_event_recomputed"], row.breakout_event):
                mismatches += 1
                continue
            merged_rows.append((sym, row.date, fr["close"], fr["active_resistance"],
                                 fr["breakout_event_recomputed"], fr["already_broken_eligibility"]))

    derived = pd.DataFrame(merged_rows, columns=[
        "symbol", "date", "close", "active_resistance", "breakout_event", "already_broken_eligibility"
    ])
    log(f"\nVALIDATION: stored (close, active_resistance, breakout_event) vs independent fresh "
        f"recompute from full continuous price history — {mismatches:,} mismatches out of "
        f"{len(raw):,} rows.")
    if mismatches:
        log("  !! Stored staging table does not match a fresh recompute — STOPPING, results unreliable.")
        raise SystemExit(1)
    log("  OK — every stored row matches an independent fresh recompute exactly. "
        "already_broken derived correctly (gapless walk, filtered down afterward).")

    mask_core = derived["active_resistance"].notna() & (derived["close"] <= derived["active_resistance"])
    pop = derived[mask_core & (~derived["already_broken_eligibility"])].copy()

    log(f"\nRows with active_resistance NOT NULL AND close <= active_resistance "
        f"(pre already_broken filter): {mask_core.sum():,}")
    log(f"PRE_BREAKOUT population (new): {len(pop):,} rows, {pop['symbol'].nunique()} symbols")

    old_rows = con.execute(f"SELECT COUNT(*) FROM {OLD_PRE_STAGING}").fetchone()[0]
    old_symbols = con.execute(f"SELECT COUNT(DISTINCT symbol) FROM {OLD_PRE_STAGING}").fetchone()[0]
    log(f"\n--- Before / after ---")
    log(f"  OLD ({OLD_PRE_STAGING}, built against the deprecated 243-symbol table): "
        f"{old_symbols} symbols, {old_rows:,} rows")
    log(f"  NEW (this rebuild, {SRC_STAGING}): {pop['symbol'].nunique()} symbols, {len(pop):,} rows")
    log(f"  Ratio: {len(pop)/old_rows*100:.1f}% of the old row count")

    per_sym = pop.groupby("symbol").size()
    log(f"\nPer-symbol row counts (new population, n={pop['symbol'].nunique()} symbols):")
    log(f"  min={per_sym.min()}  median={per_sym.median():.0f}  max={per_sym.max()}  mean={per_sym.mean():.1f}")

    return pop.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# PART B — volume-coupling recovery (research-level only)
# ══════════════════════════════════════════════════════════════════════════

def part_b(con, pop):
    log("\n" + "=" * 100)
    log("PART B — volume-coupling recovery (research pipeline only, stock_signals.py untouched)")
    log("=" * 100)

    ss = pd.read_sql_query(
        "SELECT symbol, date, base_tightness FROM stock_signals ORDER BY symbol, date", con
    )
    ss_lookup = {(r.symbol, r.date): r.base_tightness for r in ss.itertuples()}

    prices_by_symbol = {}
    for symbol, date, close, volume in con.execute(
        "SELECT symbol, date, close, volume FROM prices_adjusted ORDER BY symbol, date"
    ).fetchall():
        prices_by_symbol.setdefault(symbol, []).append((date, close, volume))
    date_index_by_symbol = {
        sym: {d: i for i, (d, c, v) in enumerate(rows)} for sym, rows in prices_by_symbol.items()
    }

    n_null_before = 0
    n_recovered = 0
    n_still_null_no_ss_row = 0
    n_still_null_insufficient_price = 0
    n_still_null_unexplained = 0

    recovered_map = {}  # (symbol, date) -> recovered bt value, for population rows only

    pop_symbols = set(pop["symbol"].unique())
    for symbol, date in zip(pop["symbol"], pop["date"]):
        bt = ss_lookup.get((symbol, date))
        if bt is not None:
            continue  # not null, nothing to recover
        n_null_before += 1

        rows = prices_by_symbol.get(symbol)
        idx_map = date_index_by_symbol.get(symbol, {})
        pos = idx_map.get(date)
        if (symbol, date) not in ss_lookup:
            n_still_null_no_ss_row += 1
            continue
        if rows is None or pos is None:
            n_still_null_no_ss_row += 1
            continue

        price_only_rows = [(d, c, 1.0) for (d, c, v) in rows]
        bt_price_only, _, _ = _compute_bt_vc(price_only_rows, pos)
        bt_real, _, _ = _compute_bt_vc(rows, pos)

        if bt_price_only is None:
            n_still_null_insufficient_price += 1
        elif bt_real is None:
            recovered_map[(symbol, date)] = bt_price_only
            n_recovered += 1
        else:
            n_still_null_unexplained += 1

    n_pop = len(pop)
    log(f"\nPopulation rows: {n_pop:,}")
    log(f"  base_tightness NULL in stock_signals for this (symbol,date): {n_null_before:,} "
        f"({n_null_before/n_pop*100:.1f}%)")
    log(f"  Recovered via price-only recomputation (volume-coupling casualties): {n_recovered:,}")
    log(f"  Still null — no stock_signals row at all for this date: {n_still_null_no_ss_row:,}")
    log(f"  Still null — insufficient price history (<20-day window): {n_still_null_insufficient_price:,}")
    log(f"  Still null — unexplained (flagged, not silently dropped): {n_still_null_unexplained:,}")

    null_after = n_null_before - n_recovered
    log(f"\nNull rate: before recovery {n_null_before/n_pop*100:.2f}% -> "
        f"after recovery {null_after/n_pop*100:.2f}%  "
        f"({n_recovered:,} rows recovered, {n_recovered/n_null_before*100:.1f}% of the null set)")

    return ss_lookup, recovered_map, prices_by_symbol, date_index_by_symbol


# ══════════════════════════════════════════════════════════════════════════
# PART C — three candidate tightness measures
# ══════════════════════════════════════════════════════════════════════════

def build_augmented_series(con, recovered_map):
    """Full per-symbol base_tightness series from stock_signals, with the
    Part-B-recovered population-row values overlaid on top (so both the
    'today' value AND any other row's trailing window that includes these
    dates benefit from the recovery -- bounded to exactly the rows Part B
    recovered, no wider recomputation of the general history)."""
    ss = pd.read_sql_query(
        "SELECT symbol, date, base_tightness FROM stock_signals ORDER BY symbol, date", con
    )
    series = {}
    for sym, g in ss.groupby("symbol"):
        dates = g["date"].tolist()
        vals = g["base_tightness"].tolist()
        series[sym] = [dates, vals]
    for (sym, date), val in recovered_map.items():
        if sym not in series:
            continue
        dates, vals = series[sym]
        pos = None
        lo, hi = 0, len(dates)
        while lo < hi:
            mid = (lo + hi) // 2
            if dates[mid] < date:
                lo = mid + 1
            else:
                hi = mid
        if lo < len(dates) and dates[lo] == date:
            vals[lo] = val
    return series


def part_c(pop, series):
    log("\n" + "=" * 100)
    log("PART C — candidate relative-tightness measures (pct_rank_252, pct_rank_756, zscore_252)")
    log("=" * 100)

    pct_252 = np.full(len(pop), np.nan)
    pct_756 = np.full(len(pop), np.nan)
    z_252 = np.full(len(pop), np.nan)
    today_bt = np.full(len(pop), np.nan)
    n_obs_252 = np.full(len(pop), 0, dtype=np.int64)
    n_obs_756 = np.full(len(pop), 0, dtype=np.int64)

    for sym, idx in pop.groupby("symbol").groups.items():
        s = series.get(sym)
        if s is None:
            continue
        dates, vals_list = s
        vals = np.array(vals_list, dtype=float)

        for i in idx:
            d = pop.at[i, "date"]
            pos = np.searchsorted(dates, d)
            if pos >= len(dates) or dates[pos] != d:
                continue
            v = vals[pos]
            today_bt[i] = v
            if np.isnan(v):
                continue

            w252 = vals[max(0, pos - 251):pos + 1]
            w252 = w252[~np.isnan(w252)]
            n_obs_252[i] = len(w252)
            if len(w252) >= MIN_TRAILING_OBS:
                pct_252[i] = (w252 <= v).mean() * 100
                if len(w252) >= 2:
                    std252 = w252.std(ddof=1)
                    z_252[i] = (v - w252.mean()) / std252 if std252 > 0 else np.nan

            w756 = vals[max(0, pos - 755):pos + 1]
            w756 = w756[~np.isnan(w756)]
            n_obs_756[i] = len(w756)
            if len(w756) >= MIN_TRAILING_OBS:
                pct_756[i] = (w756 <= v).mean() * 100

    pop["bbw_pct"] = today_bt
    pop["pct_rank_252"] = pct_252
    pop["pct_rank_756"] = pct_756
    pop["zscore_252"] = z_252
    pop["n_obs_252"] = n_obs_252
    pop["n_obs_756"] = n_obs_756

    for col in ["bbw_pct", "pct_rank_252", "pct_rank_756", "zscore_252"]:
        n_valid = pop[col].notna().sum()
        log(f"  {col}: {n_valid:,} / {len(pop):,} non-null ({n_valid/len(pop)*100:.1f}%)")

    return pop


# ══════════════════════════════════════════════════════════════════════════
# Forward returns (reused formula, not a new one)
# ══════════════════════════════════════════════════════════════════════════

def compute_fwd_return_10d(prices_by_symbol, date_index_by_symbol, pop):
    n = len(pop)
    fwd10 = np.full(n, np.nan)
    pop = pop.reset_index(drop=True)
    symbols_arr = pop["symbol"].values
    dates_arr = pop["date"].values

    for i in range(n):
        sym = symbols_arr[i]
        d = dates_arr[i]
        rows = prices_by_symbol.get(sym)
        idx_map = date_index_by_symbol.get(sym)
        if not rows or not idx_map:
            continue
        pos = idx_map.get(d)
        if pos is None:
            continue
        if pos + 10 >= len(rows):
            continue
        close_0 = rows[pos][1]
        if close_0 is None or close_0 == 0:
            continue
        close_10 = rows[pos + 10][1]
        if close_10 is None:
            continue
        fwd10[i] = (close_10 - close_0) / close_0 * 100

    pop["fwd_return_10d"] = fwd10
    return pop


# ══════════════════════════════════════════════════════════════════════════
# PART D — hypothesis test
# ══════════════════════════════════════════════════════════════════════════

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
    }


MEASURES = [
    ("pct_rank_252", True),   # tight = LOW percentile
    ("pct_rank_756", True),
    ("zscore_252", True),     # tight = LOW (negative) z-score
]


def part_d(pop):
    log("\n" + "=" * 100)
    log("PART D — does tightness predict fwd_return_10d? (three measures, tightest vs loosest quartile)")
    log("=" * 100)

    n_fwd = pop["fwd_return_10d"].notna().sum()
    log(f"\nfwd_return_10d valid: {n_fwd:,} / {len(pop):,} "
        f"({n_fwd/len(pop)*100:.1f}%) — window-not-closed / missing-price rows excluded")

    results = []
    for col, tight_low in MEASURES:
        r = quartile_test(pop, col, tight_low, "FULL POPULATION (all eras)")
        if r:
            results.append(r)

    log("\n" + "=" * 100)
    log("ERA CONSISTENCY (per measure)")
    log("=" * 100)
    for col, tight_low in MEASURES:
        log(f"\n### {col} ###")
        for era_name, start, end in ERAS:
            era_sub = pop[(pop["date"] >= start) & (pop["date"] <= end)]
            r = quartile_test(era_sub, col, tight_low, f"{era_name} ({start} -> {end})")
            if r:
                results.append(r)

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════
# WRITE — new staging table only
# ══════════════════════════════════════════════════════════════════════════

def write_staging(con, pop):
    cur = con.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {OUT_STAGING}")
    cur.execute(f"""
        CREATE TABLE {OUT_STAGING} (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            active_resistance REAL,
            bbw_pct REAL,
            pct_rank_252 REAL,
            pct_rank_756 REAL,
            zscore_252 REAL,
            n_obs_252 INTEGER,
            n_obs_756 INTEGER,
            fwd_return_10d REAL,
            PRIMARY KEY (symbol, date)
        )
    """)
    rows = list(pop[[
        "symbol", "date", "close", "active_resistance",
        "bbw_pct", "pct_rank_252", "pct_rank_756", "zscore_252",
        "n_obs_252", "n_obs_756", "fwd_return_10d",
    ]].itertuples(index=False, name=None))
    rows = [(sym, date, close, ar, bbw, p252, p756, z252, int(n252), int(n756), fwd)
            for (sym, date, close, ar, bbw, p252, p756, z252, n252, n756, fwd) in rows]
    cur.executemany(
        f"INSERT INTO {OUT_STAGING} "
        f"(symbol, date, close, active_resistance, bbw_pct, pct_rank_252, pct_rank_756, "
        f"zscore_252, n_obs_252, n_obs_756, fwd_return_10d) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    log(f"\nWrote {len(rows):,} rows to '{OUT_STAGING}'.")


def main():
    con = sqlite3.connect(DB)
    try:
        pop = part_a(con)
        ss_lookup, recovered_map, prices_by_symbol, date_index_by_symbol = part_b(con, pop)
        series = build_augmented_series(con, recovered_map)
        pop = part_c(pop, series)
        pop = compute_fwd_return_10d(prices_by_symbol, date_index_by_symbol, pop)
        results_df = part_d(pop)
        write_staging(con, pop)

        results_df.to_csv(
            Path(__file__).parent / "prebreakout_v2_partD_results.csv", index=False
        )
        log(f"\nPart D results also saved to prebreakout_v2_partD_results.csv "
            f"({len(results_df)} rows: 4 rows/measure x 3 measures = 12).")
    finally:
        con.close()


if __name__ == "__main__":
    main()
