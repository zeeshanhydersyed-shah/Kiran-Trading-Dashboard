"""
fixed_pct_comparison.py
---------------------------
Real-data run of the fixed 1:2 (2% stop / 4% target) scheme on the full
n=518 population, both with and without Kibar's SMA trend filter
(reusing kibar_ev_survivors.csv's pass/fail flags from Task 1, same
survivor set). Same robustness checks as everywhere else in this study.
"""

import sqlite3
import pandas as pd

from research_filters import drop_placeholder_zero_bars
from fixed_pct_stop_target import walk_forward_fixed_pct

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
RISK_FRAC = 0.01

ev = pd.read_csv("triangle_ev_realistic_r.csv")
print(f"Full population: n={len(ev)}")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}
rows = []

for _, cand in ev.iterrows():
    sym = cand["symbol"]
    breakout_idx = int(cand["breakout_idx"])
    direction = cand["direction"]

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df = drop_placeholder_zero_bars(df)
        symbol_cache[sym] = (df["high"].tolist(), df["low"].tolist(), df["close"].tolist())

    highs, lows, closes = symbol_cache[sym]
    if breakout_idx >= len(closes) - 1:
        continue

    r = walk_forward_fixed_pct(closes, highs, lows, breakout_idx, direction)
    rows.append({
        "symbol": sym, "start": cand["start"], "end": cand["end"],
        "outcome": cand["outcome"], "direction": direction, "breakout_idx": breakout_idx,
        "entry_price": r.entry_price, "stop_price": r.stop_price, "target_price": r.target_price,
        "exit_bar": r.exit_bar, "exit_type": r.exit_type, "realized_R": r.realized_R,
    })

conn.close()

fixed = pd.DataFrame(rows)
fixed.to_csv("C:/Users/Lenovo/psx_pipeline/fixed_pct_results.csv", index=False)
print(f"Walked forward: n={len(fixed)}")

print(f"\n{'='*70}\nFIXED 1:2 SCHEME, FULL POPULATION, NO FILTER (n={len(fixed)})\n{'='*70}")
print(f"exit_type breakdown:")
print(fixed["exit_type"].value_counts().to_string())
win_rate = (fixed["exit_type"] == "target").mean() * 100
mean_R = fixed["realized_R"].mean()
median_R = fixed["realized_R"].median()
print(f"\nwin rate (target hit before stop): {win_rate:.1f}%")
print(f"mean R: {mean_R:.4f}  -> {mean_R*RISK_FRAC*100:+.3f}%/trade")
print(f"median R: {median_R:.4f}")

# outlier concentration
srt = fixed.sort_values("realized_R", ascending=False)
total = srt["realized_R"].sum()
top5 = srt.head(5)
top5_sum = top5["realized_R"].sum()
print(f"\n--- outlier concentration ---")
print(top5[["symbol", "start", "end", "direction", "realized_R"]].to_string(index=False))
print(f"top 5 contribute {top5_sum:.2f}R of {total:.2f}R total ({top5_sum/total*100:.1f}%)")
ex_top5 = srt.iloc[5:]
print(f"WITH top 5: mean={srt['realized_R'].mean():.4f}   WITHOUT top 5: mean={ex_top5['realized_R'].mean():.4f}  n={len(ex_top5)}")

# temporal split
dates = pd.read_csv("triangle_breakout_dates.csv")
dates["breakout_date"] = pd.to_datetime(dates["breakout_date"])
SPLIT = pd.Timestamp("2017-02-07")
dates["era"] = dates["breakout_date"].apply(lambda d: "A" if d < SPLIT else "B")
fixed_dated = fixed.merge(dates[["symbol", "start", "end", "era"]], on=["symbol", "start", "end"], how="left")
print(f"\n--- temporal split ---")
for era in ["A", "B"]:
    cell = fixed_dated[fixed_dated["era"] == era]
    n_c = len(cell)
    flag = "  [n<30, TOO THIN]" if n_c < 30 else ""
    print(f"Era {era}: mean R={cell['realized_R'].mean():.4f}  median R={cell['realized_R'].median():.4f}  "
          f"win rate={(cell['exit_type']=='target').mean()*100:.1f}%  n={n_c}{flag}")

# ═══════════════════════════════════════════════════════════════════════
# Fixed 1:2 WITH Kibar filter applied
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\nFIXED 1:2 SCHEME, WITH KIBAR SMA FILTER\n{'='*70}")
survivors_keys = pd.read_csv("kibar_ev_survivors.csv")[["symbol", "start", "end"]]
fixed_filtered = fixed.merge(survivors_keys, on=["symbol", "start", "end"], how="inner")
n = len(fixed_filtered)
print(f"n={n}")
win_rate_f = (fixed_filtered["exit_type"] == "target").mean() * 100
mean_R_f = fixed_filtered["realized_R"].mean()
median_R_f = fixed_filtered["realized_R"].median()
print(f"win rate: {win_rate_f:.1f}%")
print(f"mean R: {mean_R_f:.4f} -> {mean_R_f*RISK_FRAC*100:+.3f}%/trade")
print(f"median R: {median_R_f:.4f}")

srt_f = fixed_filtered.sort_values("realized_R", ascending=False)
total_f = srt_f["realized_R"].sum()
top5_f = srt_f.head(5)
top5_f_sum = top5_f["realized_R"].sum()
print(f"\ntop 5 contribute {top5_f_sum:.2f}R of {total_f:.2f}R total ({top5_f_sum/total_f*100:.1f}%)")
print(f"WITH top 5: mean={srt_f['realized_R'].mean():.4f}   WITHOUT top 5: mean={srt_f.iloc[5:]['realized_R'].mean():.4f}  n={len(srt_f)-5}")

fixed_filtered_dated = fixed_filtered.merge(dates[["symbol", "start", "end", "era"]], on=["symbol", "start", "end"], how="left")
print(f"\n--- temporal split, filtered ---")
for era in ["A", "B"]:
    cell = fixed_filtered_dated[fixed_filtered_dated["era"] == era]
    n_c = len(cell)
    flag = "  [n<30, TOO THIN]" if n_c < 30 else ""
    print(f"Era {era}: mean R={cell['realized_R'].mean():.4f}  n={n_c}{flag}")

fixed_filtered.to_csv("C:/Users/Lenovo/psx_pipeline/fixed_pct_results_filtered.csv", index=False)

# ═══════════════════════════════════════════════════════════════════════
# Final 4-way summary
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*70}\nFINAL 4-WAY SUMMARY\n{'='*70}")
print(f"{'Scheme':<28}{'n':>6}{'mean R':>10}{'%/trade':>10}{'median R':>10}{'win rate':>10}")
print(f"{'LFD-dynamic, no filter':<28}{518:>6}{1.277:>10.3f}{'+1.28%':>10}{-1.00:>10.2f}{'18.1%':>10}")

kb = pd.read_csv("kibar_ev_survivors.csv")
kb_mean = kb["R_final"].mean()
kb_median = kb["R_final"].median()
kb_wr = (kb["R_final"] > 0).mean() * 100
kb_pct = kb_mean * RISK_FRAC * 100
print(f"{'LFD-dynamic, filtered':<28}{len(kb):>6}{kb_mean:>10.3f}{kb_pct:>+9.2f}%{kb_median:>10.2f}{kb_wr:>9.1f}%")

fixed_pct = mean_R * RISK_FRAC * 100
print(f"{'Fixed 1:2, no filter':<28}{len(fixed):>6}{mean_R:>10.3f}{fixed_pct:>+9.2f}%{median_R:>10.2f}{win_rate:>9.1f}%")

fixed_f_pct = mean_R_f * RISK_FRAC * 100
print(f"{'Fixed 1:2, filtered':<28}{n:>6}{mean_R_f:>10.3f}{fixed_f_pct:>+9.2f}%{median_R_f:>10.2f}{win_rate_f:>9.1f}%")
