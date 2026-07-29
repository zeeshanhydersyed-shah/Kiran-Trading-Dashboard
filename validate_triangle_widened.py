"""
validate_triangle_widened.py
-------------------------------
Widens the triangle-classification study from 5 tickers to 18, spanning
the same 5 sectors the original 5 tickers already belonged to (identified
via stock_metadata.sector), 3-4 per sector across liquidity tiers
(large/liquid, mid, thin), keeping all 5 original tickers in the set.

Pipeline is UNCHANGED from the validated 5-ticker version:
  1. find_pivots_collapsed() -- frozen-close collapsing
  2. drop_placeholder_zero_bars() -- placeholder-zero guard
  3. fit_boundary() -- 80-bar windows, 50% overlap, tolerance_pct=0.015
  4. assemble_triangle() -- includes the is_forced_line() spacing gate
  5. 5-category breakout-occurrence count (same horizon rule, same
     5-bar whipsaw threshold)

No Type 1-4 classification, no stop-loss logic. Counting only.
"""
import sqlite3
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary, check_violation
from triangle import assemble_triangle, classify_triangle, compute_apex, is_forced_line
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"

TICKERS = [
    # sector, symbol, tier
    ("OIL & GAS EXPLORATION COMPANIES", "OGDC", "large (existing)"),
    ("OIL & GAS EXPLORATION COMPANIES", "PPL", "large"),
    ("OIL & GAS EXPLORATION COMPANIES", "POL", "mid"),

    ("CEMENT", "LUCK", "large (existing)"),
    ("CEMENT", "DGKC", "mid"),
    ("CEMENT", "KOHC", "mid-thin"),
    ("CEMENT", "DNCC", "thin"),

    ("POWER GENERATION & DISTRIBUTION", "HUBC", "large"),
    ("POWER GENERATION & DISTRIBUTION", "KEL", "mid (existing)"),
    ("POWER GENERATION & DISTRIBUTION", "KAPCO", "mid"),
    ("POWER GENERATION & DISTRIBUTION", "EPQL", "thin"),

    ("FOOD & PERSONAL CARE PRODUCTS", "UPFL", "large"),
    ("FOOD & PERSONAL CARE PRODUCTS", "NATF", "mid"),
    ("FOOD & PERSONAL CARE PRODUCTS", "ISIL", "thin (existing)"),

    ("TEXTILE COMPOSITE", "NML", "large"),
    ("TEXTILE COMPOSITE", "KTML", "mid"),
    ("TEXTILE COMPOSITE", "SAPT", "mid-thin"),
    ("TEXTILE COMPOSITE", "TOWL", "thin (existing)"),
]

WINDOW_LEN = 80
STEP = 40
MIN_PIVOTS_PER_SIDE = 3
TOLERANCE_PCT = 0.015
HORIZON_BARS = 40
APEX_BUFFER_BARS = 5
WHIPSAW_GAP_THRESHOLD = 5

conn = sqlite3.connect(DB_PATH)

print("=== Ticker list ===")
for sec, sym, tier in TICKERS:
    print(f"  {sym:6s} | {tier:18s} | {sec}")
print(f"\n{len(TICKERS)} tickers total\n")

stats = {
    "windows_examined": 0,
    "skipped_too_few_pivots": 0,
    "boundary_fit_none": 0,  # fit_boundary() itself returned None (Section 3.2 fix) -- excluded before converging_candidates, same as the original 5-ticker pipeline
    "converging_candidates": 0,
    "touch_count": 0,
    "forced_line": 0,
    "not_triangle_shape": 0,
    "apex_behind_or_none": 0,
    "apex_too_far": 0,
    "duration_invalid": 0,
    "classified_triangle": 0,
}

per_symbol_data_notes = []
triangles = []  # (sector, tier, symbol, df, start, end, hi_boundary, lo_boundary, tri)

for sec, sym, tier in TICKERS:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
        conn, params=(sym,)
    )
    df["date"] = pd.to_datetime(df["date"])
    n_before = len(df)
    df = drop_placeholder_zero_bars(df)
    n_dropped = n_before - len(df)

    per_symbol_data_notes.append((sym, tier, n_before, n_dropped,
                                   df["date"].min().date() if len(df) else None,
                                   df["date"].max().date() if len(df) else None))

    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    all_pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)

    n = len(df)
    for start in range(0, n - WINDOW_LEN, STEP):
        end = start + WINDOW_LEN
        stats["windows_examined"] += 1
        hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
        lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
        if len(hi_pivots) < MIN_PIVOTS_PER_SIDE or len(lo_pivots) < MIN_PIVOTS_PER_SIDE:
            stats["skipped_too_few_pivots"] += 1
            continue
        hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
        lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)
        if hi_boundary is None or lo_boundary is None:
            stats["boundary_fit_none"] += 1
            continue
        if hi_boundary.slope > lo_boundary.slope + 1e-9:
            continue  # not converging, not a candidate at all (matches original funnel def)
        stats["converging_candidates"] += 1

        start_date = df["date"].iloc[start].date()
        end_date = df["date"].iloc[end].date()
        tri = assemble_triangle(
            hi_boundary, lo_boundary,
            window_start_index=start, window_end_index=end,
            start_date=start_date, end_date=end_date,
        )
        if tri is not None:
            stats["classified_triangle"] += 1
            triangles.append((sec, tier, sym, df, start, end, hi_boundary, lo_boundary, tri))
            continue

        # rejection-reason attribution, mirrors assemble_triangle's own order
        if len(hi_boundary.touch_indices) < 2 or len(lo_boundary.touch_indices) < 2:
            stats["touch_count"] += 1
            continue
        if is_forced_line(hi_boundary, start, end) or is_forced_line(lo_boundary, start, end):
            stats["forced_line"] += 1
            continue
        kind = classify_triangle(hi_boundary, lo_boundary, window_start_index=start, window_end_index=end)
        if kind is None:
            stats["not_triangle_shape"] += 1
            continue
        apex = compute_apex(hi_boundary, lo_boundary)
        if apex is None or apex[0] < end:
            stats["apex_behind_or_none"] += 1
            continue
        width = end - start
        if apex[0] > end + 3.0 * width:
            stats["apex_too_far"] += 1
            continue
        stats["duration_invalid"] += 1

conn.close()

print("=== Data availability / placeholder-zero notes per symbol ===")
for sym, tier, n_before, n_dropped, dmin, dmax in per_symbol_data_notes:
    flag = f"  <-- {n_dropped} placeholder-zero bars dropped" if n_dropped else ""
    print(f"  {sym:6s} ({tier:18s}) n={n_before:5d}  {dmin} -> {dmax}{flag}")

print("\n=== Funnel ===")
print(f"  windows_examined:        {stats['windows_examined']}")
print(f"  skipped_too_few_pivots:  {stats['skipped_too_few_pivots']}")
print(f"  converging_candidates:   {stats['converging_candidates']}")
print(f"  classified_triangle:     {stats['classified_triangle']}")

print(f"  boundary_fit_none (excluded before converging_candidates): {stats['boundary_fit_none']}")

print("\n=== Rejection breakdown (of converging_candidates) ===")
rej_total = 0
for k in ["touch_count", "forced_line", "not_triangle_shape", "apex_behind_or_none", "apex_too_far", "duration_invalid"]:
    print(f"  {k}: {stats[k]}")
    rej_total += stats[k]
print(f"  TOTAL rejected: {rej_total}  (+ classified {stats['classified_triangle']} = {rej_total + stats['classified_triangle']}, should equal converging_candidates {stats['converging_candidates']})")

print(f"\n=== Classification breakdown ({stats['classified_triangle']} classified triangles) ===")
kind_counts = {}
for sec, tier, sym, df, start, end, hi_b, lo_b, tri in triangles:
    kind_counts[tri.kind] = kind_counts.get(tri.kind, 0) + 1
for k, v in kind_counts.items():
    print(f"  {k}: {v}")

# ---- breakout occurrence, 5-category, same rule as before ----
print("\n=== Breakout occurrence (5-category) ===")
results = []
for sec, tier, sym, df, start, end, hi_boundary, lo_boundary, tri in triangles:
    n = len(df)
    horizon_end = min(n - 1, end + HORIZON_BARS, int(tri.apex_index) + APEX_BUFFER_BARS)
    horizon_end = max(horizon_end, end)
    closes = df["close"].tolist()

    up_v = check_violation(hi_boundary, closes, start_index=end + 1, end_index=horizon_end,
                            direction="upper", tolerance_pct=TOLERANCE_PCT)
    down_v = check_violation(lo_boundary, closes, start_index=end + 1, end_index=horizon_end,
                              direction="lower", tolerance_pct=TOLERANCE_PCT)
    up_idx = up_v[0] if up_v else None
    down_idx = down_v[0] if down_v else None
    gap = abs(up_idx - down_idx) if (up_idx is not None and down_idx is not None) else None

    up_hit = up_idx is not None
    down_hit = down_idx is not None
    if not up_hit and not down_hit:
        outcome = "none"
    elif up_hit and not down_hit:
        outcome = "up"
    elif down_hit and not up_hit:
        outcome = "down"
    elif gap <= WHIPSAW_GAP_THRESHOLD:
        outcome = "whipsaw"
    else:
        outcome = "sequential"

    results.append((sec, tier, sym, start, end, tri.kind, outcome, up_idx, down_idx, gap))

res_df = pd.DataFrame(results, columns=["sector", "tier", "symbol", "start", "end", "kind",
                                         "outcome", "up_idx", "down_idx", "gap"])

OUTCOME_CATEGORIES = ["up", "down", "whipsaw", "sequential", "none"]
print(res_df["outcome"].value_counts().reindex(OUTCOME_CATEGORIES, fill_value=0).to_string())

print("\n=== By kind ===")
print(res_df.groupby(["kind", "outcome"]).size().unstack(fill_value=0)
      .reindex(columns=OUTCOME_CATEGORIES, fill_value=0).to_string())

print("\n=== Full detail ===")
print(res_df.to_string(index=False))

res_df.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_widened_results.csv", index=False)
print("\nSaved full result table to triangle_widened_results.csv")
