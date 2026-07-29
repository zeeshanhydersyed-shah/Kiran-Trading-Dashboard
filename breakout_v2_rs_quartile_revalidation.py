"""
breakout_v2_rs_quartile_revalidation.py — Re-validates the RS-rank Q1-Q4 split
WITHIN the BREAKOUT population (cited prior figures: Q1 ~ -0.20%, Q4 ~ +2.07%
fwd_return_10d), against the corrected BREAKOUT V2 population
(stock_signals_breakout_v2_staging_full WHERE breakout_event=1) instead of the
old bos_flag=1 / 243-symbol-snapshot population.

READ-ONLY. No production writes. Does not touch RS_LEADER_MARKET/RS_LEADER_SECTOR.
No tightness/BBW% filter applied (RS-rank only, isolated, per task).

fwd_return_10d is computed here (not present on stock_signals_breakout_v2_staging_full)
using the EXACT formula compute_forward_returns.py already uses for setup_log:
(close at entry+10 trading days - close at entry) / close at entry * 100,
sourced from prices_adjusted. Reused verbatim, not reinvented.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

DB = str(Path(__file__).parent / "psx_data.db")


def log(msg):
    print(msg, flush=True)


def load_population(con):
    df = pd.read_sql_query(
        "SELECT symbol, date, close, active_resistance FROM stock_signals_breakout_v2_staging_full "
        "WHERE breakout_event = 1 ORDER BY symbol, date",
        con,
    )
    return df


def join_rs(con, pop):
    rs = pd.read_sql_query(
        "SELECT symbol, date, rs_score_20, sector_rs_rank FROM stock_signals",
        con,
    )
    merged = pop.merge(rs, on=["symbol", "date"], how="left")
    return merged


def compute_fwd_return_10d(con, df):
    """Mirrors compute_forward_returns.py's compute_returns(): close at entry+10
    trading days vs close at entry, from prices_adjusted, entry date's own close."""
    symbols = df["symbol"].unique().tolist()
    price_seq = {}
    cur = con.cursor()
    for sym in symbols:
        rows = cur.execute(
            "SELECT date, close FROM prices_adjusted WHERE symbol=? ORDER BY date ASC", (sym,)
        ).fetchall()
        price_seq[sym] = rows

    fwd10 = np.full(len(df), np.nan)
    window_not_closed = np.zeros(len(df), dtype=bool)
    no_price_row = np.zeros(len(df), dtype=bool)

    df = df.reset_index(drop=True)
    for i, row in df.iterrows():
        seq = price_seq.get(row["symbol"])
        if not seq:
            no_price_row[i] = True
            continue
        date_index = {d: (j, c) for j, (d, c) in enumerate(seq)}
        entry = date_index.get(row["date"])
        if entry is None:
            no_price_row[i] = True
            continue
        idx, close_0 = entry
        if idx + 10 >= len(seq):
            window_not_closed[i] = True
            continue
        if close_0 == 0 or close_0 is None:
            no_price_row[i] = True
            continue
        close_10 = seq[idx + 10][1]
        if close_10 is None:
            no_price_row[i] = True
            continue
        fwd10[i] = (close_10 - close_0) / close_0 * 100

    df["fwd_return_10d"] = fwd10
    df["_window_not_closed"] = window_not_closed
    df["_no_price_row"] = no_price_row
    return df


def quartile_report(df, var_col, label):
    sub = df.dropna(subset=[var_col, "fwd_return_10d"]).copy()
    n_total = len(sub)
    log(f"\n{'='*100}")
    log(f"QUARTILE SPLIT — {label} ({var_col})")
    log(f"{'='*100}")
    log(f"Rows with non-null {var_col} AND non-null fwd_return_10d: {n_total}")
    if n_total < 20:
        log(f"  Too few rows for a meaningful quartile split (n={n_total}) — reporting raw rows only.")
        log(sub[["symbol", "date", var_col, "fwd_return_10d"]].to_string(index=False))
        return

    raw_bins, bins = pd.qcut(sub[var_col], 4, retbins=True, duplicates="drop")
    n_bins_actual = len(bins) - 1
    if n_bins_actual < 4:
        log(f"  NOTE: {var_col} has low enough cardinality that equal-count quartiles collapse to "
            f"{n_bins_actual} groups (duplicate bin edges dropped) instead of 4 -- flagging rather "
            f"than forcing 4 artificial bins on a coarse integer-ranked variable.")
    labels = [f"Q{i+1}" for i in range(n_bins_actual)]
    sub["quartile"] = raw_bins.cat.rename_categories(labels)
    log(f"Equal-count quantile boundaries (pandas qcut, requested 4, got {n_bins_actual}) on {var_col}: "
        f"{[round(b, 3) for b in bins]}")

    rows = []
    for q in labels:
        qsub = sub[sub["quartile"] == q]
        if len(qsub) == 0:
            continue
        rows.append({
            "quartile": q, "n": len(qsub),
            "mean_fwd10": qsub["fwd_return_10d"].mean(),
            "median_fwd10": qsub["fwd_return_10d"].median(),
            "std_fwd10": qsub["fwd_return_10d"].std(),
            f"{var_col}_range": f"[{qsub[var_col].min():.2f}, {qsub[var_col].max():.2f}]",
        })
    rep = pd.DataFrame(rows)
    log(rep.to_string(index=False))

    q1 = sub[sub["quartile"] == "Q1"]["fwd_return_10d"]
    q4 = sub[sub["quartile"] == labels[-1]]["fwd_return_10d"]
    if len(q1) > 0 and len(q4) > 0:
        u_stat, p_two = stats.mannwhitneyu(q1, q4, alternative="two-sided")
        _, p_one = stats.mannwhitneyu(q4, q1, alternative="greater")  # pre-registered-style Q4>Q1
        t_stat, p_t = stats.ttest_ind(q4, q1, equal_var=False)
        # Cliff's delta (Q4 vs Q1), matching H-002's reported statistic style
        n1, n2 = len(q1), len(q4)
        greater = sum(1 for a in q4 for b in q1 if a > b)
        less = sum(1 for a in q4 for b in q1 if a < b)
        cliffs_delta = (greater - less) / (n1 * n2)
        log(f"\nQ1 vs {labels[-1]} significance tests:")
        log(f"  Mann-Whitney U, two-sided: p = {p_two:.6f}")
        log(f"  Mann-Whitney U, one-sided ({labels[-1]} > Q1, pre-registered-direction style per H-002): p = {p_one:.6f}")
        log(f"  Welch's t-test ({labels[-1]} vs Q1 means), two-sided: t = {t_stat:.4f}, p = {p_t:.6f}")
        log(f"  Cliff's delta ({labels[-1]} vs Q1): {cliffs_delta:.4f}")
    return rep


def main():
    con = sqlite3.connect(DB)
    try:
        pop = load_population(con)
        log(f"STEP 1-3: Population = stock_signals_breakout_v2_staging_full WHERE breakout_event=1")
        log(f"  Total rows: {len(pop):,}")
        log(f"  Distinct symbols: {pop['symbol'].nunique()}")
        log(f"  Date range: {pop['date'].min()} -> {pop['date'].max()}")

        merged = join_rs(con, pop)
        n_rs_match = merged["rs_score_20"].notna().sum()
        n_sec_match = merged["sector_rs_rank"].notna().sum()
        n_either_match = merged[["rs_score_20"]].notna().any(axis=1).sum()
        n_no_ss_row_at_all = merged["rs_score_20"].isna().sum()  # includes both "no row" and "row but rs null"
        log(f"\nSTEP 2: Join to stock_signals on (symbol, date)")
        log(f"  rs_score_20 matched (non-null): {n_rs_match:,} / {len(merged):,} "
            f"({n_rs_match/len(merged)*100:.1f}%)")
        log(f"  sector_rs_rank matched (non-null): {n_sec_match:,} / {len(merged):,} "
            f"({n_sec_match/len(merged)*100:.1f}%)")
        log(f"  Rows with NEITHER matched (no stock_signals row, or row exists but both fields null): "
            f"{(merged['rs_score_20'].isna() & merged['sector_rs_rank'].isna()).sum():,}")

        withfwd = compute_fwd_return_10d(con, merged)
        n_fwd_ok = withfwd["fwd_return_10d"].notna().sum()
        n_window_open = withfwd["_window_not_closed"].sum()
        n_no_price = withfwd["_no_price_row"].sum()
        log(f"\nfwd_return_10d computed (compute_forward_returns.py formula, from prices_adjusted):")
        log(f"  Valid fwd_return_10d: {n_fwd_ok:,} / {len(withfwd):,}")
        log(f"  Window not yet closed (entry+10 trading days beyond available price history): {n_window_open:,}")
        log(f"  No matching prices_adjusted row at entry date: {n_no_price:,}")

        quartile_report(withfwd, "rs_score_20", "rs_score_20 (higher = stronger RS)")
        quartile_report(withfwd, "sector_rs_rank", "sector_rs_rank (LOWER rank = stronger sector; "
                         "Q1 = lowest ranks = strongest sectors)")

    finally:
        con.close()


if __name__ == "__main__":
    main()
