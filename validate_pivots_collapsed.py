"""
validate_pivots_collapsed.py
------------------------------
Re-runs pivot detection for TOWL and ISIL using find_pivots_collapsed()
(frozen-close collapsing preprocessing, see pivots.py design note 5) and
compares against the original raw find_pivots() results to confirm the
spurious multi-pivot-per-plateau behavior collapses to a single pivot per
frozen run, matching what KEL already showed without collapsing (KEL's
frozen run has high=low=close identical, so it never triggered the bug).

Validation only -- triangle-assembly logic untouched.
"""
import os
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pivots import find_pivots, find_pivots_collapsed

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
OUT_DIR = "C:/Users/Lenovo/psx_pipeline/pivot_validation_charts"
os.makedirs(OUT_DIR, exist_ok=True)

TICKERS = ["TOWL", "ISIL"]

# same windows used for the earlier zoom diagnostics, so before/after is
# a direct visual comparison
ZOOM_WINDOWS = {
    "TOWL": ("2011-01-01", "2012-05-31"),
    "ISIL": ("2011-02-01", "2011-06-30"),
}

conn = sqlite3.connect(DB_PATH)

for sym in TICKERS:
    df = pd.read_sql_query(
        "SELECT date, high, low, close FROM prices_adjusted WHERE symbol = ? ORDER BY date",
        conn, params=(sym,)
    )
    df["date"] = pd.to_datetime(df["date"])
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()

    raw_pivots = find_pivots(highs, lows, left=3, right=3)
    collapsed_pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)

    for label, pivots in [("RAW", raw_pivots), ("COLLAPSED", collapsed_pivots)]:
        hi = [p for p in pivots if p.kind == "high"]
        lo = [p for p in pivots if p.kind == "low"]
        print(f"{sym} [{label}]: {len(hi)} pivot highs, {len(lo)} pivot lows (total {len(pivots)})")

    # --- full-history chart, collapsed pivots ---
    fig, ax = plt.subplots(figsize=(22, 6))
    ax.plot(df["date"], df["close"], linewidth=0.6, color="#333333", label="close")
    hi = [p for p in collapsed_pivots if p.kind == "high"]
    lo = [p for p in collapsed_pivots if p.kind == "low"]
    if hi:
        ax.scatter([df["date"].iloc[p.index] for p in hi], [p.price for p in hi],
                    marker="^", color="#d62728", s=18, zorder=5, label=f"pivot high (n={len(hi)})")
    if lo:
        ax.scatter([df["date"].iloc[p.index] for p in lo], [p.price for p in lo],
                    marker="v", color="#2ca02c", s=18, zorder=5, label=f"pivot low (n={len(lo)})")
    ax.set_title(f"{sym} — find_pivots_collapsed(left=3,right=3) [frozen-close collapsed] — "
                 f"{df['date'].min().date()} to {df['date'].max().date()} (n={len(df)} bars)")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    out_path = os.path.join(OUT_DIR, f"{sym}_pivots_COLLAPSED.png")
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"  saved {out_path}")

    # --- zoomed before/after comparison over the known plateau window ---
    start, end = ZOOM_WINDOWS[sym]
    mask = (df["date"] >= start) & (df["date"] <= end)
    sub_idx = df.index[mask]
    sub = df.loc[sub_idx]

    fig, axes = plt.subplots(2, 1, figsize=(18, 11), sharex=True)
    for ax, pivots, title in [
        (axes[0], raw_pivots, "RAW find_pivots() -- before collapsing"),
        (axes[1], collapsed_pivots, "find_pivots_collapsed() -- after frozen-close collapsing"),
    ]:
        ax.plot(sub["date"], sub["close"], marker="o", markersize=3, linewidth=1, color="#333333")
        for p in pivots:
            if p.index in sub_idx.values:
                d = df["date"].iloc[p.index]
                marker = "^" if p.kind == "high" else "v"
                color = "#d62728" if p.kind == "high" else "#2ca02c"
                ax.scatter([d], [p.price], marker=marker, color=color, s=90, zorder=5)
                ax.annotate(f"{p.index}", (d, p.price), fontsize=7,
                            xytext=(0, 6 if p.kind == "high" else -12),
                            textcoords="offset points", ha="center")
        ax.set_title(f"{sym} {start} to {end} — {title}")
        ax.grid(alpha=0.3)

    fig.autofmt_xdate()
    fig.tight_layout()
    out_path = os.path.join(OUT_DIR, f"{sym}_ZOOM_before_after.png")
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    print(f"  saved {out_path}")

conn.close()
