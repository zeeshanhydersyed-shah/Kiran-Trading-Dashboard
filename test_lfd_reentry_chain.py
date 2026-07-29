"""
test_lfd_reentry_chain.py
----------------------------
Synthetic, hand-verified tests for lfd_reentry_chain.py, before any
real-data run.

Fixtures are built as a flat "safe baseline" (close=100, high=101,
low=100 everywhere -- never touches any LFD level below 100, never
breaches a boundary flat at 100 with 1.5% tolerance) with specific bar
indices overridden explicitly by assignment, rather than concatenated
segments -- avoids the hand-counting errors concatenation produced in
an earlier draft of this file (caught by the tests themselves failing
with informative "got X" mismatches, not by eyeballing).
"""

from boundaries import Boundary
from lfd_reentry_chain import walk_reentry_chain

results = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    results.append(ok)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def flat_boundary(price):
    return Boundary(slope=0.0, intercept=price, touch_indices=[], all_candidate_indices=[])


def safe_arrays(n):
    """n bars, indices 0..n-1, all safe: close=100, high=101, low=100."""
    return [100.0] * n, [101.0] * n, [100.0] * n


# ─────────────────────────────────────────────────────────────────────
# Test (a): no re-entry ever occurs. Boundary flat @ 100. breakout_idx=20,
# entry=closes[20]=101, lfd_level=lows[19]=95. Stopped out at bar 22
# (lows[22]=94). Everything else stays at the safe baseline -- boundary
# never re-crossed (close never exceeds 101.5) within the search horizon.
# ─────────────────────────────────────────────────────────────────────
closes, highs, lows = safe_arrays(41)  # indices 0-40
lows[19] = 95.0
closes[20] = 101.0
lows[22] = 94.0
b = flat_boundary(100.0)
r = walk_reentry_chain(closes, highs, lows, breakout_idx=20, direction="up", boundary=b)
check("Test a1: exactly 1 leg, no re-entry", len(r.legs) == 1 and r.n_reentries == 0,
      f"got {len(r.legs)} legs, n_reentries={r.n_reentries}")
check("Test a2: leg 1 stopped out at bar 22, realized_R=-1.0",
      r.legs[0].exit_bar == 22 and r.legs[0].exit_type == "lfd" and approx(r.legs[0].realized_R, -1.0),
      f"got {r.legs[0]}")
check("Test a3: chain_realized_R=-1.0, cap_bound=False",
      approx(r.chain_realized_R, -1.0) and not r.cap_bound)

# ─────────────────────────────────────────────────────────────────────
# Test (b): one clean re-entry, rides to horizon-close.
# Same leg 1 (stop at bar 22). Bar 29: low=99 (leg 2's future LFD
# reference bar -- value itself is harmless here, just needs to be set
# for leg 2's raw_lfd_level() to pick up). Bar 30: close=103 (>101.5) --
# re-entry. New entry=103, new lfd=lows[29]=99 (R_denom=4.0). Rest of
# the array (31-40) stays at the safe baseline (low=100 > 99, never
# touches leg 2's LFD) -- leg 2 rides to horizon-close at bar 40 (array
# end). Bar 40 close overridden to 105 for a clean, nonzero mark-to-market.
#   leg2 realized_R = (105-103)/4 = 0.5
#   chain_realized_R = -1.0 + 0.5 = -0.5
# ─────────────────────────────────────────────────────────────────────
closes, highs, lows = safe_arrays(41)  # indices 0-40
lows[19] = 95.0
closes[20] = 101.0
lows[22] = 94.0
lows[29] = 99.0
closes[30] = 103.0
closes[40] = 105.0
check("Test b setup: array ends at bar 40", len(closes) - 1 == 40)
check("Test b setup: lows[29]=99.0 (leg 2's LFD reference)", approx(lows[29], 99.0))
b = flat_boundary(100.0)
r = walk_reentry_chain(closes, highs, lows, breakout_idx=20, direction="up", boundary=b)
check("Test b1: 2 legs, 1 re-entry", len(r.legs) == 2 and r.n_reentries == 1,
      f"got {len(r.legs)} legs, n_reentries={r.n_reentries}")
check("Test b2: leg 2 entry_bar=30, entry_price=103.0",
      r.legs[1].entry_bar == 30 and approx(r.legs[1].entry_price, 103.0),
      f"got entry_bar={r.legs[1].entry_bar}, entry_price={r.legs[1].entry_price}")
check("Test b3: leg 2 lfd_level=99.0, r_lfd_denom=4.0",
      approx(r.legs[1].lfd_level, 99.0) and approx(r.legs[1].r_lfd_denom, 4.0),
      f"got {r.legs[1]}")
check("Test b4: leg 2 exit_type='horizon', exit_bar=40, realized_R=0.5",
      r.legs[1].exit_type == "horizon" and r.legs[1].exit_bar == 40 and approx(r.legs[1].realized_R, 0.5),
      f"got {r.legs[1].exit_type}, {r.legs[1].exit_bar}, {r.legs[1].realized_R}")
check("Test b5: chain_realized_R=-0.5", approx(r.chain_realized_R, -0.5), f"got {r.chain_realized_R}")

# ─────────────────────────────────────────────────────────────────────
# Test (c): re-entry that itself gets stopped out, triggering a SECOND
# re-entry. Continues from leg 2 (entry bar 30, lfd=99, r_denom=4.0):
# bar 33: low=98 (<=99) -- leg 2 stopped out. Bar 35: low=97 (leg 3's
# future LFD reference). Bar 36: close=102 (>101.5) -- re-entry 2. New
# entry=102, new lfd=lows[35]=97 (R_denom=5.0). Rest of array (37-45)
# safe baseline (low=100 > 97) -- leg 3 rides to horizon-close at bar 45
# (array end). Bar 45 close overridden to 103.
#   leg2 realized_R = -1.0 (stopped)
#   leg3 realized_R = (103-102)/5 = 0.2
#   chain_realized_R = -1.0 + -1.0 + 0.2 = -1.8
# ─────────────────────────────────────────────────────────────────────
closes, highs, lows = safe_arrays(46)  # indices 0-45
lows[19] = 95.0
closes[20] = 101.0
lows[22] = 94.0
lows[29] = 99.0
closes[30] = 103.0
lows[33] = 98.0
lows[35] = 97.0
closes[36] = 102.0
closes[45] = 103.0
check("Test c setup: array ends at bar 45", len(closes) - 1 == 45)
check("Test c setup: lows[35]=97.0 (leg 3's LFD reference)", approx(lows[35], 97.0))
b = flat_boundary(100.0)
r = walk_reentry_chain(closes, highs, lows, breakout_idx=20, direction="up", boundary=b)
check("Test c1: 3 legs, 2 re-entries", len(r.legs) == 3 and r.n_reentries == 2,
      f"got {len(r.legs)} legs, n_reentries={r.n_reentries}")
check("Test c2: leg 2 stopped at bar 33", r.legs[1].exit_bar == 33 and r.legs[1].exit_type == "lfd",
      f"got exit_bar={r.legs[1].exit_bar}, exit_type={r.legs[1].exit_type}")
check("Test c3: leg 3 entry_bar=36, entry_price=102.0, lfd_level=97.0, r_lfd_denom=5.0",
      r.legs[2].entry_bar == 36 and approx(r.legs[2].entry_price, 102.0)
      and approx(r.legs[2].lfd_level, 97.0) and approx(r.legs[2].r_lfd_denom, 5.0),
      f"got {r.legs[2]}")
check("Test c4: leg 3 rides to horizon-close at bar 45, realized_R=0.2",
      r.legs[2].exit_type == "horizon" and r.legs[2].exit_bar == 45 and approx(r.legs[2].realized_R, 0.2),
      f"got {r.legs[2].exit_type}, {r.legs[2].exit_bar}, {r.legs[2].realized_R}")
check("Test c5: chain_realized_R=-1.8, cap_bound=False (default max_reentries=3, only 2 used)",
      approx(r.chain_realized_R, -1.8) and not r.cap_bound, f"got {r.chain_realized_R}, cap_bound={r.cap_bound}")

# ─────────────────────────────────────────────────────────────────────
# Test (c-cap): SAME fixture as test (c), but max_reentries=1 -- forces
# the cap to bind after leg 2's stop-out (which would otherwise have
# found the bar-36 re-entry). Confirms the chain stops at 2 legs AND
# cap_bound=True is correctly reported (the search still runs for
# reporting, it just isn't acted on).
# ─────────────────────────────────────────────────────────────────────
r_cap = walk_reentry_chain(closes, highs, lows, breakout_idx=20, direction="up", boundary=b, max_reentries=1)
check("Test c-cap 1: only 2 legs (cap stops the chain before leg 3)",
      len(r_cap.legs) == 2 and r_cap.n_reentries == 1,
      f"got {len(r_cap.legs)} legs, n_reentries={r_cap.n_reentries}")
check("Test c-cap 2: cap_bound=True (a re-entry DID exist at bar 36, just not taken)",
      r_cap.cap_bound)
check("Test c-cap 3: chain_realized_R=-2.0 (leg1 + leg2, both stopped, leg3 never happens)",
      approx(r_cap.chain_realized_R, -2.0), f"got {r_cap.chain_realized_R}")

# ─────────────────────────────────────────────────────────────────────
# Test (d): re-entry trigger price uses the LATER bar's boundary value,
# NOT the original breakout price. Boundary SLOPED (slope=0.5,
# intercept=90): price_at(20)=100 (original breakout level),
# price_at(25)=102.5 (threshold 104.0375), price_at(40)=110.0
# (threshold 111.65).
#
# Bar 25 close=103: exceeds the ORIGINAL level's threshold (100*1.015=
# 101.5) but NOT the boundary's own bar-25 threshold (104.0375) -- a
# buggy implementation comparing against the original breakout price
# would incorrectly fire here. Bar 40 close=112: clears the CORRECT
# bar-40 threshold (111.65) -- this is the true re-entry bar.
# ─────────────────────────────────────────────────────────────────────
closes, highs, lows = safe_arrays(46)  # indices 0-45
lows[19] = 95.0
closes[20] = 101.0
lows[22] = 94.0
closes[25] = 103.0   # trap -- must NOT trigger re-entry
closes[40] = 112.0   # true re-entry
check("Test d setup: array ends at bar 45", len(closes) - 1 == 45)
check("Test d setup: bar 25 close=103 (trap value)", approx(closes[25], 103.0))
check("Test d setup: bar 40 close=112 (true re-entry value)", approx(closes[40], 112.0))
sloped_b = Boundary(slope=0.5, intercept=90.0, touch_indices=[], all_candidate_indices=[])
check("Test d setup: sloped boundary price_at(20)=100, price_at(25)=102.5, price_at(40)=110.0",
      approx(sloped_b.price_at(20), 100.0) and approx(sloped_b.price_at(25), 102.5)
      and approx(sloped_b.price_at(40), 110.0))
r = walk_reentry_chain(closes, highs, lows, breakout_idx=20, direction="up", boundary=sloped_b)
check("Test d1: re-entry bar is 40, NOT 25 (would fail if original breakout price were reused)",
      len(r.legs) == 2 and r.legs[1].entry_bar == 40,
      f"got {len(r.legs)} legs" + (f", entry_bar={r.legs[1].entry_bar}" if len(r.legs) > 1 else ""))
check("Test d2: leg 2 entry_price=112.0 (the later bar's close)",
      approx(r.legs[1].entry_price, 112.0), f"got {r.legs[1].entry_price}")

n_pass = sum(results)
n_total = len(results)
print(f"\n{'='*60}\n{n_pass}/{n_total} PASSED\n{'='*60}")
if n_pass != n_total:
    raise SystemExit(1)
