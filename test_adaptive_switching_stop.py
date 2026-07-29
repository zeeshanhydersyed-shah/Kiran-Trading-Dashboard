"""
test_adaptive_switching_stop.py
----------------------------------
Synthetic, hand-verified tests for adaptive_switching_stop.py, before any
real-data run. Same discipline as every prior module.

Tests (a)-(c) use a flat, hand-constructed boundary (no real pivot data
needed -- classify_breakout() only needs a Boundary object, highs, lows).
Test (d) uses real candidates and real refit boundaries, as a WIRING
sanity check: since adaptive_switching_stop.py calls the real
classify_breakout() internally (not a hand-copied breach formula), a
mismatch here would mean this module is passing the wrong boundary,
direction, or horizon -- not that the underlying formula differs.
"""

import sqlite3
import pandas as pd

from boundaries import Boundary
from breakout_classification import classify_breakout
from adaptive_switching_stop import adaptive_switching_walk_forward

results = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def flat_boundary(price):
    return Boundary(slope=0.0, intercept=price, touch_indices=[], all_candidate_indices=[])


# ─────────────────────────────────────────────────────────────────────
# Test (a): never breaches the boundary before LFD touches -- confirms
# no switch, result identical to what static LFD alone would give.
# Boundary flat @ 100 (breach threshold 98.5). breakout_idx=20, entry=105,
# lfd_level=lows[19]=100 (R=5). Bar 21: low=99.5 touches LFD (<=100) but
# does NOT breach the boundary (99.5 > 98.5) -- LFD wins immediately,
# checked before breach on this bar regardless.
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 19 + [100.0, 105.0, 100.5]
highs = [100.0] * 19 + [100.0, 106.0, 101.0]
lows = [100.0] * 19 + [100.0, 104.0, 99.5]
b = flat_boundary(100.0)
r = adaptive_switching_walk_forward(closes, highs, lows, breakout_idx=20, direction="up",
                                     boundary=b, opposite_stop=85.0)
check("Test a1: no switch, exits on LFD at bar 21",
      not r.switched and r.exit_bar == 21 and r.exit_stop == "lfd",
      f"got switched={r.switched}, exit_bar={r.exit_bar}, exit_stop={r.exit_stop}")
check("Test a2: both R conventions agree, = -1.0 (identical to static LFD)",
      approx(r.realized_R_fixed, -1.0) and approx(r.realized_R_rebased, -1.0))

# ─────────────────────────────────────────────────────────────────────
# Test (b): breaches the boundary before LFD touches, then opposite
# triggers later -- confirms the switch happens and both R conventions
# compute correctly.
# lfd_level=lows[19]=95 (R_lfd=10.0). opposite_stop=85.0 (R_opposite=20.0).
# Bar 21: low=98.0 -- breaches boundary (98.0 < 98.5) but does NOT touch
# LFD (98.0 > 95) -- switch triggers at bar 21, opposite (85) not yet
# touched same bar (98.0 > 85).
# Bar 22: low=84.0 -- touches opposite (84.0 <= 85) -- exit.
#   realized_R_fixed   = -(r_opposite_denom / r_lfd_denom) = -(20/10) = -2.0
#   realized_R_rebased = -1.0
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 19 + [97.0, 105.0, 98.5, 85.5]
highs = [100.0] * 19 + [98.0, 106.0, 99.0, 86.0]
lows = [100.0] * 19 + [95.0, 104.0, 98.0, 84.0]
b = flat_boundary(100.0)
r = adaptive_switching_walk_forward(closes, highs, lows, breakout_idx=20, direction="up",
                                     boundary=b, opposite_stop=85.0)
check("Test b1: breach detected at bar 21, switch triggers there",
      r.first_breach_idx == 21 and r.switched and r.switch_bar == 21,
      f"got first_breach_idx={r.first_breach_idx}, switched={r.switched}, switch_bar={r.switch_bar}")
check("Test b2: exits on opposite at bar 22 (not bar 21 -- opposite not yet reached same bar)",
      r.exit_bar == 22 and r.exit_stop == "opposite",
      f"got exit_bar={r.exit_bar}, exit_stop={r.exit_stop}")
check("Test b3: r_lfd_denom=10.0, r_opposite_denom=20.0",
      approx(r.r_lfd_denom, 10.0) and approx(r.r_opposite_denom, 20.0))
check("Test b4: realized_R_fixed=-2.0 (loss in ORIGINAL LFD-risk units, since opposite is 2x wider)",
      approx(r.realized_R_fixed, -2.0), f"got {r.realized_R_fixed}")
check("Test b5: realized_R_rebased=-1.0 (clean stop-out in the NEW, re-based units)",
      approx(r.realized_R_rebased, -1.0), f"got {r.realized_R_rebased}")

# ─────────────────────────────────────────────────────────────────────
# Test (c): switch happens, then price recovers past the horizon without
# touching either stop post-switch -- confirms the horizon-close
# fallback works correctly for a mid-trade switch, under BOTH
# denominator conventions.
# Same breach-at-21 setup, opposite_stop=90.0 this time (R_opposite=15.0).
# Bars 22-30: lows stay flat at 97 (never <=90). closes[30]=99.0.
#   realized_R_fixed   = mark_to_market(99, 105, r_lfd_denom=10)      = (99-105)/10 = -0.6
#   realized_R_rebased = mark_to_market(99, 105, r_opposite_denom=15) = (99-105)/15 = -0.4
# ─────────────────────────────────────────────────────────────────────
closes = [100.0] * 19 + [97.0, 105.0, 98.5] + [97.5] * 8 + [99.0]
highs = [100.0] * 19 + [98.0, 106.0, 99.0] + [98.5] * 8 + [99.5]
lows = [100.0] * 19 + [95.0, 104.0, 98.0] + [97.0] * 8 + [98.0]
b = flat_boundary(100.0)
r = adaptive_switching_walk_forward(closes, highs, lows, breakout_idx=20, direction="up",
                                     boundary=b, opposite_stop=90.0)
check("Test c0: array ends at bar 30", len(closes) - 1 == 30)
check("Test c1: switched at bar 21, never exits, horizon_reached=True at bar 30",
      r.switched and r.switch_bar == 21 and r.horizon_reached and r.exit_bar == 30 and r.exit_stop is None,
      f"got switched={r.switched}, switch_bar={r.switch_bar}, horizon_reached={r.horizon_reached}, "
      f"exit_bar={r.exit_bar}, exit_stop={r.exit_stop}")
check("Test c2: realized_R_fixed=-0.6, realized_R_rebased=-0.4",
      approx(r.realized_R_fixed, -0.6) and approx(r.realized_R_rebased, -0.4),
      f"got fixed={r.realized_R_fixed}, rebased={r.realized_R_rebased}")

# ─────────────────────────────────────────────────────────────────────
# Test (d): WIRING sanity check against real candidates -- confirm this
# module's use of classify_breakout() (boundary side, direction,
# tolerance_pct) reproduces the already-recorded Type 1/2/3 result when
# given the SAME (original, apex-based) horizon the classification stage
# used -- i.e. this module is passing the right boundary/direction, not
# a subtly different one. Also reports (not asserts, since this is an
# expected/documented deviation, not a bug) how the breach bar compares
# under the adaptive rule's OWN 90-bar horizon vs the original.
# ─────────────────────────────────────────────────────────────────────
from pivots import find_pivots_collapsed
from boundaries import fit_boundary
from triangle import assemble_triangle
from research_filters import drop_placeholder_zero_bars

DB_PATH = "C:/Users/Lenovo/psx_pipeline/psx_data.db"
TOLERANCE_PCT = 0.015
HORIZON_BARS = 40
APEX_BUFFER_BARS = 5

conn = sqlite3.connect(DB_PATH)
candidates_csv = pd.read_csv("triangle_full_universe_results.csv")
variants_csv = pd.read_csv("breakout_classification_variant_results.csv")
variants_csv = variants_csv[variants_csv["variant"] == "trigger"]

real_cases = [("ABL", 1000, 1080, 1.0), ("AGIL", 1520, 1600, 2.0), ("ACPL", 600, 680, 3.0)]

for sym, start, end, expected_type in real_cases:
    cand = candidates_csv[(candidates_csv["symbol"] == sym)
                           & (candidates_csv["start"] == start)
                           & (candidates_csv["end"] == end)].iloc[0]
    outcome = cand["outcome"]
    up_idx, down_idx = cand["up_idx"], cand["down_idx"]
    if outcome == "up":
        breakout_idx, direction = int(up_idx), "up"
    elif outcome == "down":
        breakout_idx, direction = int(down_idx), "down"
    else:
        breakout_idx, direction = (int(up_idx), "up") if up_idx <= down_idx else (int(down_idx), "down")

    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices_adjusted WHERE symbol = ? ORDER BY date",
        conn, params=(sym,)
    )
    df = drop_placeholder_zero_bars(df)
    highs_r = df["high"].tolist()
    lows_r = df["low"].tolist()
    closes_r = df["close"].tolist()
    all_pivots = find_pivots_collapsed(closes_r, highs_r, lows_r, left=3, right=3)
    hi_pivots = [p for p in all_pivots if p.kind == "high" and start <= p.index <= end]
    lo_pivots = [p for p in all_pivots if p.kind == "low" and start <= p.index <= end]
    hi_boundary = fit_boundary(hi_pivots, tolerance_pct=TOLERANCE_PCT)
    lo_boundary = fit_boundary(lo_pivots, tolerance_pct=TOLERANCE_PCT)

    n = len(df)
    start_date = df["date"].iloc[start]
    end_date = df["date"].iloc[end]
    tri = assemble_triangle(hi_boundary, lo_boundary, window_start_index=start, window_end_index=end,
                             start_date=pd.Timestamp(start_date).date(), end_date=pd.Timestamp(end_date).date())
    original_horizon_end = min(n - 1, end + HORIZON_BARS, int(tri.apex_index) + APEX_BUFFER_BARS)
    original_horizon_end = max(original_horizon_end, end)

    boundary = hi_boundary if direction == "up" else lo_boundary

    # Reproduce the ORIGINAL classification exactly, same horizon as breakout_classification_variant_results.csv:
    cbr_original_horizon = classify_breakout(boundary, highs_r, lows_r, breakout_idx, direction,
                                              original_horizon_end, tolerance_pct=TOLERANCE_PCT, lfd_variant="full")
    matches = cbr_original_horizon.type == expected_type
    check(f"Test d ({sym} {start}-{end}): reproduces recorded Type {int(expected_type)} "
          f"under the ORIGINAL apex-based horizon",
          matches, f"got type={cbr_original_horizon.type}")

    # This module's own call, using its 90-bar horizon -- report (don't assert) any divergence.
    r_adaptive = adaptive_switching_walk_forward(closes_r, highs_r, lows_r, breakout_idx, direction,
                                                  boundary=boundary, opposite_stop=lows_r[0])  # opposite_stop irrelevant to breach timing
    same_breach = r_adaptive.first_breach_idx == cbr_original_horizon.first_breach_idx
    print(f"    [info] {sym} {start}-{end}: original-horizon first_breach_idx="
          f"{cbr_original_horizon.first_breach_idx}, adaptive 90-bar-horizon first_breach_idx="
          f"{r_adaptive.first_breach_idx}  ({'same' if same_breach else 'DIFFERS -- wider horizon saw more'})")

conn.close()

# ═══════════════════════════════════════════════════════════════════════
n_pass = sum(results)
n_total = len(results)
print(f"\n{'='*60}\n{n_pass}/{n_total} PASSED\n{'='*60}")
if n_pass != n_total:
    raise SystemExit(1)
