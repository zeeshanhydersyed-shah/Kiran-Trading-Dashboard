"""
triangle_trend_alignment.py
-------------------------------
Follow-up check (not a reopening of the closed EV finding): does 200-day
EMA trend alignment at breakout explain any of the variance in 60-day
raw_pct_move for the clean up/down-outcome candidates?

EMA CONVENTION (stated explicitly, per instruction):
  SMA-seeded EMA-200, standard/textbook method:
    ema[199] = mean(close[0:200])   (first 200 closes, SMA seed)
    ema[i]   = close[i] * k + ema[i-1] * (1-k), k = 2/(200+1), for i > 199
    ema[i] undefined (NaN) for i < 199 -- fewer than 200 bars of history.
  Computed on the SAME post-drop_placeholder_zero_bars price series used
  throughout this study (bar indices already reflect that convention, so
  breakout_idx values join directly without re-indexing).

Candidates with breakout_idx < 199 (fewer than 200 bars of prior history)
have no valid 200EMA at all -- EXCLUDED from price-vs-EMA and slope
analysis both, not approximated with a shorter window.

EMA SLOPE: ema[breakout_idx] vs ema[breakout_idx - 20] (20 bars back,
proposed as a reasonable slope-measurement window -- not validated
against alternatives). Candidates with breakout_idx - 20 < 199 have a
valid price-vs-EMA classification but no valid slope classification --
excluded from slope-dependent splits only, counted and reported
separately from the full EMA exclusion.
"""

import sqlite3
import pandas as pd
import numpy as np

from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
EMA_WINDOW = 200
SLOPE_LOOKBACK = 20

candidates = pd.read_csv("triangle_full_universe_results.csv")
mm60 = pd.read_csv("triangle_measured_move_results.csv")
mm60 = mm60[(mm60["horizon"] == 60) & (mm60["outcome"].isin(["up", "down"])) & (~mm60["excluded_insufficient_data"])]

merged = mm60.merge(
    candidates[["symbol", "start", "end", "up_idx", "down_idx"]],
    on=["symbol", "start", "end"], how="left"
)
merged["breakout_idx"] = merged.apply(
    lambda r: r["up_idx"] if r["outcome"] == "up" else r["down_idx"], axis=1
).astype(int)

print(f"Candidates to process (horizon=60, up/down, not excluded_insufficient_data): {len(merged)}")
print(merged["outcome"].value_counts().to_string())

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

no_ema = []
no_slope = []
rows = []

for _, cand in merged.iterrows():
    sym = cand["symbol"]
    breakout_idx = cand["breakout_idx"]

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df = drop_placeholder_zero_bars(df)
        closes = df["close"].tolist()

        ema = [np.nan] * len(closes)
        if len(closes) >= EMA_WINDOW:
            ema[EMA_WINDOW - 1] = sum(closes[:EMA_WINDOW]) / EMA_WINDOW
            k = 2 / (EMA_WINDOW + 1)
            for i in range(EMA_WINDOW, len(closes)):
                ema[i] = closes[i] * k + ema[i - 1] * (1 - k)
        symbol_cache[sym] = (closes, ema)

    closes, ema = symbol_cache[sym]

    if breakout_idx >= len(ema) or pd.isna(ema[breakout_idx]):
        no_ema.append((sym, cand["start"], cand["end"], "breakout_idx", breakout_idx))
        continue

    close_at_breakout = closes[breakout_idx]
    ema_at_breakout = ema[breakout_idx]
    price_above_ema = close_at_breakout > ema_at_breakout

    slope_idx = breakout_idx - SLOPE_LOOKBACK
    has_slope = slope_idx >= 0 and not pd.isna(ema[slope_idx])
    ema_rising = None
    ema_slope_pct = None
    if has_slope:
        ema_slope_pct = (ema_at_breakout - ema[slope_idx]) / ema[slope_idx] * 100
        ema_rising = ema_at_breakout > ema[slope_idx]
    else:
        no_slope.append((sym, cand["start"], cand["end"], "slope_idx", slope_idx))

    rows.append({
        "symbol": sym, "start": cand["start"], "end": cand["end"], "outcome": cand["outcome"],
        "breakout_idx": breakout_idx, "close_at_breakout": close_at_breakout,
        "ema_at_breakout": ema_at_breakout, "price_above_ema": price_above_ema,
        "ema_rising": ema_rising, "ema_slope_pct": ema_slope_pct,
        "raw_pct_move": cand["raw_pct_move"],
    })

conn.close()

res = pd.DataFrame(rows)
print(f"\nExcluded, insufficient history for ANY 200EMA (breakout_idx < {EMA_WINDOW} bars): {len(no_ema)}")
print(f"Candidates with a valid 200EMA (price-vs-EMA classifiable): {len(res)}")
print(f"Of those, missing a valid EMA-slope (breakout_idx - {SLOPE_LOOKBACK} still < {EMA_WINDOW} bars): "
      f"{res['ema_rising'].isna().sum()}")
print(f"Candidates with BOTH a valid price-vs-EMA AND slope classification: {res['ema_rising'].notna().sum()}")

res.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_trend_alignment_stage1.csv", index=False)

if no_ema:
    print(f"\nExcluded-for-no-EMA candidates (sample, up to 10):")
    for row in no_ema[:10]:
        print(f"  {row}")

# ═══════════════════════════════════════════════════════════════════════
# Splits
# ═══════════════════════════════════════════════════════════════════════

def describe(series, label):
    s = series.dropna()
    n = len(s)
    flag = "  [n<15, TOO SMALL TO CONCLUDE]" if n < 15 else ""
    if n == 0:
        print(f"    {label}: n=0{flag}")
        return
    print(f"    {label}: n={n}  mean={s.mean():+.2f}%  median={s.median():+.2f}%{flag}")

for outc in ["up", "down"]:
    sub = res[res["outcome"] == outc]
    print(f"\n{'='*70}\nOUTCOME = {outc.upper()} (n={len(sub)} with valid EMA)\n{'='*70}")

    print("\n--- (a) price above vs below 200EMA at breakout ---")
    describe(sub[sub["price_above_ema"] == True]["raw_pct_move"], "above EMA")
    describe(sub[sub["price_above_ema"] == False]["raw_pct_move"], "below EMA")

    slope_sub = sub[sub["ema_rising"].notna()]
    print(f"\n--- (b) 200EMA rising vs falling at breakout (n={len(slope_sub)} with valid slope) ---")
    describe(slope_sub[slope_sub["ema_rising"] == True]["raw_pct_move"], "EMA rising")
    describe(slope_sub[slope_sub["ema_rising"] == False]["raw_pct_move"], "EMA falling")

    print(f"\n--- (c) combination (n={len(slope_sub)} with both valid) ---")
    for above in [True, False]:
        for rising in [True, False]:
            cell = slope_sub[(slope_sub["price_above_ema"] == above) & (slope_sub["ema_rising"] == rising)]
            label = f"{'above' if above else 'below'} EMA + {'rising' if rising else 'falling'} EMA"
            describe(cell["raw_pct_move"], label)
