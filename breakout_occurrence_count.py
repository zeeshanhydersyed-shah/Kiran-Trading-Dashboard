"""
breakout_occurrence_count.py
------------------------------
Raw occurrence count only -- NOT the Type 1-4 breakout classification.
For each of the (post-forced-line-filter) classified triangle candidates,
looks forward from window_end_index and checks whether price ever closes
decisively beyond the upper boundary (breakout up) or lower boundary
(breakout down) within an observation horizon, using the existing
check_violation() from boundaries.py unmodified.

Observation horizon: min(window_end_index + 40, apex_index + 5), capped at
the ticker's available data length. Combines both options the task allowed
("~40 bars" or "apex + small buffer") by taking whichever is SHORTER --
apex_index can sit up to 3x the window width past window_end_index (per
assemble_triangle's max_apex_distance_multiplier), so an apex-only horizon
could stretch to 240+ bars for an 80-bar window; capping at a fixed 40-bar
ceiling avoids waiting on a pattern most chartists would already consider
stale, while the apex+5 cap independently stops the check shortly past the
point where the pattern is theoretically supposed to have resolved, for
candidates whose apex sits closer than 40 bars out.

Outcome categories (5, not 4): "up", "down", "whipsaw" (both boundaries
violated within WHIPSAW_GAP_THRESHOLD bars of each other -- treated as
effectively the same rapid two-sided event), "sequential" (both boundaries
violated, but more than WHIPSAW_GAP_THRESHOLD bars apart -- structurally a
different phenomenon: two temporally distinct events, price broke one way,
held for a real stretch, then separately broke the other way too), and
"none" (never broke out within the horizon). "sequential" is never folded
into up/down by first-occurrence or into whipsaw -- it is its own category,
per explicit decision (see Triangle_Pattern_Specification_v1.md Section 6.1).

No Type 1-4 classification, no stop-loss/entry/exit logic. Counting only.
"""
import sqlite3
import pandas as pd

from pivots import find_pivots_collapsed
from boundaries import fit_boundary, check_violation
from triangle import assemble_triangle, is_forced_line
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
TICKERS = ["OGDC", "LUCK", "KEL", "ISIL", "TOWL"]

WINDOW_LEN = 80
STEP = 40
MIN_PIVOTS_PER_SIDE = 3
TOLERANCE_PCT = 0.015
HORIZON_BARS = 40
APEX_BUFFER_BARS = 5

conn = sqlite3.connect(DB_PATH)

triangles = []  # (symbol, df, start, end, hi_boundary, lo_boundary, tri)

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
        if hi_boundary.slope > lo_boundary.slope + 1e-9:
            continue

        tri = assemble_triangle(
            hi_boundary, lo_boundary,
            window_start_index=start, window_end_index=end,
            start_date=df["date"].iloc[start].date(), end_date=df["date"].iloc[end].date(),
        )
        if tri is not None:
            triangles.append((sym, df, start, end, hi_boundary, lo_boundary, tri))

conn.close()
print(f"{len(triangles)} classified triangle candidates (post forced-line filter) to check for breakout occurrence\n")

results = []  # (sym, start, end, kind, outcome, up_idx, down_idx, horizon_end)

for sym, df, start, end, hi_boundary, lo_boundary, tri in triangles:
    n = len(df)
    horizon_end = min(n - 1, end + HORIZON_BARS, int(tri.apex_index) + APEX_BUFFER_BARS)
    horizon_end = max(horizon_end, end)  # never look backward
    closes = df["close"].tolist()

    up_violations = check_violation(hi_boundary, closes, start_index=end + 1, end_index=horizon_end,
                                     direction="upper", tolerance_pct=TOLERANCE_PCT)
    down_violations = check_violation(lo_boundary, closes, start_index=end + 1, end_index=horizon_end,
                                       direction="lower", tolerance_pct=TOLERANCE_PCT)

    up_idx = up_violations[0] if up_violations else None
    down_idx = down_violations[0] if down_violations else None

    gap = abs(up_idx - down_idx) if (up_idx is not None and down_idx is not None) else None

    results.append((sym, start, end, tri.kind, up_idx, down_idx, gap, horizon_end))
    gap_note = f"  gap={gap} bars" if gap is not None else ""
    print(f"{sym} {start}-{end} [{tri.kind}] horizon_end={horizon_end} "
          f"up_break={up_idx} down_break={down_idx}{gap_note}")

res_df = pd.DataFrame(results, columns=["symbol", "start", "end", "kind",
                                         "up_idx", "down_idx", "gap", "horizon_end"])

print("\n=== Raw bar-gaps for the 3 both-violated candidates (no threshold applied) ===")
both_df = res_df[res_df["gap"].notna()].copy()
print(both_df[["symbol", "start", "end", "kind", "up_idx", "down_idx", "gap"]].to_string(index=False))

# WHIPSAW_GAP_THRESHOLD: reuses is_forced_line()'s existing min_pairwise_gap_bars
# (5) rather than inventing a new constant -- chosen because it cleanly separates
# the natural clustering actually observed (3 vs 18/31 bars), not an arbitrary
# guess. A gap <= threshold is a "whipsaw": both boundaries violated close
# enough together to read as one rapid two-sided event. A gap > threshold is
# "sequential": two temporally distinct events (broke out, held for a real
# stretch, then separately broke the other way too) -- structurally different
# from a whipsaw, and deliberately its OWN category, not force-resolved into
# up/down by first-occurrence and not folded into whipsaw. See
# Triangle_Pattern_Specification_v1.md Section 6.1 for the documented decision.
WHIPSAW_GAP_THRESHOLD = 5

OUTCOME_CATEGORIES = ["up", "down", "whipsaw", "sequential", "none"]


def classify_outcome(row):
    up_hit = pd.notna(row["up_idx"])
    down_hit = pd.notna(row["down_idx"])
    if not up_hit and not down_hit:
        return "none"
    if up_hit and not down_hit:
        return "up"
    if down_hit and not up_hit:
        return "down"
    # both violated
    if row["gap"] <= WHIPSAW_GAP_THRESHOLD:
        return "whipsaw"
    return "sequential"


res_df["outcome"] = res_df.apply(classify_outcome, axis=1)

print(f"\n=== 5-category occurrence table (whipsaw threshold = {WHIPSAW_GAP_THRESHOLD} bars) ===")
for _, row in res_df.iterrows():
    print(f"{row.symbol} {row.start}-{row.end} [{row.kind}] -> {row.outcome.upper()}")

print("\n=== Overall counts ===")
print(res_df["outcome"].value_counts().reindex(OUTCOME_CATEGORIES, fill_value=0).to_string())

print("\n=== By kind ===")
print(res_df.groupby(["kind", "outcome"]).size().unstack(fill_value=0)
      .reindex(columns=OUTCOME_CATEGORIES, fill_value=0).to_string())

seq = res_df[res_df["outcome"] == "sequential"]
print(f"\n=== Sequential (both directions) detail: {len(seq)} candidate(s), gap > {WHIPSAW_GAP_THRESHOLD} bars ===")
print(seq[["symbol", "start", "end", "kind", "up_idx", "down_idx", "gap"]].to_string(index=False))
