"""
validate_triangle_full_universe.py
-------------------------------------
Full active-universe run, symbol-level exclusion applied UPFRONT via
research_filters.exclude_known_artifact_symbols() -- SGPL, DWAE, FRCL
dropped from the symbol list before any per-symbol work starts (302 of
305 active symbols remain). See research_filters.py's KNOWN_ARTIFACT_SYMBOLS
docstring and Triangle_Pattern_Specification_v1.md Section 8 for the full
rationale: these 3 symbols share a prices_adjusted adjustment-factor
artifact (near-zero pinned prices for hundreds of bars despite real
volume), confirmed present in an earlier full-universe run before this
exclusion was added. This exclusion is upfront and symbol-level (removed
from the meta list before the price-history loop even starts), not a
per-window or per-price filter like drop_placeholder_zero_bars().

The "~250" figure originally quoted for this stage was approximate; the
actual active universe is 305, 302 after this exclusion.

Pipeline otherwise UNCHANGED from the validated 5-ticker and 18-ticker
versions:
  1. find_pivots_collapsed() -- frozen-close collapsing
  2. drop_placeholder_zero_bars() -- placeholder-zero guard
  3. fit_boundary() -- 80-bar windows, 50% overlap, tolerance_pct=0.015
  4. assemble_triangle() -- includes the is_forced_line() spacing gate
  5. 5-category breakout-occurrence count (same horizon rule, same
     5-bar whipsaw threshold)

Liquidity tier is trading-day-coverage-based (>=90%=liquid, 70-89%=mid,
<70%=thin) -- documentation/metadata only, consumed by nothing in the
pivot/boundary/triangle compute path.

No Type 1-4 classification, no stop-loss logic. Counting only.
"""
import sqlite3
import time
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary, check_violation
from triangle import assemble_triangle, classify_triangle, compute_apex, is_forced_line
from research_filters import drop_placeholder_zero_bars, exclude_known_artifact_symbols, KNOWN_ARTIFACT_SYMBOLS

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"

WINDOW_LEN = 80
STEP = 40
MIN_PIVOTS_PER_SIDE = 3
TOLERANCE_PCT = 0.015
HORIZON_BARS = 40
APEX_BUFFER_BARS = 5
WHIPSAW_GAP_THRESHOLD = 5

t0 = time.time()
conn = sqlite3.connect(DB_PATH)

meta = pd.read_sql_query(
    "SELECT symbol, sector FROM stock_metadata WHERE is_active = 1 ORDER BY symbol", conn
)
n_before_exclusion = len(meta)
meta = meta[meta["symbol"].isin(exclude_known_artifact_symbols(meta["symbol"]))].reset_index(drop=True)
print(f"{n_before_exclusion} active symbols in universe; "
      f"{n_before_exclusion - len(meta)} excluded ({sorted(KNOWN_ARTIFACT_SYMBOLS)}); "
      f"{len(meta)} remain")

all_prices = pd.read_sql_query(
    """
    SELECT p.symbol, p.date, p.open, p.high, p.low, p.close, p.volume
    FROM prices_adjusted p JOIN stock_metadata m ON m.symbol = p.symbol
    WHERE m.is_active = 1
    ORDER BY p.symbol, p.date
    """,
    conn
)
conn.close()
all_prices = all_prices[all_prices["symbol"].isin(meta["symbol"])].reset_index(drop=True)
all_prices["date"] = pd.to_datetime(all_prices["date"])
print(f"Bulk fetch: {len(all_prices)} rows (post-exclusion), {time.time()-t0:.1f}s")

stats = {
    "windows_examined": 0,
    "skipped_too_few_pivots": 0,
    "boundary_fit_none": 0,
    "converging_candidates": 0,
    "touch_count": 0,
    "forced_line": 0,
    "not_triangle_shape": 0,
    "apex_behind_or_none": 0,
    "apex_too_far": 0,
    "duration_invalid": 0,
    "classified_triangle": 0,
}

symbol_notes = []       # (symbol, sector, tier, n_rows, n_placeholder_dropped, coverage_pct, min_positive_close)
suspect_windows = []    # any classified triangle with a suspiciously low touch price (near-zero artifact leakage)
triangles = []          # (sector, symbol, df, start, end, hi_boundary, lo_boundary, tri)

n_symbols_done = 0
for sym, sector in zip(meta["symbol"], meta["sector"]):
    df = all_prices[all_prices["symbol"] == sym].reset_index(drop=True)
    if len(df) == 0:
        continue

    span_days = (df["date"].max() - df["date"].min()).days
    coverage = len(df) / (span_days / 365.25 * 252) if span_days > 0 else 0
    tier = "liquid" if coverage >= 0.90 else ("mid" if coverage >= 0.70 else "thin")
    min_pos_close = df.loc[df["close"] > 0, "close"].min() if (df["close"] > 0).any() else None

    n_before = len(df)
    df = drop_placeholder_zero_bars(df)
    n_dropped = n_before - len(df)
    symbol_notes.append((sym, sector, tier, n_before, n_dropped, round(coverage, 3), min_pos_close))

    if len(df) < WINDOW_LEN + 1:
        continue

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
            continue
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
            triangles.append((sector, sym, df, start, end, hi_boundary, lo_boundary, tri))

            min_touch_price = min(
                [p.price for p in hi_pivots if p.index in hi_boundary.touch_indices] +
                [p.price for p in lo_pivots if p.index in lo_boundary.touch_indices]
            )
            if min_touch_price < 1.0 or sym in KNOWN_ARTIFACT_SYMBOLS:
                suspect_windows.append((sym, sector, start, end, tri.kind, min_touch_price))
            continue

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

    n_symbols_done += 1
    if n_symbols_done % 50 == 0:
        print(f"  ...{n_symbols_done}/{len(meta)} symbols done, {time.time()-t0:.1f}s elapsed, "
              f"{stats['classified_triangle']} classified so far")

print(f"\nDone: {n_symbols_done} symbols processed, {time.time()-t0:.1f}s total")

print("\n=== Funnel ===")
for k in ["windows_examined", "skipped_too_few_pivots", "boundary_fit_none", "converging_candidates", "classified_triangle"]:
    print(f"  {k}: {stats[k]}")

print("\n=== Rejection breakdown (of converging_candidates) ===")
rej_total = 0
for k in ["touch_count", "forced_line", "not_triangle_shape", "apex_behind_or_none", "apex_too_far", "duration_invalid"]:
    print(f"  {k}: {stats[k]}")
    rej_total += stats[k]
print(f"  TOTAL rejected: {rej_total}  (+ classified {stats['classified_triangle']} = {rej_total + stats['classified_triangle']}, should equal converging_candidates {stats['converging_candidates']})")

kind_counts = {}
for sec, sym, df, start, end, hi_b, lo_b, tri in triangles:
    kind_counts[tri.kind] = kind_counts.get(tri.kind, 0) + 1
print(f"\n=== Classification breakdown ({stats['classified_triangle']} classified triangles) ===")
for k, v in kind_counts.items():
    print(f"  {k}: {v}")

# ---- data-quality notes ----
notes_df = pd.DataFrame(symbol_notes, columns=["symbol", "sector", "tier", "n_rows", "n_placeholder_dropped", "coverage", "min_positive_close"])
notes_df.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_full_universe_symbol_notes.csv", index=False)

print(f"\n=== Symbols with placeholder-zero bars dropped: {(notes_df['n_placeholder_dropped']>0).sum()} ===")
print(notes_df[notes_df["n_placeholder_dropped"] > 0].sort_values("n_placeholder_dropped", ascending=False).head(20).to_string(index=False))

print(f"\n=== Tier distribution ===")
print(notes_df["tier"].value_counts().to_string())

print(f"\n=== Known near-zero-artifact symbols (SGPL/DWAE/FRCL) -- min positive close ===")
print(notes_df[notes_df["symbol"].isin(KNOWN_ARTIFACT_SYMBOLS)].to_string(index=False))

print(f"\n=== Suspect classified windows (min touch price < 1.0, or known artifact symbol): {len(suspect_windows)} ===")
for row in suspect_windows:
    print(f"  {row}")

# ---- breakout occurrence, 5-category ----
print("\n=== Breakout occurrence (5-category) ===")
results = []
for sec, sym, df, start, end, hi_boundary, lo_boundary, tri in triangles:
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

    results.append((sec, sym, start, end, tri.kind, outcome, up_idx, down_idx, gap))

res_df = pd.DataFrame(results, columns=["sector", "symbol", "start", "end", "kind",
                                         "outcome", "up_idx", "down_idx", "gap"])

OUTCOME_CATEGORIES = ["up", "down", "whipsaw", "sequential", "none"]
print(res_df["outcome"].value_counts().reindex(OUTCOME_CATEGORIES, fill_value=0).to_string())

print("\n=== By kind ===")
print(res_df.groupby(["kind", "outcome"]).size().unstack(fill_value=0)
      .reindex(columns=OUTCOME_CATEGORIES, fill_value=0).to_string())

# minimum whipsaw gap seen (compare against the tightest before: KOHC gap=1)
whipsaws = res_df[res_df["outcome"] == "whipsaw"].copy()
whipsaws["gap"] = whipsaws["gap"].astype(int)
print(f"\n=== Whipsaw gap distribution (n={len(whipsaws)}) ===")
print(whipsaws[["sector", "symbol", "start", "end", "gap"]].sort_values("gap").to_string(index=False))

res_df.to_csv("C:/Users/Lenovo/psx_pipeline/triangle_full_universe_results.csv", index=False)
print(f"\nSaved {len(res_df)} classified-triangle rows to triangle_full_universe_results.csv")
print(f"Saved {len(notes_df)} symbol notes to triangle_full_universe_symbol_notes.csv")
print(f"\nTotal runtime: {time.time()-t0:.1f}s")
