"""
validate_boundaries_real_data.py
----------------------------------
Validation-only: scans real PSX pivot data (find_pivots_collapsed, left=3
right=3) for candidate converging-pivot windows, fits boundaries on highs
and lows separately (fit_boundary), and charts price + pivots + fitted
lines with touch/interior markers distinguished. Also tracks how often
fit_boundary() returns None for one or both sides across every window
scanned -- that rate is the tuning signal requested, not just a stat on
the plotted candidates.

Does NOT do triangle assembly (duration/apex/breakout logic). A window is
called "candidate" here purely as a geometric proxy -- upper boundary
slope <= lower boundary slope (converging or parallel) with both fits
non-None -- used only to pick windows worth a human eyeballing, not as a
validated pattern.

Before pivots are computed, each ticker's raw prices_adjusted pull is
passed through research_filters.drop_placeholder_zero_bars() -- see that
module's docstring. This is a research-pipeline-only guard for a known,
separately-tracked production data-quality issue (placeholder O=H=L=0.00
rows on no-trade days); it is NOT a fix applied at the source, and does
not touch stock_signals.py or any production file.
"""
import os
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
OUT_DIR = "C:/Users/Lenovo/psx_pipeline/boundary_validation_charts"
os.makedirs(OUT_DIR, exist_ok=True)

TICKERS = ["OGDC", "LUCK", "KEL", "ISIL", "TOWL"]

WINDOW_LEN = 80     # bars per scan window (~4 months of trading days)
STEP = 40           # 50% overlap between consecutive windows
MIN_PIVOTS_PER_SIDE = 3
TOLERANCE_PCT = 0.015

conn = sqlite3.connect(DB_PATH)

# ---- stats across EVERY window scanned (not just plotted candidates) ----
stats = {
    "windows_examined": 0,
    "skipped_too_few_pivots": 0,
    "high_none": 0,
    "low_none": 0,
    "both_none": 0,
    "both_fit": 0,
    "converging_candidates": 0,
}

candidates = []  # (symbol, df, start_idx, end_idx, hi_pivots, lo_pivots, hi_boundary, lo_boundary)

for sym in TICKERS:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
        conn, params=(sym,)
    )
    df["date"] = pd.to_datetime(df["date"])

    n_before = len(df)
    df = drop_placeholder_zero_bars(df)
    n_dropped = n_before - len(df)
    if n_dropped:
        print(f"{sym}: dropped {n_dropped} placeholder-zero bar(s) before pivot detection")

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

        hi_is_none = hi_boundary is None
        lo_is_none = lo_boundary is None
        if hi_is_none:
            stats["high_none"] += 1
        if lo_is_none:
            stats["low_none"] += 1
        if hi_is_none and lo_is_none:
            stats["both_none"] += 1
        if not hi_is_none and not lo_is_none:
            stats["both_fit"] += 1
            # converging (or parallel) proxy: upper boundary slope <= lower
            # boundary slope, i.e. the gap between them is not widening
            if hi_boundary.slope <= lo_boundary.slope + 1e-9:
                stats["converging_candidates"] += 1
                candidates.append((sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary))

conn.close()

print("=== Scan stats (every window examined) ===")
for k, v in stats.items():
    print(f"  {k}: {v}")
fit_attempted = stats["windows_examined"] - stats["skipped_too_few_pivots"]
if fit_attempted:
    print(f"\n  high_none rate (of windows where a fit was attempted): {stats['high_none']/fit_attempted:.1%}")
    print(f"  low_none rate  (of windows where a fit was attempted): {stats['low_none']/fit_attempted:.1%}")
    print(f"  both_none rate: {stats['both_none']/fit_attempted:.1%}")
    print(f"  both_fit rate:  {stats['both_fit']/fit_attempted:.1%}")
    if stats["both_fit"]:
        print(f"  converging-candidate rate (of both_fit): {stats['converging_candidates']/stats['both_fit']:.1%}")

print(f"\n{len(candidates)} converging candidate windows found across all tickers.")

# ---- pick up to 10 candidates, spread across tickers, prefer more touches ----
def score(c):
    _, _, _, _, _, _, hi_b, lo_b = c
    return len(hi_b.touch_indices) + len(lo_b.touch_indices)

candidates_sorted = sorted(candidates, key=score, reverse=True)

picked = []
seen_per_symbol = {}
for c in candidates_sorted:
    sym = c[0]
    if seen_per_symbol.get(sym, 0) >= 2:  # cap 2 per ticker for diversity
        continue
    picked.append(c)
    seen_per_symbol[sym] = seen_per_symbol.get(sym, 0) + 1
    if len(picked) >= 10:
        break

print(f"Plotting {len(picked)} candidates.")

for i, (sym, df, start, end, hi_pivots, lo_pivots, hi_boundary, lo_boundary) in enumerate(picked):
    fig, ax = plt.subplots(figsize=(14, 7))
    sub = df.iloc[max(0, start - 10):min(len(df), end + 10)]
    ax.plot(sub["date"], sub["close"], linewidth=1, color="#333333", label="close", zorder=1)

    xs_line = list(range(start, end + 1))
    ax.plot([df["date"].iloc[x] for x in xs_line], [hi_boundary.price_at(x) for x in xs_line],
             color="#d62728", linewidth=1.5, linestyle="--", label="upper boundary")
    ax.plot([df["date"].iloc[x] for x in xs_line], [lo_boundary.price_at(x) for x in xs_line],
             color="#2ca02c", linewidth=1.5, linestyle="--", label="lower boundary")

    for p in hi_pivots:
        is_touch = p.index in hi_boundary.touch_indices
        ax.scatter([df["date"].iloc[p.index]], [p.price],
                    marker="^", s=90 if is_touch else 40,
                    color="#d62728" if is_touch else "none",
                    edgecolors="#d62728", linewidths=1.5, zorder=5)
    for p in lo_pivots:
        is_touch = p.index in lo_boundary.touch_indices
        ax.scatter([df["date"].iloc[p.index]], [p.price],
                    marker="v", s=90 if is_touch else 40,
                    color="#2ca02c" if is_touch else "none",
                    edgecolors="#2ca02c", linewidths=1.5, zorder=5)

    ax.scatter([], [], marker="^", color="#d62728", label="pivot high (touch)")
    ax.scatter([], [], marker="^", facecolors="none", edgecolors="#d62728", label="pivot high (interior)")
    ax.scatter([], [], marker="v", color="#2ca02c", label="pivot low (touch)")
    ax.scatter([], [], marker="v", facecolors="none", edgecolors="#2ca02c", label="pivot low (interior)")

    ax.set_title(f"{sym} bars {start}-{end} ({df['date'].iloc[start].date()} to {df['date'].iloc[end].date()}) "
                 f"| hi_slope={hi_boundary.slope:.4f} lo_slope={lo_boundary.slope:.4f} "
                 f"| touches hi={len(hi_boundary.touch_indices)}/{len(hi_pivots)} lo={len(lo_boundary.touch_indices)}/{len(lo_pivots)}")
    ax.legend(loc="best", fontsize=7)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    out_path = os.path.join(OUT_DIR, f"{i+1:02d}_{sym}_{start}_{end}.png")
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"  saved {out_path}")
