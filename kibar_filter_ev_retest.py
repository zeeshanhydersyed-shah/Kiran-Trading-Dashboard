"""
kibar_filter_ev_retest.py
-----------------------------
TASK 1: re-tests Kibar's 200-day SMA trend filter against the ACTUAL
tradeable EV/R-multiple framework (full population n=518, LFD stop,
-3.0R floor, friction+CGT costs) -- not raw gain% among winners only,
which was the earlier session's methodology error.

SMA-200 recomputed FRESH for all 518 candidates (not reused from the
prior up/down-only 374-candidate file, which used a slightly different
population -- 190/184 there vs 196/181 up/down here, plus this task also
needs sequential/whipsaw candidates the prior file never covered). Same
convention throughout this study: post drop_placeholder_zero_bars price
series, SMA-200 = mean of the trailing 200 closes ending at and including
breakout_idx, requires >=200 bars of prior history or excluded (not
approximated).
"""

import sqlite3
import pandas as pd
import numpy as np

from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
SMA_WINDOW = 200
FLOOR = -3.0
RISK_FRAC = 0.01
FRICTION_PCT = 0.20
CGT_RATE = 0.15

ev = pd.read_csv("triangle_ev_realistic_r.csv")
print(f"Full EV population: n={len(ev)}  {ev['outcome'].value_counts().to_dict()}")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

close_vals, sma_vals = [], []
for _, cand in ev.iterrows():
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
    if breakout_idx >= len(closes):
        close_vals.append(np.nan)
        sma_vals.append(np.nan)
        continue
    close_vals.append(closes[breakout_idx])
    if breakout_idx + 1 < SMA_WINDOW:
        sma_vals.append(np.nan)
    else:
        window = closes[breakout_idx - SMA_WINDOW + 1: breakout_idx + 1]
        sma_vals.append(sum(window) / SMA_WINDOW)

conn.close()
ev["close_at_breakout_check"] = close_vals
ev["sma_at_breakout"] = sma_vals

n_no_sma = ev["sma_at_breakout"].isna().sum()
print(f"Excluded, insufficient history for 200-day SMA: {n_no_sma}")

ev_valid = ev[ev["sma_at_breakout"].notna()].copy()
print(f"Candidates with a valid SMA: {len(ev_valid)}  {ev_valid['outcome'].value_counts().to_dict()}")

# sanity: close_at_breakout_check should match entry_price (both = closes[breakout_idx])
mismatch = (ev_valid["close_at_breakout_check"] - ev_valid["entry_price"]).abs() > 0.01
print(f"entry_price vs freshly-fetched close mismatch (sanity check): {mismatch.sum()}")

ev_valid["passes_sma"] = ev_valid.apply(
    lambda r: (r["entry_price"] > r["sma_at_breakout"]) if r["direction"] == "up"
    else (r["entry_price"] < r["sma_at_breakout"]), axis=1
)

print(f"\n{'='*70}\nFILTER RESULT\n{'='*70}")
n_total = len(ev_valid)
n_pass = ev_valid["passes_sma"].sum()
print(f"Passes: {n_pass}/{n_total} ({n_pass/n_total*100:.1f}%)")
print(f"By direction:")
for d, grp in ev_valid.groupby("direction"):
    p = grp["passes_sma"].sum()
    print(f"  {d}: {p}/{len(grp)} ({p/len(grp)*100:.1f}%)")

survivors = ev_valid[ev_valid["passes_sma"]].copy()
survivors["R_final"] = survivors["realized_R_realistic"].clip(lower=FLOOR)
survivors["risk_pct_of_price"] = survivors["r_lfd_denom"] / survivors["entry_price"] * 100
survivors["friction_in_R"] = FRICTION_PCT / survivors["risk_pct_of_price"]
survivors["R_net_friction_cgt"] = survivors.apply(
    lambda r: (r["R_final"] * (1 - CGT_RATE) if r["R_final"] > 0 else r["R_final"]) - r["friction_in_R"], axis=1)

survivors.to_csv("C:/Users/Lenovo/psx_pipeline/kibar_ev_survivors.csv", index=False)

print(f"\n{'='*70}\nEV COMPARISON: SMA-FILTERED vs BASELINE (unfiltered n=518)\n{'='*70}")
n = len(survivors)
gross_mean = survivors["R_final"].mean()
gross_median = survivors["R_final"].median()
net_mean = survivors["R_net_friction_cgt"].mean()
win_rate = (survivors["R_final"] > 0).mean() * 100
print(f"SMA-filtered (n={n}):")
print(f"  gross mean R:  {gross_mean:.4f}  -> {gross_mean*RISK_FRAC*100:+.3f}%/trade")
print(f"  median R:      {gross_median:.4f}")
print(f"  net of friction+CGT mean R: {net_mean:.4f} -> {net_mean*RISK_FRAC*100:+.3f}%/trade")
print(f"  win rate: {win_rate:.1f}%")
print(f"\nBASELINE (unfiltered, n=518): gross mean +1.277R (+1.28%/trade), median -1.00R, "
      f"WR 18.1%, net of costs +0.85%/trade")

# ═══════════════════════════════════════════════════════════════════════
# Outlier concentration
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\nOUTLIER CONCENTRATION, SMA-FILTERED SURVIVORS\n{'='*70}")
srt = survivors.sort_values("R_final", ascending=False)
total = srt["R_final"].sum()
top5 = srt.head(5)
top5_sum = top5["R_final"].sum()
print(top5[["symbol", "start", "end", "direction", "R_final"]].to_string(index=False))
print(f"top 5 contribute {top5_sum:.2f}R of {total:.2f}R total ({top5_sum/total*100:.1f}%)")
ex_top5 = srt.iloc[5:]
print(f"WITH top 5:    mean={srt['R_final'].mean():.4f}  n={len(srt)}")
print(f"WITHOUT top 5: mean={ex_top5['R_final'].mean():.4f}  n={len(ex_top5)}")

# ═══════════════════════════════════════════════════════════════════════
# Temporal split
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\nTEMPORAL SPLIT, SMA-FILTERED SURVIVORS\n{'='*70}")
dates = pd.read_csv("triangle_breakout_dates.csv")
dates["breakout_date"] = pd.to_datetime(dates["breakout_date"])
SPLIT = pd.Timestamp("2017-02-07")
dates["era"] = dates["breakout_date"].apply(lambda d: "A" if d < SPLIT else "B")
surv_dated = survivors.merge(dates[["symbol", "start", "end", "era"]], on=["symbol", "start", "end"], how="left")

for era in ["A", "B"]:
    cell = surv_dated[surv_dated["era"] == era]
    n_c = len(cell)
    flag = "  [n<30, TOO THIN]" if n_c < 30 else ""
    if n_c == 0:
        print(f"Era {era}: n=0{flag}")
        continue
    print(f"Era {era}: mean R={cell['R_final'].mean():.4f}  median R={cell['R_final'].median():.4f}  "
          f"win rate={(cell['R_final']>0).mean()*100:.1f}%  n={n_c}{flag}")
