"""
test_stop_loss_definitions.py
-------------------------------
Synthetic, hand-verified tests for stop_loss_definitions.py, before any
real-data run. Same discipline as test_breakout_classification.py.

IMPORTANT DEVIATIONS FROM THE ORIGINAL 10-ITEM TEST PLAN, FOUND WHILE
BUILDING THESE FIXTURES -- reported here, not silently smoothed over:

Both rolling_low_stop() and the down-breakout mirror always compute their
window over data TRUNCATED TO END AT THE LFD REFERENCE BAR ITSELF
(breakout_idx-1) -- this was the confirmed, correct choice to avoid
lookahead (see stop_loss_definitions.py docstring point 3). A direct
consequence, proven below and confirmed by hand-computation, not just
asserted: because the LFD reference bar's own high/low is ALWAYS one of
the values the rolling window's min/max is taken over, the rolling stop
is ALGEBRAICALLY GUARANTEED to be at least as wide as (in practice always
strictly wider than, given the nonzero 1% buffer) the LFD stop, for every
single candidate where both are defined. Two consequences for the
originally-planned test list:

  - Item 1 ("both stops equidistant from entry") is mathematically
    unreachable -- R_lfd_denom == R_rolling_denom would require
    lfd_level == rolling_stop, which the buffer alone rules out whenever
    support > 0. Reinterpreted as Test 1: the MINIMUM-GAP case (LFD
    reference bar IS the window's own extreme), hand-verified to show the
    gap is exactly the 1% buffer -- the tightest the two stops can ever
    get, not literal equality.
  - Item 2's "vice versa" (rolling touched, LFD not) is likewise
    unreachable: touching the wider (rolling) level on some bar's
    high/low necessarily means that same bar's high/low already crossed
    the tighter (LFD) level too, so LFD must have registered a touch on
    that bar or an earlier one. Reinterpreted as Test 2b: rather than
    attempting an impossible construction, this is tested as an explicit
    invariant assertion (lfd_hit_bar <= rolling_hit_bar whenever both are
    not None) alongside Test 2a's constructible "LFD hit, rolling never
    hit" case.

This is flagged prominently in the accompanying report to Zeeshan as a
structural finding about what the walk-forward comparison can and cannot
show -- not treated as a bug, since it follows directly from the
confirmed §1 truncation design, but genuinely non-obvious before running
the numbers by hand.
"""

import inspect

import stop_loss_definitions as sld
from stop_loss_definitions import (
    raw_lfd_level, rolling_low_stop, walk_forward,
    _consolidation_mirror_short,
)

results = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ═══════════════════════════════════════════════════════════════════════
# Shared fixture builder for the up-breakout tests (1, 2a, 2b, 3, 4, 5, 7,
# 8, 10): bars 0-9 filler (unused, any window <=10 never reaches them
# once truncated arrays are >=20 long), bars 10-19 a flat consolidation
# box (low=100, high=108), breakout_idx=20, entry=105.
# ═══════════════════════════════════════════════════════════════════════

def base_up_fixture(tail_closes=None, tail_highs=None, tail_lows=None):
    closes = [100.0] * 10 + [104.0] * 10 + [105.0]
    highs = [100.0] * 10 + [108.0] * 10 + [110.0]
    lows = [100.0] * 10 + [100.0] * 10 + [ -1 ]  # bar 20's low overwritten by caller/default below
    lows[20] = 50.0  # deliberately poisoned -- see Test 10; harmless elsewhere since never scanned
    if tail_closes:
        closes += tail_closes
    if tail_highs:
        highs += tail_highs
    if tail_lows:
        lows += tail_lows
    return closes, highs, lows


# ─────────────────────────────────────────────────────────────────────
# Test 1 (reinterpreted, see module docstring): minimum-gap case -- LFD
# reference bar (19) IS the consolidation window's own extreme, so
# support == lfd_level == 100.0 exactly, and rolling_stop is exactly the
# 1% buffer below it (99.0), not equal. Hand-verified: R_lfd=5.0,
# R_rolling=6.0, gap == 1.0 == 1% of support, confirming this is the
# tightest achievable gap, not a bug.
# ─────────────────────────────────────────────────────────────────────
closes, highs, lows = base_up_fixture()
lfd = raw_lfd_level(highs, lows, breakout_idx=20, direction="up")
roll = rolling_low_stop(closes, highs, lows, breakout_idx=20, direction="up", entry_price=closes[20])
check("Test 1a: LFD level = 100.0 (raw, lows[19])", approx(lfd, 100.0), f"got {lfd}")
check("Test 1b: rolling status ok, stop = 99.0 (100 * 0.99)",
      roll.status == "ok" and approx(roll.stop_level, 99.0), f"got {roll}")
r_lfd = closes[20] - lfd
r_roll = closes[20] - roll.stop_level
check("Test 1c: R_lfd=5.0, R_rolling=6.0, gap=1.0 (exactly the 1% buffer, minimum possible)",
      approx(r_lfd, 5.0) and approx(r_roll, 6.0) and approx(r_roll - r_lfd, 1.0),
      f"R_lfd={r_lfd}, R_rolling={r_roll}")
check("Test 1d: rolling denom always > lfd denom (structural invariant, up direction)",
      r_roll > r_lfd)

# ─────────────────────────────────────────────────────────────────────
# Test 2a: LFD touched at bar 21 (low=99.5, below lfd=100 but above
# rolling=99.0), rolling never touched across a full 90-bar horizon.
# Hand-verified: anchor_bar=21, realized_R_lfd=-1.0,
# realized_R_rolling = (closes[21]-entry)/R_rolling = (100.5-105)/6.0 = -0.75
# ─────────────────────────────────────────────────────────────────────
tail_c = [100.5] + [100.0] * 98   # bar21 close=100.5, then 98 safe filler bars -> total tail len 99
tail_h = [101.0] + [101.0] * 98
tail_l = [99.5] + [101.0] * 98    # bar21 low=99.5 (touches LFD=100, not rolling=99.0); rest stay safe
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")
check("Test 2a: lfd_hit_bar=21, rolling_hit_bar=None",
      r.lfd_hit_bar == 21 and r.rolling_hit_bar is None, f"got {r.lfd_hit_bar}, {r.rolling_hit_bar}")
check("Test 2a: anchor_bar=21, not horizon_reached, not simultaneous",
      r.anchor_bar == 21 and not r.horizon_reached and not r.simultaneous_hit)
check("Test 2a: realized_R_lfd=-1.0, realized_R_rolling=-0.75",
      approx(r.realized_R_lfd, -1.0) and approx(r.realized_R_rolling, -0.75),
      f"got {r.realized_R_lfd}, {r.realized_R_rolling}")

# Test 2b: the "vice versa" is structurally impossible -- proven as an
# invariant, not constructed. Re-verify against Test 2a's own result
# (rolling never fired, so the invariant is trivially satisfied there)
# plus Test 9's down-direction result later in this file.
check("Test 2b: invariant holds on Test 2a's fixture (rolling_hit_bar is None or >= lfd_hit_bar)",
      r.rolling_hit_bar is None or r.rolling_hit_bar >= r.lfd_hit_bar)

# ─────────────────────────────────────────────────────────────────────
# Test 3: simultaneous touch -- bar 21's low=98.5, below BOTH lfd(100)
# and rolling(99.0) in one bar (gap-through-both).
# ─────────────────────────────────────────────────────────────────────
tail_c = [95.0] + [95.0] * 98
tail_h = [99.0] + [99.0] * 98
tail_l = [98.5] + [99.0] * 98
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")
check("Test 3: both hit at bar 21, simultaneous_hit=True",
      r.lfd_hit_bar == 21 and r.rolling_hit_bar == 21 and r.simultaneous_hit,
      f"got lfd={r.lfd_hit_bar}, roll={r.rolling_hit_bar}, sim={r.simultaneous_hit}")
check("Test 3: both realize -1.0 R",
      approx(r.realized_R_lfd, -1.0) and approx(r.realized_R_rolling, -1.0))

# ─────────────────────────────────────────────────────────────────────
# Test 4: LFD-vs-lfd_variant="trigger" DECOUPLING. Constructs a bar
# (21) where breakout_classification.py's "trigger" variant would
# supersede the LFD level (close reaches the measured-move target), then
# a later bar (22) where price touches the LFD level -- which the
# "trigger" variant would IGNORE (touch after supersession) but this
# module's raw, unsuperseded LFD MUST still register.
#
# This test explicitly imports breakout_classification.classify_breakout
# to compute the "trigger"-variant answer independently and assert the
# two modules DIVERGE as expected -- proving stop_loss_definitions.py's
# LFD is not accidentally coupled to trigger-supersession. A static
# source-scan below additionally proves stop_loss_definitions.py never
# imports breakout_classification at all -- so this divergence can't be
# accidentally fixed by future code sharing a level that later becomes
# variant-gated.
# ─────────────────────────────────────────────────────────────────────
from boundaries import Boundary
from breakout_classification import classify_breakout


def flat_boundary(price):
    return Boundary(slope=0.0, intercept=price, touch_indices=[], all_candidate_indices=[])


tail_c = [111.0, 99.5, 99.5, 99.5, 99.5]   # bar21 close=111 (>=target 110, supersedes), bar22+ filler
tail_h = [112.0, 100.0, 100.0, 100.0, 100.0]
tail_l = [102.0, 99.0, 99.0, 99.0, 99.0]    # bar21 low=102 (no LFD touch yet); bar22 low=99 (touches LFD=100)
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)

# Independent "trigger"-variant answer from breakout_classification.py:
b = flat_boundary(100.0)
cbr = classify_breakout(
    b, highs, lows, breakout_idx=20, direction="up", horizon_end=25,
    lfd_variant="trigger", closes=closes, measured_move_height=5.0,
)
check("Test 4a: breakout_classification 'trigger' variant does NOT register the bar-22 LFD touch",
      cbr.lfd_touched is False and cbr.type != 4,
      f"got lfd_touched={cbr.lfd_touched}, type={cbr.type}")

# This module's raw LFD, same fixture:
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")
check("Test 4b: stop_loss_definitions.py's raw LFD DOES register the bar-22 touch (decoupled)",
      r.lfd_hit_bar == 22, f"got lfd_hit_bar={r.lfd_hit_bar}")

src_lines = inspect.getsource(sld).splitlines()
import_lines = [ln for ln in src_lines
                if ln.strip().startswith("import ") or ln.strip().startswith("from ")]
has_bad_import = any("breakout_classification" in ln for ln in import_lines)
check("Test 4c: static source scan -- stop_loss_definitions.py has no import statement "
      "referencing breakout_classification (docstring mentions of the module name are fine)",
      not has_bad_import, f"import lines found: {import_lines}")

# ─────────────────────────────────────────────────────────────────────
# Test 5: rolling stop wider than 6% risk -> skipped under kiran's own
# rule. Box support=90 (bars 10-19 low=90 flat), stop=89.1, entry=100 ->
# risk=10.9% > 6%.
# ─────────────────────────────────────────────────────────────────────
closes5 = [100.0] * 10 + [93.0] * 10 + [100.0]
highs5 = [100.0] * 10 + [95.0] * 10 + [102.0]
lows5 = [100.0] * 10 + [90.0] * 10 + [88.0]
roll5 = rolling_low_stop(closes5, highs5, lows5, breakout_idx=20, direction="up", entry_price=closes5[20])
check("Test 5: status='skipped_risk_gt_6pct', stop=89.1, risk~10.9%",
      roll5.status == "skipped_risk_gt_6pct" and approx(roll5.stop_level, 89.1)
      and roll5.risk_pct > 6.0, f"got {roll5}")

r5 = walk_forward(closes5, highs5, lows5, breakout_idx=20, direction="up")
check("Test 5b: walk_forward carries the skip through -- realized_R_rolling is None, row not dropped",
      r5.rolling_status == "skipped_risk_gt_6pct" and r5.realized_R_rolling is None
      and r5.realized_R_lfd is not None)

# ─────────────────────────────────────────────────────────────────────
# Test 6: no valid consolidation window at all (every window's width
# exceeds MAX_RANGE_PCT=12%) -> "no_valid_consolidation".
# ─────────────────────────────────────────────────────────────────────
closes6 = [100.0] * 20
highs6 = [200.0] * 20
lows6 = [10.0] * 20
roll6 = rolling_low_stop(closes6, highs6, lows6, breakout_idx=20, direction="up", entry_price=105.0)
check("Test 6: status='no_valid_consolidation', stop/risk/window all None",
      roll6.status == "no_valid_consolidation" and roll6.stop_level is None
      and roll6.risk_pct is None and roll6.window is None, f"got {roll6}")

# ─────────────────────────────────────────────────────────────────────
# Test 7: neither stop touched across the full 90-bar horizon (data
# available beyond bar 110) -> horizon_reached=True, anchor_bar=110
# (breakout_idx+90), both sides marked-to-market at closes[110]=104.0.
# realized_R_lfd = (104-105)/5.0 = -0.2
# realized_R_rolling = (104-105)/6.0 = -0.16666...
# ─────────────────────────────────────────────────────────────────────
tail_c = [104.0] * 90
tail_h = [106.0] * 90
tail_l = [102.0] * 90   # never <=100 (lfd) or <=99 (rolling)
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
check("Test 7 setup: array reaches bar 110", len(closes) - 1 == 110)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")
check("Test 7: horizon_reached=True, anchor_bar=110 (breakout_idx+90, full horizon)",
      r.horizon_reached and r.anchor_bar == 110, f"got anchor_bar={r.anchor_bar}, horizon_reached={r.horizon_reached}")
check("Test 7: realized_R_lfd=-0.2, realized_R_rolling=-0.16667",
      approx(r.realized_R_lfd, -0.2) and approx(r.realized_R_rolling, -1.0 / 6.0, tol=1e-4),
      f"got {r.realized_R_lfd}, {r.realized_R_rolling}")

# ─────────────────────────────────────────────────────────────────────
# Test 8: symbol's history ends before bar 90 -- only 10 bars of
# post-breakout data (last_bar=30). Confirms horizon_end truncates to
# last_bar=30, not a synthetic/out-of-range 110, and doesn't crash.
# ─────────────────────────────────────────────────────────────────────
tail_c = [104.0] * 10
tail_h = [106.0] * 10
tail_l = [102.0] * 10
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
check("Test 8 setup: array ends at bar 30", len(closes) - 1 == 30)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")
check("Test 8: horizon truncated to last available bar (30), not the nominal 110",
      r.anchor_bar == 30 and r.horizon_reached, f"got anchor_bar={r.anchor_bar}")

# ─────────────────────────────────────────────────────────────────────
# Test 9: down-breakout mirror, dedicated fixture (not inferred from the
# long-side tests). Box: full-window floor (support)=195 flat throughout
# 10-19; highs 10-14=203 (older spike), 15-19=200 (recent, tighter) --
# _consolidation_mirror_short must pick window=5 (support=195,
# resistance=200), correctly avoiding the older 203 spike, mirroring the
# long side's "avoid the stale crash wick" logic. Entry=193 (a breakdown
# close below support). lfd_level=highs[19]=200. rolling stop =
# round(200*1.01, 2) = 202.0.
# R_lfd = 200-193 = 7.0, R_rolling = 202-193 = 9.0 (again rolling wider,
# confirming the invariant holds in the down direction too).
# ─────────────────────────────────────────────────────────────────────
closes9 = [195.0] * 10 + [198.0] * 5 + [197.0] * 5 + [193.0]
highs9 = [195.0] * 10 + [203.0] * 5 + [200.0] * 5 + [194.0]
lows9 = [195.0] * 10 + [195.0] * 5 + [195.0] * 5 + [190.0]

mirror = _consolidation_mirror_short(closes9[:20], highs9[:20], lows9[:20])
check("Test 9a: mirror picks window=5, support=195, resistance=200 (avoids the 203 older spike)",
      mirror is not None and mirror["window"] == 5
      and approx(mirror["support"], 195.0) and approx(mirror["resistance"], 200.0),
      f"got {mirror}")

lfd9 = raw_lfd_level(highs9, lows9, breakout_idx=20, direction="down")
roll9 = rolling_low_stop(closes9, highs9, lows9, breakout_idx=20, direction="down", entry_price=closes9[20])
check("Test 9b: lfd_level=200.0 (highs[19]), rolling stop=202.0, status='ok'",
      approx(lfd9, 200.0) and roll9.status == "ok" and approx(roll9.stop_level, 202.0),
      f"got lfd={lfd9}, roll={roll9}")
r_lfd9 = lfd9 - closes9[20]
r_roll9 = roll9.stop_level - closes9[20]
check("Test 9c: R_lfd=7.0, R_rolling=9.0 (rolling wider, invariant holds for down-breakouts too)",
      approx(r_lfd9, 7.0) and approx(r_roll9, 9.0) and r_roll9 > r_lfd9,
      f"R_lfd={r_lfd9}, R_rolling={r_roll9}")

# Full walk-forward: bar21 high=201 (touches LFD=200, not rolling=202),
# closes[21]=199; bar22 high=203 (touches rolling=202, after LFD).
closes9b = closes9 + [199.0, 198.0]
highs9b = highs9 + [201.0, 203.0]
lows9b = lows9 + [197.0, 196.0]
r9 = walk_forward(closes9b, highs9b, lows9b, breakout_idx=20, direction="down")
check("Test 9d: lfd_hit_bar=21 (fires first), rolling_hit_bar=22 (fires later, confirms invariant)",
      r9.lfd_hit_bar == 21 and r9.rolling_hit_bar == 22, f"got {r9.lfd_hit_bar}, {r9.rolling_hit_bar}")
check("Test 9e: anchor_bar=21, realized_R_lfd=-1.0, realized_R_rolling=(193-199)/9=-0.6667",
      r9.anchor_bar == 21 and approx(r9.realized_R_lfd, -1.0)
      and approx(r9.realized_R_rolling, -6.0 / 9.0, tol=1e-4),
      f"got anchor={r9.anchor_bar}, R_lfd={r9.realized_R_lfd}, R_rolling={r9.realized_R_rolling}")

# ─────────────────────────────────────────────────────────────────────
# Test 10: breakout bar itself (20) carries a deliberately poisoned low
# (50.0, from base_up_fixture's default) -- far below both stops. If the
# walk-forward loop incorrectly started scanning AT breakout_idx instead
# of breakout_idx+1, this would register an immediate simultaneous hit
# at bar 20. Bars 21-30 are all safe (never touch either stop) --
# confirms bar 20 is correctly excluded.
# ─────────────────────────────────────────────────────────────────────
tail_c = [104.0] * 10
tail_h = [106.0] * 10
tail_l = [102.0] * 10
closes, highs, lows = base_up_fixture(tail_c, tail_h, tail_l)
check("Test 10 setup: bar 20's low is poisoned at 50.0 (would trigger both stops if scanned)",
      lows[20] == 50.0)
r = walk_forward(closes, highs, lows, breakout_idx=20, direction="up")
check("Test 10: bar 20 excluded from the scan -- neither stop hit, horizon reached at bar 30",
      r.lfd_hit_bar is None and r.rolling_hit_bar is None
      and r.anchor_bar == 30 and r.horizon_reached,
      f"got lfd_hit={r.lfd_hit_bar}, roll_hit={r.rolling_hit_bar}, anchor={r.anchor_bar}")

# ═══════════════════════════════════════════════════════════════════════
n_pass = sum(results)
n_total = len(results)
print(f"\n{'='*60}\n{n_pass}/{n_total} PASSED\n{'='*60}")
if n_pass != n_total:
    raise SystemExit(1)
