"""
render_triangle_candlestick.py
--------------------------------
Re-renders specific already-validated triangle windows as real candlestick
charts (mplfinance) instead of a close-price line, with the same fitted
upper/lower boundary lines, touch/interior pivot markers, and apex overlaid.
Purpose: let a human confirm by eye whether the boundary lines are actually
tracking the wick highs/lows they were built from, which a line chart
(showing only close) can't reveal.

Validation-only, no triangle-assembly or breakout-confirmation logic
touched -- this only changes how an already-classified window is drawn.
"""
import os
import sqlite3
import pandas as pd
import numpy as np
import mplfinance as mpf

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from triangle import assemble_triangle
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
OUT_DIR = "C:/Users/Lenovo/psx_pipeline/triangle_validation_charts"
os.makedirs(OUT_DIR, exist_ok=True)

TOLERANCE_PCT = 0.015

# Windows surviving the touch-spacing (is_forced_line) gate added after the
# previous candlestick render -- none of the 3 originally-rendered windows
# (OGDC 4000-4080, OGDC 2240-2320, LUCK 320-400) survive under this gate,
# so these are the current OGDC/LUCK examples from the re-run classification.
TARGETS = [
    ("OGDC", 520, 600, "ascending_01_OGDC_520_600_candles"),
    ("LUCK", 2040, 2120, "descending_01_LUCK_2040_2120_candles"),
    ("OGDC", 2400, 2480, "descending_02_OGDC_2400_2480_candles"),
]

conn = sqlite3.connect(DB_PATH)

for sym, start, end, out_name in TARGETS:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
        conn, params=(sym,)
    )
    df["date"] = pd.to_datetime(df["date"])
    df = drop_placeholder_zero_bars(df)

    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    all_pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)

    hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
    lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
    hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
    lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)

    tri = assemble_triangle(
        hi_boundary, lo_boundary,
        window_start_index=start, window_end_index=end,
        start_date=df["date"].iloc[start].date(), end_date=df["date"].iloc[end].date(),
    )
    if tri is None:
        print(f"SKIP {sym} {start}-{end}: no longer classifies as a triangle under current logic")
        continue

    pad = 10
    width = end - start
    line_end = min(len(df) - 1, int(min(tri.apex_index, end + width)))
    plot_start = max(0, start - pad)
    plot_end = min(len(df) - 1, line_end + pad)

    sub = df.iloc[plot_start:plot_end + 1].copy()
    n_missing_open = sub["open"].isna().sum()
    if n_missing_open:
        # Known, already-documented data gap (pre-2020 open coverage,
        # see project CLAUDE.md) -- not new. Fallback to close for the
        # candle body on those rows only, for rendering purposes.
        print(f"  note: {sym} {start}-{end} has {n_missing_open} bar(s) with missing open "
              f"(known pre-2020 coverage gap) -- using close as fallback for the candle body")
        sub["open"] = sub["open"].fillna(sub["close"])
    sub = sub.set_index("date")
    sub.index.name = "Date"
    sub = sub.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})

    # boundary lines, aligned to sub's index, NaN outside [start, line_end]
    upper_line = pd.Series(np.nan, index=sub.index)
    lower_line = pd.Series(np.nan, index=sub.index)
    for x in range(start, line_end + 1):
        d = df["date"].iloc[x]
        if d in upper_line.index:
            upper_line.loc[d] = hi_boundary.price_at(x)
            lower_line.loc[d] = lo_boundary.price_at(x)

    # pivot markers: touch vs interior, high vs low -- 4 separate scatter series
    def marker_series(pivots, boundary, want_touch):
        s = pd.Series(np.nan, index=sub.index)
        for p in pivots:
            d = df["date"].iloc[p.index]
            is_touch = p.index in boundary.touch_indices
            if is_touch == want_touch and d in s.index:
                s.loc[d] = p.price
        return s

    hi_touch = marker_series(hi_pivots, hi_boundary, True)
    hi_interior = marker_series(hi_pivots, hi_boundary, False)
    lo_touch = marker_series(lo_pivots, lo_boundary, True)
    lo_interior = marker_series(lo_pivots, lo_boundary, False)

    apex_series = pd.Series(np.nan, index=sub.index)
    if start <= tri.apex_index <= line_end:
        apex_idx_int = int(round(tri.apex_index))
        if 0 <= apex_idx_int < len(df):
            d = df["date"].iloc[apex_idx_int]
            if d in apex_series.index:
                apex_series.loc[d] = tri.apex_price

    addplots = [
        mpf.make_addplot(upper_line, color="#d62728", width=1.5, linestyle="--"),
        mpf.make_addplot(lower_line, color="#2ca02c", width=1.5, linestyle="--"),
        mpf.make_addplot(hi_touch, type="scatter", marker="^", markersize=90, color="#d62728"),
        mpf.make_addplot(hi_interior, type="scatter", marker="^", markersize=40,
                          color="none", edgecolors="#d62728"),
        mpf.make_addplot(lo_touch, type="scatter", marker="v", markersize=90, color="#2ca02c"),
        mpf.make_addplot(lo_interior, type="scatter", marker="v", markersize=40,
                          color="none", edgecolors="#2ca02c"),
    ]
    if apex_series.notna().any():
        addplots.append(mpf.make_addplot(apex_series, type="scatter", marker="*",
                                          markersize=300, color="#9467bd", edgecolors="black"))

    title = (f"{sym} bars {start}-{end} | {tri.kind.upper()} | duration={tri.duration_days}d "
             f"| hi_slope={hi_boundary.slope:.4f} lo_slope={lo_boundary.slope:.4f} "
             f"| touches hi={len(hi_boundary.touch_indices)}/{len(hi_pivots)} lo={len(lo_boundary.touch_indices)}/{len(lo_pivots)}")

    out_path = os.path.join(OUT_DIR, f"{out_name}.png")
    mpf.plot(
        sub,
        type="candle",
        style="yahoo",
        addplot=addplots,
        title=title,
        ylabel="price",
        figsize=(16, 8),
        datetime_format="%Y-%m",
        xrotation=30,
        savefig=dict(fname=out_path, dpi=130),
    )
    print(f"saved {out_path}")

conn.close()
