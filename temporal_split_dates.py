"""
temporal_split_dates.py
--------------------------
Derives each candidate's breakout calendar date (not bar index) for the
temporal-holdout re-validation task. Candidate CSVs throughout this study
only carry bar indices -- this looks up the actual date at breakout_idx
per candidate directly from prices_adjusted (post drop_placeholder_zero_bars,
same pipeline as everywhere else in this study).

breakout_idx convention matches breakout_classification_variant_comparison.py
exactly: up_idx for outcome="up", down_idx for outcome="down", the earlier
of the two (first chronological violation) for whipsaw/sequential.
outcome="none" candidates never broke out at all -- no breakout_idx exists,
so the WINDOW END bar's date is used instead as the best available proxy
for "when this candidate happened," explicitly flagged as a different
convention for those 2 rows.
"""

import sqlite3
import pandas as pd

from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"

candidates = pd.read_csv("triangle_full_universe_results.csv")
conn = sqlite3.connect(DB_PATH)
symbol_cache = {}

rows = []
for _, cand in candidates.iterrows():
    sym = cand["symbol"]
    start, end = int(cand["start"]), int(cand["end"])
    outcome = cand["outcome"]
    up_idx, down_idx = cand["up_idx"], cand["down_idx"]

    if sym not in symbol_cache:
        df = pd.read_sql_query(
            "SELECT date FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        df["date"] = pd.to_datetime(df["date"])
        # drop_placeholder_zero_bars needs OHLCV columns; re-fetch properly
        full = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
            conn, params=(sym,)
        )
        full = drop_placeholder_zero_bars(full)
        symbol_cache[sym] = pd.to_datetime(full["date"]).tolist()

    dates = symbol_cache[sym]

    if outcome == "none":
        idx = end
        date_convention = "window_end (no breakout occurred)"
    elif outcome == "up":
        idx = int(up_idx)
        date_convention = "breakout_idx"
    elif outcome == "down":
        idx = int(down_idx)
        date_convention = "breakout_idx"
    else:  # whipsaw or sequential
        idx = int(up_idx) if up_idx <= down_idx else int(down_idx)
        date_convention = "breakout_idx (first chronological)"

    if idx >= len(dates):
        breakout_date = None
    else:
        breakout_date = dates[idx]

    rows.append({
        "symbol": sym, "start": start, "end": end, "outcome": outcome,
        "breakout_idx_used": idx, "breakout_date": breakout_date, "date_convention": date_convention,
    })

conn.close()

out = pd.DataFrame(rows)
out.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_breakout_dates.csv", index=False)
print(f"{len(out)} candidates dated, {out['breakout_date'].isna().sum()} unresolvable")
print(f"\nDate range: {out['breakout_date'].min()} to {out['breakout_date'].max()}")
print(f"\nCandidates by year:")
print(out["breakout_date"].dt.year.value_counts().sort_index().to_string())
