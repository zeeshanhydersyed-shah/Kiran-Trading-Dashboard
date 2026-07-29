"""
sector_rs_rank_prescreen_test.py — A2: tests sector_rs_rank <= 5 as a PRE-SCREEN
filter (independent of breakout timing entirely — no bos_flag, active_resistance,
or breakout_event conditioning), matching the Explorer page's Weinstein Watchlist
toggle's own cutoff.

Distinct from:
  - RS_LEADER_SECTOR (a different, standalone, already-dead setup type) -- not touched.
  - S-002 (RS as a POST-breakout quality score) -- not touched, not re-run.

READ-ONLY. No production writes. fwd_return_10d is computed fresh (stock_signals
has no such column -- it's a setup_log-only field, and this population is
explicitly NOT setup_log-conditioned) using the exact same formula
compute_forward_returns.py already uses, sourced from prices_adjusted -- reused
verbatim, not reinvented, same as S-002.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DB = str(Path(__file__).parent / "psx_data.db")

ERAS = [
    ("Development", "2015-01-01", "2019-12-31"),
    ("Validation",  "2020-01-01", "2022-12-31"),
    ("OOS",         "2023-01-01", "2026-12-31"),
]


def log(msg):
    print(msg, flush=True)


def load_population(con):
    df = pd.read_sql_query(
        """
        SELECT symbol, date, sector_rs_rank
        FROM stock_signals
        WHERE avg_vol_10d > 200000
          AND sector_rs_rank IS NOT NULL
        ORDER BY symbol, date
        """,
        con,
    )
    return df


def compute_fwd_return_10d(con, df):
    symbols = df["symbol"].unique().tolist()
    price_seq = {}
    date_index = {}
    cur = con.cursor()
    for sym in symbols:
        rows = cur.execute(
            "SELECT date, close FROM prices_adjusted WHERE symbol=? ORDER BY date ASC", (sym,)
        ).fetchall()
        price_seq[sym] = rows
        date_index[sym] = {d: (i, c) for i, (d, c) in enumerate(rows)}

    n = len(df)
    fwd10 = np.full(n, np.nan)
    window_not_closed = np.zeros(n, dtype=bool)
    no_price_row = np.zeros(n, dtype=bool)

    df = df.reset_index(drop=True)
    symbols_arr = df["symbol"].values
    dates_arr = df["date"].values

    for i in range(n):
        sym = symbols_arr[i]
        d = dates_arr[i]
        seq = price_seq.get(sym)
        idx_map = date_index.get(sym)
        if not seq or not idx_map:
            no_price_row[i] = True
            continue
        entry = idx_map.get(d)
        if entry is None:
            no_price_row[i] = True
            continue
        idx, close_0 = entry
        if idx + 10 >= len(seq):
            window_not_closed[i] = True
            continue
        if close_0 is None or close_0 == 0:
            no_price_row[i] = True
            continue
        close_10 = seq[idx + 10][1]
        if close_10 is None:
            no_price_row[i] = True
            continue
        fwd10[i] = (close_10 - close_0) / close_0 * 100
        if i % 50000 == 0 and i > 0:
            log(f"  ... {i:,}/{n:,} rows processed")

    df["fwd_return_10d"] = fwd10
    df["_window_not_closed"] = window_not_closed
    df["_no_price_row"] = no_price_row
    return df


def cliffs_delta_via_mwu(x, y):
    """Efficient Cliff's delta (x vs y) via the MWU U-statistic, exact with ties,
    avoiding an O(n1*n2) double loop at this population's scale."""
    u1, _ = stats.mannwhitneyu(x, y, alternative="two-sided")
    n1, n2 = len(x), len(y)
    return (2 * u1) / (n1 * n2) - 1


def run_split_test(sub, label):
    g_low = sub[sub["sector_rs_rank"] <= 5]["fwd_return_10d"]   # <=5 = stronger sector
    g_high = sub[sub["sector_rs_rank"] > 5]["fwd_return_10d"]

    log(f"\n{'='*100}")
    log(f"{label}")
    log(f"{'='*100}")
    log(f"N total (valid fwd_return_10d): {len(sub):,}")
    log(f"  sector_rs_rank <= 5: N={len(g_low):,}  mean={g_low.mean():+.4f}%  "
        f"median={g_low.median():+.4f}%  std={g_low.std():.4f}")
    log(f"  sector_rs_rank >  5: N={len(g_high):,}  mean={g_high.mean():+.4f}%  "
        f"median={g_high.median():+.4f}%  std={g_high.std():.4f}")

    if len(g_low) < 2 or len(g_high) < 2:
        log("  Too few rows in one group for a significance test.")
        return

    u_two, p_two = stats.mannwhitneyu(g_low, g_high, alternative="two-sided")
    _, p_one = stats.mannwhitneyu(g_low, g_high, alternative="greater")
    t_stat, p_t = stats.ttest_ind(g_low, g_high, equal_var=False)
    delta = cliffs_delta_via_mwu(g_low, g_high)

    log(f"\n  Mann-Whitney U, two-sided: p = {p_two:.6f}")
    log(f"  Mann-Whitney U, one-sided (<=5 > >5, matching the live filter's implicit "
        f"assumption): p = {p_one:.6f}")
    log(f"  Welch's t-test (<=5 vs >5 means), two-sided: t = {t_stat:.4f}, p = {p_t:.6f}")
    log(f"  Cliff's delta (<=5 vs >5): {delta:.4f}")
    mean_delta = g_low.mean() - g_high.mean()
    log(f"  Mean delta (<=5 minus >5): {mean_delta:+.4f} percentage points")


def per_rank_breakdown(sub):
    log(f"\n{'='*100}")
    log("PER-RANK-VALUE BREAKDOWN (full population, all eras)")
    log(f"{'='*100}")
    rows = []
    for r in range(1, 10):
        g = sub[sub["sector_rs_rank"] == r]["fwd_return_10d"]
        if len(g) == 0:
            continue
        rows.append({"sector_rs_rank": str(r), "n": len(g), "mean_fwd10": g.mean(),
                     "median_fwd10": g.median(), "std_fwd10": g.std()})
    g10 = sub[sub["sector_rs_rank"] >= 10]["fwd_return_10d"]
    if len(g10) > 0:
        rows.append({"sector_rs_rank": "10+", "n": len(g10), "mean_fwd10": g10.mean(),
                     "median_fwd10": g10.median(), "std_fwd10": g10.std()})
    rep = pd.DataFrame(rows)
    log(rep.to_string(index=False))


def main():
    con = sqlite3.connect(DB)
    try:
        pop = load_population(con)
        log(f"Population before fwd_return_10d computation: {len(pop):,} rows, "
            f"{pop['symbol'].nunique()} symbols, date range {pop['date'].min()} -> {pop['date'].max()}")

        withfwd = compute_fwd_return_10d(con, pop)
        n_valid = withfwd["fwd_return_10d"].notna().sum()
        n_window_open = withfwd["_window_not_closed"].sum()
        n_no_price = withfwd["_no_price_row"].sum()
        log(f"\nfwd_return_10d computed (compute_forward_returns.py formula, from prices_adjusted):")
        log(f"  Valid: {n_valid:,} / {len(withfwd):,}")
        log(f"  Window not yet closed: {n_window_open:,}")
        log(f"  No matching prices_adjusted row: {n_no_price:,}")

        sub = withfwd.dropna(subset=["fwd_return_10d"]).copy()

        run_split_test(sub, "FULL POPULATION (all eras combined) — sector_rs_rank <= 5 vs > 5")

        per_rank_breakdown(sub)

        log(f"\n{'='*100}")
        log("ERA-CONSISTENCY CHECK")
        log(f"{'='*100}")
        for era_name, start, end in ERAS:
            era_sub = sub[(sub["date"] >= start) & (sub["date"] <= end)]
            run_split_test(era_sub, f"{era_name} ({start} -> {end})")

    finally:
        con.close()


if __name__ == "__main__":
    main()
