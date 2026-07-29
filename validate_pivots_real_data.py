"""
validate_pivots_real_data.py
-----------------------------
Validation-only script: runs find_pivots() (pivots.py, left=3 right=3)
against real PSX full-history data for 5 tickers, pulled from the local
SQLite Kiran DB (prices_adjusted, full 2005-2026 history -- Supabase only
holds a rolling ~2yr window and isn't used here). Saves one PNG per ticker
with the close-price line and detected pivot highs/lows marked.

Does NOT touch triangle-assembly/boundary-fitting logic. Validation only.
"""
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from pivots import find_pivots

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
OUT_DIR = "C:/Users/Lenovo/psx_pipeline/pivot_validation_charts"

# 2 liquid blue-chips + 3 thin/circuit-lock-prone names (verified real prices
# and nonzero volume during their plateau runs -- see session notes; SGPL/
# DWAE/FRCL were rejected as candidates because their "plateaus" were a
# near-zero adjusted-price data artifact, not genuine circuit-lock trading)
TICKERS = ["OGDC", "LUCK", "KEL", "ISIL", "TOWL"]

import os
os.makedirs(OUT_DIR, exist_ok=True)

conn = sqlite3.connect(DB_PATH)

summary_rows = []

for sym in TICKERS:
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices_adjusted "
        "WHERE symbol = ? ORDER BY date",
        conn, params=(sym,)
    )
    df["date"] = pd.to_datetime(df["date"])
    highs = df["high"].tolist()
    lows = df["low"].tolist()

    pivots = find_pivots(highs, lows, left=3, right=3)
    hi_pivots = [p for p in pivots if p.kind == "high"]
    lo_pivots = [p for p in pivots if p.kind == "low"]

    fig, ax = plt.subplots(figsize=(22, 6))
    ax.plot(df["date"], df["close"], linewidth=0.6, color="#333333", label="close")

    if hi_pivots:
        hx = [df["date"].iloc[p.index] for p in hi_pivots]
        hy = [p.price for p in hi_pivots]
        ax.scatter(hx, hy, marker="^", color="#d62728", s=18, zorder=5, label=f"pivot high (n={len(hi_pivots)})")
    if lo_pivots:
        lx = [df["date"].iloc[p.index] for p in lo_pivots]
        ly = [p.price for p in lo_pivots]
        ax.scatter(lx, ly, marker="v", color="#2ca02c", s=18, zorder=5, label=f"pivot low (n={len(lo_pivots)})")

    ax.set_title(f"{sym} — close price + find_pivots(left=3,right=3) — {df['date'].min().date()} to {df['date'].max().date()} (n={len(df)} bars)")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()

    out_path = os.path.join(OUT_DIR, f"{sym}_pivots.png")
    fig.savefig(out_path, dpi=130)
    plt.close(fig)

    summary_rows.append({
        "symbol": sym,
        "n_bars": len(df),
        "date_range": f"{df['date'].min().date()} -> {df['date'].max().date()}",
        "n_pivot_high": len(hi_pivots),
        "n_pivot_low": len(lo_pivots),
        "png": out_path,
    })
    print(f"{sym}: {len(df)} bars, {len(hi_pivots)} pivot highs, {len(lo_pivots)} pivot lows -> {out_path}")

conn.close()

summary = pd.DataFrame(summary_rows)
print("\n" + summary.to_string(index=False))
