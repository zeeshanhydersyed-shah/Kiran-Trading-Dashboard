"""
kibar_trend_filter.py
-------------------------
Corrected application of Kibar's 200-day trend filter: a hard EXCLUSION,
not a soft comparison. Primary convention is SMA (Kibar's own wording is
"200-day average"), with EMA reported alongside for comparison.

Reuses triangle_trend_alignment_stage1.csv (the earlier EMA pass: 190 up
/ 184 down candidates with >=200 bars of prior history, close_at_breakout
and ema_at_breakout already computed per candidate) as the base candidate
set and EMA source. SMA-200 computed fresh here, same window/history
requirement, same post-drop_placeholder_zero_bars price series.
"""

import sqlite3
import pandas as pd
import numpy as np

from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
SMA_WINDOW = 200

base = pd.read_csv("triangle_trend_alignment_stage1.csv")
print(f"Base candidate set (from earlier EMA pass): {len(base)} ({base['outcome'].value_counts().to_dict()})")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}
sma_vals = []

for _, cand in base.iterrows():
    sym = cand["symbol"]
    breakout_idx = int(cand["breakout_idx"])

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df = drop_placeholder_zero_bars(df)
        symbol_cache[sym] = df["close"].tolist()

    closes = symbol_cache[sym]
    if breakout_idx + 1 < SMA_WINDOW:
        sma_vals.append(np.nan)
    else:
        window = closes[breakout_idx - SMA_WINDOW + 1: breakout_idx + 1]
        sma_vals.append(sum(window) / SMA_WINDOW)

conn.close()
base["sma_at_breakout"] = sma_vals
print(f"SMA unresolvable (should be 0, same 200-bar requirement as the EMA pass): {base['sma_at_breakout'].isna().sum()}")

# ═══════════════════════════════════════════════════════════════════════
# 1. Hard exclusion filter, SMA primary, EMA for comparison
# ═══════════════════════════════════════════════════════════════════════
base["passes_sma"] = base.apply(
    lambda r: (r["close_at_breakout"] > r["sma_at_breakout"]) if r["outcome"] == "up"
    else (r["close_at_breakout"] < r["sma_at_breakout"]), axis=1
)
base["passes_ema"] = base.apply(
    lambda r: (r["close_at_breakout"] > r["ema_at_breakout"]) if r["outcome"] == "up"
    else (r["close_at_breakout"] < r["ema_at_breakout"]), axis=1
)

print(f"\n{'='*70}\n1. HARD EXCLUSION FILTER RESULTS\n{'='*70}")
for outc in ["up", "down"]:
    sub = base[base["outcome"] == outc]
    n_total = len(sub)
    n_sma_pass = sub["passes_sma"].sum()
    n_ema_pass = sub["passes_ema"].sum()
    print(f"\n--- {outc.upper()} (n={n_total}) ---")
    print(f"  SMA filter: {n_sma_pass} pass ({n_sma_pass/n_total*100:.1f}%), "
          f"{n_total-n_sma_pass} excluded ({(n_total-n_sma_pass)/n_total*100:.1f}%)")
    print(f"  EMA filter: {n_ema_pass} pass ({n_ema_pass/n_total*100:.1f}%), "
          f"{n_total-n_ema_pass} excluded ({(n_total-n_ema_pass)/n_total*100:.1f}%)")
    disagree = sub[sub["passes_sma"] != sub["passes_ema"]]
    sma_only = sub[(sub["passes_sma"]) & (~sub["passes_ema"])]
    ema_only = sub[(~sub["passes_sma"]) & (sub["passes_ema"])]
    print(f"  Disagreement: {len(disagree)} candidates ({len(disagree)/n_total*100:.1f}%) -- "
          f"{len(sma_only)} pass SMA but fail EMA, {len(ema_only)} pass EMA but fail SMA")

base.to_csv("C:/Users/Lenovo/psx_pipeline/kibar_filter_base.csv", index=False)

# ═══════════════════════════════════════════════════════════════════════
# 2. Recompute raw_pct_move at all 5 horizons for SMA survivors
# ═══════════════════════════════════════════════════════════════════════
mm = pd.read_csv("triangle_measured_move_results.csv")
mm = mm[(~mm["excluded_insufficient_data"]) & (mm["outcome"].isin(["up", "down"]))]

sma_survivors = base[base["passes_sma"]][["symbol", "start", "end", "outcome"]]

unfiltered = {
    "up": {10: (4.64, 2.12, 205), 20: (8.18, 4.52, 201), 30: (10.51, 5.63, 198), 60: (14.00, 7.35, 198), 90: (14.83, 7.12, 198)},
    "down": {10: (2.85, 2.83, 188), 20: (5.04, 3.95, 188), 30: (5.21, 3.92, 188), 60: (5.77, 5.63, 188), 90: (3.08, 6.70, 187)},
}

print(f"\n{'='*70}\n2. SMA-FILTERED RESULTS, ALL 5 HORIZONS, vs UNFILTERED\n{'='*70}")
horizon_results = {}
for outc in ["up", "down"]:
    print(f"\n--- {outc.upper()} ---")
    surv = sma_survivors[sma_survivors["outcome"] == outc]
    for h in [10, 20, 30, 60, 90]:
        sub = mm[(mm["horizon"] == h) & (mm["outcome"] == outc)].merge(
            surv[["symbol", "start", "end"]], on=["symbol", "start", "end"], how="inner"
        )
        n = len(sub)
        mean_v = sub["raw_pct_move"].mean()
        median_v = sub["raw_pct_move"].median()
        u_mean, u_median, u_n = unfiltered[outc][h]
        flag = "  [n<30, TOO THIN]" if n < 30 else ""
        direction = "IMPROVES" if mean_v > u_mean and median_v > u_median else \
                    "WORSENS" if mean_v < u_mean and median_v < u_median else "MIXED"
        print(f"  {h}d: filtered mean={mean_v:+.2f}% median={median_v:+.2f}% n={n}{flag}   "
              f"| unfiltered mean={u_mean:+.2f}% median={u_median:+.2f}% n={u_n}   -> {direction}")
        horizon_results[(outc, h)] = (mean_v, median_v, n)

# ═══════════════════════════════════════════════════════════════════════
# 3a. Outlier concentration, 60d, SMA survivors
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\n3a. OUTLIER CONCENTRATION, 60d HORIZON, SMA SURVIVORS\n{'='*70}")
for outc in ["up", "down"]:
    surv = sma_survivors[sma_survivors["outcome"] == outc]
    sub = mm[(mm["horizon"] == 60) & (mm["outcome"] == outc)].merge(
        surv[["symbol", "start", "end"]], on=["symbol", "start", "end"], how="inner"
    ).sort_values("raw_pct_move", ascending=False)
    n = len(sub)
    total = sub["raw_pct_move"].sum()
    top5 = sub.head(5)
    top5_sum = top5["raw_pct_move"].sum()
    print(f"\n--- {outc.upper()} (n={n}, total summed raw_pct_move={total:.1f}%) ---")
    print(top5[["symbol", "start", "end", "raw_pct_move"]].to_string(index=False))
    print(f"  top 5 contribute {top5_sum:.1f}% of {total:.1f}% total ({top5_sum/total*100:.1f}%)")
    ex_top5 = sub.iloc[5:]
    print(f"  WITH top 5:    mean={sub['raw_pct_move'].mean():+.2f}%  median={sub['raw_pct_move'].median():+.2f}%  n={n}")
    print(f"  WITHOUT top 5: mean={ex_top5['raw_pct_move'].mean():+.2f}%  median={ex_top5['raw_pct_move'].median():+.2f}%  n={len(ex_top5)}")

# ═══════════════════════════════════════════════════════════════════════
# 3b. Temporal split, 60d, SMA survivors
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\n3b. TEMPORAL SPLIT, 60d HORIZON, SMA SURVIVORS\n{'='*70}")
dates = pd.read_csv("triangle_breakout_dates.csv")
dates["breakout_date"] = pd.to_datetime(dates["breakout_date"])
SPLIT = pd.Timestamp("2017-02-07")
dates["era"] = dates["breakout_date"].apply(lambda d: "A" if d < SPLIT else "B")

for outc in ["up", "down"]:
    surv = sma_survivors[sma_survivors["outcome"] == outc]
    sub = mm[(mm["horizon"] == 60) & (mm["outcome"] == outc)].merge(
        surv[["symbol", "start", "end"]], on=["symbol", "start", "end"], how="inner"
    ).merge(dates[["symbol", "start", "end", "era"]], on=["symbol", "start", "end"], how="left")
    print(f"\n--- {outc.upper()} ---")
    for era in ["A", "B"]:
        cell = sub[sub["era"] == era]
        n = len(cell)
        flag = "  [n<30, TOO THIN]" if n < 30 else ""
        if n == 0:
            print(f"  Era {era}: n=0{flag}")
            continue
        print(f"  Era {era}: mean={cell['raw_pct_move'].mean():+.2f}%  median={cell['raw_pct_move'].median():+.2f}%  n={n}{flag}")
