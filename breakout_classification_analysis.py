"""
breakout_classification_analysis.py
--------------------------------------
Type 1-4 classification (breakout_classification.py) re-run on the
canonical 302-symbol, 544-candidate classified-triangle set
(triangle_full_universe_results.csv). No pipeline changes to
pivots.py/boundaries.py/triangle.py -- reconstructs each candidate's
Boundary objects and apex (for the horizon) deterministically from the
recorded (symbol, start, end) window, exactly as the measured-move
analysis already does.

The 2 "none"-outcome candidates never had a boundary violation at all --
there is no breakout to classify a RETEST/FAILURE pattern for, so they
are reported explicitly as "N/A (no breakout)" in every table rather
than silently dropped.

Breakout point/direction = the FIRST boundary violation chronologically
(same convention as the measured-move analysis): up_idx/down_idx for
single-direction outcomes, min(up_idx, down_idx) for whipsaw/sequential.

Horizon = min(window_end+40, apex_index+5), capped at data length -- the
same horizon already used for breakout-occurrence counting.

Descriptive only -- no stop-loss/R-multiple logic yet.

SUPERSEDED AS "THE" CANONICAL TYPE 1-4 RESULT (2026-07-15): this script
reports the ORIGINAL full-horizon LFD definition (lfd_variant="full",
pinned explicitly below), which is the too-broad baseline documented in
Triangle_Pattern_Specification_v1.md (69% Type 4 overall) -- kept
runnable for that historical/comparison reference, but "trigger" is now
DEFAULT_LFD_VARIANT (locked) and breakout_classification_variant_results.csv
(filtered to variant=="trigger") is the current canonical Type 1-4 result.
See breakout_classification_variant_comparison.py.
"""
import sqlite3
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from triangle import assemble_triangle
from breakout_classification import classify_breakout
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
RESULTS_CSV = "C:/Users/Lenovo/psx_pipeline/triangle_full_universe_results.csv"
TOLERANCE_PCT = 0.015
HORIZON_BARS = 40
APEX_BUFFER_BARS = 5

candidates = pd.read_csv(RESULTS_CSV)
print(f"{len(candidates)} classified candidates loaded")

conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []

for _, cand in candidates.iterrows():
    sym = cand["symbol"]
    start, end = int(cand["start"]), int(cand["end"])
    outcome = cand["outcome"]
    up_idx = cand["up_idx"]
    down_idx = cand["down_idx"]

    if sym not in symbol_cache:
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
        symbol_cache[sym] = (df, highs, lows, closes, all_pivots)

    df, highs, lows, closes, all_pivots = symbol_cache[sym]

    if outcome == "none":
        rows.append({
            "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
            "kind": cand["kind"], "outcome": outcome, "type": "N/A",
            "boundary_touched": None, "boundary_breached": None, "lfd_touched": None,
        })
        continue

    hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
    lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
    hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
    lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)

    start_date = df["date"].iloc[start].date()
    end_date = df["date"].iloc[end].date()
    tri = assemble_triangle(hi_boundary, lo_boundary, window_start_index=start, window_end_index=end,
                             start_date=start_date, end_date=end_date)

    if outcome == "up":
        breakout_idx, direction = int(up_idx), "up"
    elif outcome == "down":
        breakout_idx, direction = int(down_idx), "down"
    else:  # whipsaw or sequential
        if up_idx <= down_idx:
            breakout_idx, direction = int(up_idx), "up"
        else:
            breakout_idx, direction = int(down_idx), "down"

    n = len(df)
    horizon_end = min(n - 1, end + HORIZON_BARS, int(tri.apex_index) + APEX_BUFFER_BARS)
    horizon_end = max(horizon_end, end)

    boundary = hi_boundary if direction == "up" else lo_boundary
    result = classify_breakout(boundary, highs, lows, breakout_idx, direction, horizon_end,
                                tolerance_pct=TOLERANCE_PCT, lfd_variant="full")

    rows.append({
        "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
        "kind": cand["kind"], "outcome": outcome, "type": result.type,
        "boundary_touched": result.boundary_touched,
        "boundary_breached": result.boundary_breached,
        "lfd_touched": result.lfd_touched,
    })

conn.close()

res = pd.DataFrame(rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/breakout_classification_results.csv", index=False)

print("\n=== Full Type 1-4 distribution (overall) ===")
print(res["type"].value_counts().reindex([1, 2, 3, 4, "N/A"], fill_value=0).to_string())

print("\n=== By triangle kind ===")
print(res.groupby(["kind", "type"]).size().unstack(fill_value=0)
      .reindex(columns=[1, 2, 3, 4, "N/A"], fill_value=0).to_string())

print("\n=== Cross-tab: Type (1-4/N/A) x existing 5-category outcome ===")
crosstab = pd.crosstab(res["type"], res["outcome"])
crosstab = crosstab.reindex(index=[1, 2, 3, 4, "N/A"], columns=["up", "down", "whipsaw", "sequential", "none"], fill_value=0)
print(crosstab.to_string())

print("\n=== Type 4 <-> sequential mapping check (empirical, not assumed) ===")
sequential_candidates = res[res["outcome"] == "sequential"]
type4_candidates = res[res["type"] == 4]

sequential_and_type4 = res[(res["outcome"] == "sequential") & (res["type"] == 4)]
sequential_not_type4 = res[(res["outcome"] == "sequential") & (res["type"] != 4)]
type4_not_sequential = res[(res["type"] == 4) & (res["outcome"] != "sequential")]

print(f"  'sequential' candidates: {len(sequential_candidates)}")
print(f"  Type 4 candidates: {len(type4_candidates)}")
print(f"  sequential AND Type 4 (mapping holds): {len(sequential_and_type4)}")
print(f"  sequential but NOT Type 4 (mismatch): {len(sequential_not_type4)}")
if len(sequential_not_type4):
    print(sequential_not_type4[["symbol", "start", "end", "kind", "type"]].to_string(index=False))
print(f"  Type 4 but NOT sequential (mismatch): {len(type4_not_sequential)}")
if len(type4_not_sequential):
    print(type4_not_sequential[["symbol", "start", "end", "kind", "outcome"]].to_string(index=False))

print(f"\nSaved {len(res)} rows to breakout_classification_results.csv")
