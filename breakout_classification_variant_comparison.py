"""
breakout_classification_variant_comparison.py
-------------------------------------------------
Three-way comparison of LFD window-length variants on the canonical
544-candidate classified-triangle set, per explicit instruction:
"current" (full horizon, unchanged/original), "fixed" (5 and 10 bars),
and "trigger" (measured-move close threshold). No decision baked in --
descriptive comparison only, reported side by side.

Reconstructs each candidate's Boundary objects and apex deterministically
from the recorded (symbol, start, end) window, same as prior analyses.
measured_move_height is recomputed directly (same formula as
triangle_measured_move_analysis.py: |hi_boundary.price_at(breakout_idx) -
lo_boundary.price_at(breakout_idx)|) rather than joined from an external
CSV, to keep this self-contained and reproducible.
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

VARIANTS = [
    ("current", dict(lfd_variant="full")),
    ("fixed_5", dict(lfd_variant="fixed", lfd_fixed_bars=5)),
    ("fixed_10", dict(lfd_variant="fixed", lfd_fixed_bars=10)),
    ("trigger", dict(lfd_variant="trigger")),  # closes/measured_move_height filled in per-candidate below
]

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
        for variant_name, _ in VARIANTS:
            rows.append({
                "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
                "kind": cand["kind"], "outcome": outcome, "variant": variant_name, "type": "N/A",
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

    measured_move_height = abs(hi_boundary.price_at(breakout_idx) - lo_boundary.price_at(breakout_idx))

    for variant_name, kwargs in VARIANTS:
        call_kwargs = dict(kwargs)
        if call_kwargs.get("lfd_variant") == "trigger":
            call_kwargs["closes"] = closes
            call_kwargs["measured_move_height"] = measured_move_height

        result = classify_breakout(boundary, highs, lows, breakout_idx, direction, horizon_end,
                                    tolerance_pct=TOLERANCE_PCT, **call_kwargs)
        rows.append({
            "sector": cand["sector"], "symbol": sym, "start": start, "end": end,
            "kind": cand["kind"], "outcome": outcome, "variant": variant_name, "type": result.type,
        })

conn.close()

res = pd.DataFrame(rows)
res.to_csv("C:/Users/Lenovo/psx_pipeline/breakout_classification_variant_results.csv", index=False)

for variant_name, _ in VARIANTS:
    sub = res[res["variant"] == variant_name]
    print(f"\n{'='*70}\nVARIANT: {variant_name}\n{'='*70}")

    print("\n--- Type 1-4 distribution (overall) ---")
    print(sub["type"].value_counts().reindex([1, 2, 3, 4, "N/A"], fill_value=0).to_string())

    print("\n--- By triangle kind ---")
    print(sub.groupby(["kind", "type"]).size().unstack(fill_value=0)
          .reindex(columns=[1, 2, 3, 4, "N/A"], fill_value=0).to_string())

    print("\n--- Cross-tab: Type x outcome ---")
    crosstab = pd.crosstab(sub["type"], sub["outcome"])
    crosstab = crosstab.reindex(index=[1, 2, 3, 4, "N/A"], columns=["up", "down", "whipsaw", "sequential", "none"], fill_value=0)
    print(crosstab.to_string())

    up_sub = sub[sub["outcome"] == "up"]
    down_sub = sub[sub["outcome"] == "down"]
    up_type4_pct = (up_sub["type"] == 4).sum() / len(up_sub) * 100 if len(up_sub) else float("nan")
    down_type4_pct = (down_sub["type"] == 4).sum() / len(down_sub) * 100 if len(down_sub) else float("nan")
    print(f"\n--- 'up' candidates classified Type 4: {(up_sub['type']==4).sum()}/{len(up_sub)} ({up_type4_pct:.1f}%) ---")
    print(f"--- 'down' candidates classified Type 4: {(down_sub['type']==4).sum()}/{len(down_sub)} ({down_type4_pct:.1f}%) ---")

    seq_sub = sub[sub["outcome"] == "sequential"]
    seq_type4_pct = (seq_sub["type"] == 4).sum() / len(seq_sub) * 100 if len(seq_sub) else float("nan")
    print(f"--- 'sequential' candidates classified Type 4 (mapping preserved): {(seq_sub['type']==4).sum()}/{len(seq_sub)} ({seq_type4_pct:.1f}%) ---")

print(f"\nSaved {len(res)} rows to breakout_classification_variant_results.csv")
