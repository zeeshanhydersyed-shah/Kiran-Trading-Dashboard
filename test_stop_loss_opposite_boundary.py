"""
test_stop_loss_opposite_boundary.py
--------------------------------------
Synthetic, hand-verified tests for the third stop arm added to
walk_forward() in stop_loss_definitions.py: opposite_stop, a FIXED price
level (the un-broken boundary's price at the breakout bar, computed by
the caller -- this module never imports boundaries.py).

Run test_stop_loss_definitions.py FIRST and confirm it's still 28/28
before trusting these -- these tests only cover the NEW opposite_stop
parameter; the original 2-stop behavior is re-verified unchanged there
(opposite_stop defaults to None, which reproduces the original code path
byte-for-byte -- see walk_forward()'s docstring).
"""

from stop_loss_definitions import walk_forward

results = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)


def approx(a, b, tol=1e-4):
    return abs(a - b) <= tol


def base_up_fixture(tail_closes=None, tail_highs=None, tail_lows=None):
    """Same fixture as test_stop_loss_definitions.py: box bars 10-19
    (low=100, high=108), breakout_idx=20, entry=105. LFD=100 (R=5),
    rolling stop=99.0 (R=6, status='ok')."""
    closes = [100.0] * 10 + [104.0] * 10 + [105.0]
    highs = [100.0] * 10 + [108.0] * 10 + [110.0]
    lows = [100.0] * 10 + [100.0] * 10 + [100.0]
    if tail_closes:
        closes += tail_closes
    if tail_highs:
        highs += tail_highs
    if tail_lows:
        lows += tail_lows
    return closes, highs, lows


# ─────────────────────────────────────────────────────────────────────
# Test A: opposite-boundary stop wider than both LFD and rolling in a
# typical case -- opposite_stop=90.0 (far below entry=105), nothing
# touched across the full 90-bar horizon, all three marked-to-market at
# closes[110]=104.0.
#   R_lfd=5.0, R_rolling=6.0, R_opposite=15.0
#   realized_R_lfd = (104-105)/5 = -0.2
#   realized_R_rolling = (104-105)/6 = -0.16667
#   realized_R_opposite = (104-105)/15 = -0.06667
# ─────────────────────────────────────────────────────────────────────
tail_c = [104.0] * 90
tail_h = [106.0] * 90
tail_l = [102.0] * 90   # never touches lfd(100), rolling(99), or opposite(90)
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up", opposite_stop=90.0)

check("Test A1: opposite_stop wider than both -- R_opposite=15.0 > R_rolling=6.0 > R_lfd=5.0",
      approx(r.r_opposite_denom, 15.0) and r.r_opposite_denom > r.r_rolling_denom > r.r_lfd_denom,
      f"got opposite={r.r_opposite_denom}, rolling={r.r_rolling_denom}, lfd={r.r_lfd_denom}")
check("Test A2: nothing touched, horizon_reached=True, anchor_bar=110",
      r.horizon_reached and r.anchor_bar == 110 and r.opposite_hit_bar is None)
check("Test A3: all three marked-to-market correctly",
      approx(r.realized_R_lfd, -0.2) and approx(r.realized_R_rolling, -1.0 / 6.0)
      and approx(r.realized_R_opposite, -1.0 / 15.0),
      f"got lfd={r.realized_R_lfd}, rolling={r.realized_R_rolling}, opposite={r.realized_R_opposite}")

# ─────────────────────────────────────────────────────────────────────
# Test B: opposite-boundary touched BEFORE LFD -- confirms the "LFD
# always fires first" invariant (proven for rolling, because rolling's
# window always contains the LFD reference bar) does NOT extend to the
# opposite boundary, which is an independently-fitted, non-nested line
# with no such structural relationship to the LFD level.
#
# opposite_stop=103.0 (TIGHTER than LFD=100). Bar 21: low=102.5 touches
# opposite (103) but not LFD (100) or rolling (99). Bar 22: low=99.5
# touches LFD (100) but not rolling (99); opposite already resolved.
#   opposite_hit_bar=21, lfd_hit_bar=22 -- opposite fires FIRST.
#   anchor_bar=21 (opposite), realized_R_opposite=-1.0
#   realized_R_lfd = mark-to-market at closes[21]=103.0: (103-105)/5=-0.4
#   realized_R_rolling (never touched) = (103-105)/6 = -0.3333
# ─────────────────────────────────────────────────────────────────────
tail_c = [103.0, 99.0] + [101.0] * 13
tail_h = [104.0, 100.0] + [102.0] * 13
tail_l = [102.5, 99.5] + [101.0] * 13
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up", opposite_stop=103.0)

check("Test B1: opposite_hit_bar=21, lfd_hit_bar=22 (opposite fires strictly BEFORE lfd)",
      r.opposite_hit_bar == 21 and r.lfd_hit_bar == 22,
      f"got opposite={r.opposite_hit_bar}, lfd={r.lfd_hit_bar}")
check("Test B2: invariant broken -- opposite_hit_bar < lfd_hit_bar (would be impossible for rolling)",
      r.opposite_hit_bar < r.lfd_hit_bar)
check("Test B3: rolling never touched (99 never reached)", r.rolling_hit_bar is None)
check("Test B4: anchor_bar=21 (opposite), not simultaneous, not horizon_reached",
      r.anchor_bar == 21 and not r.simultaneous_hit and not r.horizon_reached)
check("Test B5: realized_R_opposite=-1.0, realized_R_lfd=-0.4, realized_R_rolling=-0.3333",
      approx(r.realized_R_opposite, -1.0) and approx(r.realized_R_lfd, -0.4)
      and approx(r.realized_R_rolling, -1.0 / 3.0),
      f"got opposite={r.realized_R_opposite}, lfd={r.realized_R_lfd}, rolling={r.realized_R_rolling}")

# ─────────────────────────────────────────────────────────────────────
# Test C: opposite boundary undefined (opposite_stop=None, the default)
# -- must reproduce the original 2-stop fields/behavior exactly.
# ─────────────────────────────────────────────────────────────────────
tail_c = [100.5] + [100.0] * 98
tail_h = [101.0] + [101.0] * 98
tail_l = [99.5] + [101.0] * 98
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")  # opposite_stop omitted
check("Test C: opposite_stop=None -- all opposite_* fields are None, no crash",
      r.opposite_stop is None and r.r_opposite_denom is None
      and r.opposite_hit_bar is None and r.realized_R_opposite is None)
check("Test C2: 2-stop behavior unchanged (matches Test 2a in the original suite): "
      "lfd_hit_bar=21, anchor_bar=21, realized_R_lfd=-1.0, realized_R_rolling=-0.75",
      r.lfd_hit_bar == 21 and r.anchor_bar == 21
      and approx(r.realized_R_lfd, -1.0) and approx(r.realized_R_rolling, -0.75))

# ─────────────────────────────────────────────────────────────────────
# Test D: degenerate opposite_stop (on the wrong side of entry, denom
# <= 0) -- must be defensively ignored (opposite_active=False), same
# treatment as an unavailable rolling stop, not a crash or a nonsensical
# negative-R record.
# ─────────────────────────────────────────────────────────────────────
tail_c = [104.0] * 20
tail_h = [106.0] * 20
tail_l = [102.0] * 20
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up", opposite_stop=110.0)  # above entry=105
check("Test D: degenerate opposite_stop (110 > entry 105 for an up-breakout) is ignored, not crashed",
      r.opposite_stop is None and r.r_opposite_denom is None
      and r.opposite_hit_bar is None and r.realized_R_opposite is None)

# ═══════════════════════════════════════════════════════════════════════
n_pass = sum(results)
n_total = len(results)
print(f"\n{'='*60}\n{n_pass}/{n_total} PASSED\n{'='*60}")
if n_pass != n_total:
    raise SystemExit(1)
