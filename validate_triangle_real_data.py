"""
validate_triangle_real_data.py
--------------------------------
Validation-only: re-runs the same converging-boundary window scan as
validate_boundaries_real_data.py (same WINDOW_LEN/STEP/MIN_PIVOTS/
TOLERANCE, same placeholder-zero-bar guard via research_filters), then
calls assemble_triangle() on every converging candidate to classify it
(symmetrical/ascending/descending) or reject it (touch count, apex
behind/too-far, non-triangle slope shape). Plots a handful of examples
per classified kind. Does NOT do breakout confirmation.
"""
import os
import sqlite3
from datetime import date
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from triangle import assemble_triangle
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
OUT_DIR = "C:/Users/Lenovo/psx_pipeline/triangle_validation_charts"
os.makedirs(OUT_DIR, exist_ok=True)

TICKERS = ["OGDC", "LUCK", "KEL", "ISIL", "TOWL"]

WINDOW_LEN = 80
STEP = 40
MIN_PIVOTS_PER_SIDE = 3
TOLERANCE_PCT = 0.015

conn = sqlite3.connect(DB_PATH)

converging_candidates = []  # (symbol, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary)

for sym in TICKERS:
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

    n = len(df)
    for start in range(0, n - WINDOW_LEN, STEP):
        end = start + WINDOW_LEN
        hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
        lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
        if len(hi_pivots) < MIN_PIVOTS_PER_SIDE or len(lo_pivots) < MIN_PIVOTS_PER_SIDE:
            continue
        hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
        lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)
        if hi_boundary is None or lo_boundary is None:
            continue
        if hi_boundary.slope <= lo_boundary.slope + 1e-9:
            converging_candidates.append((sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary))

conn.close()
print(f"{len(converging_candidates)} converging candidate windows to run through assemble_triangle()")

# ---- run assemble_triangle on every converging candidate, track outcomes ----
rejection_reasons = {"touch_count": 0, "forced_line": 0, "not_triangle_shape": 0, "apex_behind_or_none": 0,
                      "apex_too_far": 0, "duration_invalid": 0, "unclassified_other": 0}
kind_counts = {"symmetrical": 0, "ascending": 0, "descending": 0}
triangles = []  # (symbol, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary, tri)

for sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary in converging_candidates:
    start_date = df["date"].iloc[start].date()
    end_date = df["date"].iloc[end].date()

    tri = assemble_triangle(
        hi_boundary, lo_boundary,
        window_start_index=start, window_end_index=end,
        start_date=start_date, end_date=end_date,
    )

    if tri is not None:
        kind_counts[tri.kind] += 1
        triangles.append((sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary, tri))
        continue

    # classify why it was rejected, for reporting (best-effort, mirrors
    # assemble_triangle's own check order)
    if len(hi_boundary.touch_indices) < 2 or len(lo_boundary.touch_indices) < 2:
        rejection_reasons["touch_count"] += 1
        continue
    from triangle import classify_triangle, compute_apex, is_forced_line
    if is_forced_line(hi_boundary, start, end) or is_forced_line(lo_boundary, start, end):
        rejection_reasons["forced_line"] += 1
        continue
    kind = classify_triangle(hi_boundary, lo_boundary, window_start_index=start, window_end_index=end)
    if kind is None:
        rejection_reasons["not_triangle_shape"] += 1
        continue
    apex = compute_apex(hi_boundary, lo_boundary)
    if apex is None or apex[0] < end:
        rejection_reasons["apex_behind_or_none"] += 1
        continue
    width = end - start
    if apex[0] > end + 3.0 * width:
        rejection_reasons["apex_too_far"] += 1
        continue
    if (end_date - start_date).days <= 0:
        rejection_reasons["duration_invalid"] += 1
        continue
    rejection_reasons["unclassified_other"] += 1

print("\n=== Classification breakdown (of", len(converging_candidates), "converging candidates) ===")
for k, v in kind_counts.items():
    print(f"  {k}: {v}")
print(f"  TOTAL classified as a triangle: {sum(kind_counts.values())}")
print("\n=== Rejection reasons ===")
for k, v in rejection_reasons.items():
    print(f"  {k}: {v}")
print(f"  TOTAL rejected: {sum(rejection_reasons.values())}")

# ---- plot up to 4 examples per kind ----
def plot_triangle(sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary, tri, out_path):
    fig, ax = plt.subplots(figsize=(14, 7))
    pad = 10
    plot_start = max(0, start - pad)
    # extend line drawing toward the apex, but cap for chart readability
    width = end - start
    line_end = min(len(df) - 1, int(min(tri.apex_index, end + width)))
    plot_end = min(len(df) - 1, line_end + pad)
    sub = df.iloc[plot_start:plot_end + 1]

    ax.plot(sub["date"], sub["close"], linewidth=1, color="#333333", label="close", zorder=1)

    xs_line = list(range(start, line_end + 1))
    ax.plot([df["date"].iloc[x] for x in xs_line], [hi_boundary.price_at(x) for x in xs_line],
             color="#d62728", linewidth=1.5, linestyle="--", label="upper boundary")
    ax.plot([df["date"].iloc[x] for x in xs_line], [lo_boundary.price_at(x) for x in xs_line],
             color="#2ca02c", linewidth=1.5, linestyle="--", label="lower boundary")

    for p in hi_pivots:
        is_touch = p.index in hi_boundary.touch_indices
        ax.scatter([df["date"].iloc[p.index]], [p.price], marker="^",
                    s=90 if is_touch else 40, color="#d62728" if is_touch else "none",
                    edgecolors="#d62728", linewidths=1.5, zorder=5)
    for p in lo_pivots:
        is_touch = p.index in lo_boundary.touch_indices
        ax.scatter([df["date"].iloc[p.index]], [p.price], marker="v",
                    s=90 if is_touch else 40, color="#2ca08d" if is_touch else "none",
                    edgecolors="#2ca02c", linewidths=1.5, zorder=5)

    if tri.apex_index <= line_end:
        apex_x = df["date"].iloc[int(round(tri.apex_index))] if int(round(tri.apex_index)) < len(df) else sub["date"].iloc[-1]
        ax.scatter([apex_x], [tri.apex_price], marker="*", s=250, color="#9467bd",
                    edgecolors="black", linewidths=0.5, zorder=6, label="apex")

    ax.scatter([], [], marker="^", color="#d62728", label="pivot high (touch)")
    ax.scatter([], [], marker="^", facecolors="none", edgecolors="#d62728", label="pivot high (interior)")
    ax.scatter([], [], marker="v", color="#2ca02c", label="pivot low (touch)")
    ax.scatter([], [], marker="v", facecolors="none", edgecolors="#2ca02c", label="pivot low (interior)")

    ax.set_title(f"{sym} bars {start}-{end} | {tri.kind.upper()} | duration={tri.duration_days}d "
                 f"| hi_slope={hi_boundary.slope:.4f} lo_slope={lo_boundary.slope:.4f} "
                 f"| touches hi={len(hi_boundary.touch_indices)}/{len(hi_pivots)} lo={len(lo_boundary.touch_indices)}/{len(lo_pivots)}")
    ax.legend(loc="best", fontsize=7)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


LIQUID_TICKERS = {"OGDC", "LUCK"}
THIN_TICKERS = {"KEL", "ISIL", "TOWL"}

for kind in ["symmetrical", "ascending", "descending"]:
    examples = [t for t in triangles if t[8].kind == kind]
    # prefer more total touches, then spread across symbols
    examples.sort(key=lambda t: len(t[6].touch_indices) + len(t[7].touch_indices), reverse=True)

    # Liquid names (OGDC/LUCK) are the fairer visual test of whether the
    # classification looks like a real triangle by eye -- prioritize them.
    # Thin names (KEL/ISIL/TOWL) were the right stress test for robustness
    # earlier, but are a worse test here, so include exactly one as a
    # sanity check rather than as the primary basis for judgment.
    picked = []
    seen = {}
    for ex in examples:
        sym = ex[0]
        if sym not in LIQUID_TICKERS:
            continue
        if seen.get(sym, 0) >= 2:
            continue
        picked.append(ex)
        seen[sym] = seen.get(sym, 0) + 1
        if len(picked) >= 3:
            break

    for ex in examples:
        sym = ex[0]
        if sym not in THIN_TICKERS:
            continue
        picked.append(ex)
        break

    print(f"\nPlotting {len(picked)} {kind} examples "
          f"({sum(1 for p in picked if p[0] in LIQUID_TICKERS)} liquid, "
          f"{sum(1 for p in picked if p[0] in THIN_TICKERS)} thin)")
    for i, (sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary, tri) in enumerate(picked):
        out_path = os.path.join(OUT_DIR, f"{kind}_{i+1:02d}_{sym}_{start}_{end}.png")
        plot_triangle(sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary, tri, out_path)
        print(f"  saved {out_path}")
