"""
test_breakout_classification.py
----------------------------------
Synthetic tests with hand-verified known answers for Type 1-4 breakout
classification.
"""

from boundaries import Boundary
from breakout_classification import classify_breakout

results = []


def flat_boundary(price=100.0):
    return Boundary(slope=0.0, intercept=price, touch_indices=[], all_candidate_indices=[])


def check(name, ok):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    results.append(ok)


# ------------------------------------------------------------------
# Common setup for up-direction tests: boundary flat at 100,
# tolerance_pct=0.015 -> touch threshold=101.5, breach threshold=98.5.
# breakout_idx=10, LFD bar=9.
#
# Tests 1-11 pin lfd_variant="full" explicitly -- they test the core
# Type 1-4 priority/mirroring/invariant logic in isolation from the
# LFD-window-length question (that's what the "full" variant IS: the
# whole horizon is live, no window-length effect to worry about), not
# because "full" is the production default -- it is NOT; "trigger" is
# (DEFAULT_LFD_VARIANT, locked 2026-07-15, see design note 6 in
# breakout_classification.py). The default alone can't run these calls
# unmodified since "trigger" requires closes/measured_move_height, which
# these simplified tests deliberately don't construct.
# ------------------------------------------------------------------
b = flat_boundary(100.0)

# Test 1: Type 1 -- no touch, no breach, no LFD hit.
lows1 = [0] * 20
lows1[9] = 90          # LFD level = 90
for i in range(11, 16):
    lows1[i] = 110      # well clear of boundary (101.5) and LFD (90)
highs1 = [x + 5 for x in lows1]
r1 = classify_breakout(b, highs1, lows1, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("Type 1: clean momentum, no touch/breach/LFD", r1.type == 1 and not r1.boundary_touched
      and not r1.boundary_breached and not r1.lfd_touched)

# Test 2: Type 2 -- touches boundary (low=100.5) but doesn't breach; LFD untouched.
lows2 = [0] * 20
lows2[9] = 90
lows2[11], lows2[12], lows2[13], lows2[14], lows2[15] = 110, 100.5, 109, 112, 110
highs2 = [x + 5 for x in lows2]
r2 = classify_breakout(b, highs2, lows2, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("Type 2: touched boundary (100.5), not breached, LFD untouched",
      r2.type == 2 and r2.boundary_touched and not r2.boundary_breached
      and not r2.lfd_touched and r2.first_touch_idx == 12)

# Test 3: Type 3 -- boundary breached (low=97 < 98.5), LFD untouched (LFD=90).
lows3 = [0] * 20
lows3[9] = 90
lows3[11], lows3[12], lows3[13], lows3[14], lows3[15] = 110, 97, 109, 112, 110
highs3 = [x + 5 for x in lows3]
r3 = classify_breakout(b, highs3, lows3, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("Type 3: boundary breached (97), LFD (90) untouched",
      r3.type == 3 and r3.boundary_breached and r3.boundary_touched
      and not r3.lfd_touched and r3.first_breach_idx == 12)

# Test 4: Type 4 -- LFD touched (low=85 <= LFD 90), even though boundary
# was also breached earlier -- Type 4 must win regardless.
lows4 = [0] * 20
lows4[9] = 90
lows4[11], lows4[12], lows4[13], lows4[14], lows4[15] = 110, 97, 85, 112, 110
highs4 = [x + 5 for x in lows4]
r4 = classify_breakout(b, highs4, lows4, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("Type 4: LFD touched (85<=90), overrides boundary-breach-only Type 3",
      r4.type == 4 and r4.lfd_touched and r4.boundary_breached
      and r4.first_lfd_touch_idx == 13 and r4.first_breach_idx == 12)

# Test 5 (EDGE CASE, explicitly requested): touch exactly AT the tolerance
# threshold must count as touched, not breached, not ignored. Value is
# constructed from the SAME floating-point computation classify_breakout()
# itself uses (100 * (1 + 0.015)), not the hand-typed literal 101.5 --
# 100 * 1.015 == 101.49999999999999 in IEEE-754 float, not exactly 101.5,
# so a hand-typed 101.5 would test a DIFFERENT (very slightly larger)
# value than the true tolerance boundary and fail this edge case for the
# wrong reason (float representation, not classification logic).
exact_tolerance_threshold = 100.0 * (1 + 0.015)
lows5 = [0] * 20
lows5[9] = 50  # LFD far away, never touched
lows5[11], lows5[12], lows5[13], lows5[14], lows5[15] = 110, exact_tolerance_threshold, 109, 112, 110
highs5 = [x + 5 for x in lows5]
r5 = classify_breakout(b, highs5, lows5, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("EDGE: touch exactly at tolerance boundary -> Type 2, not Type 1 or 3",
      r5.type == 2 and r5.boundary_touched and not r5.boundary_breached)

# Test 6 (EDGE CASE, explicitly requested): a case that looks like Type 3
# through bar 14 (boundary breached at bar 12), but LFD is touched EXACTLY
# at the LAST bar of the horizon (bar 15) -- must resolve to Type 4, not
# Type 3, proving the evaluation range is inclusive of horizon_end and
# doesn't stop checking early.
lows6 = [0] * 20
lows6[9] = 90  # LFD level = 90
lows6[11], lows6[12], lows6[13], lows6[14] = 110, 97, 109, 112
lows6[15] = 90  # exactly at LFD level, on the final bar of the horizon
highs6 = [x + 5 for x in lows6]
r6 = classify_breakout(b, highs6, lows6, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("EDGE: LFD touched exactly on the LAST bar of horizon -> Type 4, not Type 3",
      r6.type == 4 and r6.first_lfd_touch_idx == 15)

# ------------------------------------------------------------------
# Test 7: down-direction mirror -- LFD must use HIGH (not low), boundary
# touch/breach must use HIGH (not low). Boundary flat at 100 acting as
# resistance after the breakdown; tolerance 0.015 -> touch >=98.5,
# breach >101.5.
# ------------------------------------------------------------------
highs7 = [0] * 20
highs7[9] = 110  # LFD level = 110 (the HIGH of the prior day, confirming the mirror)
highs7[11], highs7[12], highs7[13], highs7[14], highs7[15] = 90, 99, 85, 80, 90
lows7 = [x - 5 for x in highs7]
r7 = classify_breakout(b, highs7, lows7, breakout_idx=10, direction="down", horizon_end=15, lfd_variant="full")
check("Down-direction: LFD level correctly taken from HIGH of prior bar (110)",
      r7.lfd_idx == 9 and r7.lfd_level == 110)
check("Down-direction: Type 2 touch (high=99>=98.5) via HIGH, not breached, LFD untouched",
      r7.type == 2 and r7.boundary_touched and not r7.boundary_breached
      and not r7.lfd_touched and r7.first_touch_idx == 12)

# Test 8: first-occurrence tracking -- two touches, first_touch_idx must
# be the EARLIER one (11), not the later one (13).
lows8 = [0] * 20
lows8[9] = 90
lows8[11], lows8[12], lows8[13], lows8[14], lows8[15] = 100.8, 110, 100.9, 112, 110
highs8 = [x + 5 for x in lows8]
r8 = classify_breakout(b, highs8, lows8, breakout_idx=10, direction="up", horizon_end=15, lfd_variant="full")
check("First-occurrence tracking: first_touch_idx is the earlier touch (11), not 13",
      r8.type == 2 and r8.first_touch_idx == 11)

# Test 9: down-direction Type 1 (clean breakdown, no retest) -- confirms
# the Type 1 default path also works correctly in the down-mirror branch,
# not just up.
highs9 = [0] * 20
highs9[9] = 110
highs9[11], highs9[12], highs9[13], highs9[14], highs9[15] = 90, 91, 89, 92, 90
lows9 = [x - 5 for x in highs9]
r9 = classify_breakout(b, highs9, lows9, breakout_idx=10, direction="down", horizon_end=15, lfd_variant="full")
check("Down-direction Type 1: clean breakdown, no touch/breach/LFD",
      r9.type == 1 and not r9.boundary_touched and not r9.lfd_touched)

# Test 10: invalid direction raises ValueError rather than silently
# misclassifying.
try:
    classify_breakout(b, highs1, lows1, breakout_idx=10, direction="sideways", horizon_end=15)
    ok10 = False
except ValueError:
    ok10 = True
check("Invalid direction raises ValueError rather than silently misclassifying", ok10)

# Test 11: breach-implies-touch invariant holds across every breach-positive
# result already produced above (r3, r4, r6) -- explicit regression guard.
ok11 = all(r.boundary_touched for r in [r3, r4, r6] if r.boundary_breached)
check("Invariant: boundary_breached implies boundary_touched, across all breach cases", ok11)

# ------------------------------------------------------------------
# Variant A (lfd_variant="fixed") edge cases. Boundary stays flat at 100
# (touch threshold 101.5, breach threshold 98.5); LFD level is set to
# 105 -- ABOVE the boundary's touch threshold -- specifically so that
# touching LFD never simultaneously touches/breaches the boundary too.
# (An earlier version of this test used LFD=90, which is BELOW the
# boundary's breach threshold of 98.5 -- so "touching LFD" also always
# breached the boundary at the same bar, contaminating the "ignored"
# cases with a real Type 3 signal and failing for the wrong reason. Not
# a bug in classify_breakout() -- confirmed by inspecting the result
# directly: first_lfd_touch_idx was correctly None in both cases, but
# boundary_breached was independently True from the same low value.
# Fixed by separating the two price levels.) All other bars stay at 110,
# clear of both thresholds. breakout_idx=10, LFD idx=9, lfd_fixed_bars=5
# -> LFD window = bars [11, 15] inclusive.
# ------------------------------------------------------------------
lowsA_hit_at_edge = [110] * 30
lowsA_hit_at_edge[9] = 105
lowsA_hit_at_edge[15] = 105  # exactly the LAST bar of the 5-bar fixed window
highsA_hit_at_edge = [x + 5 for x in lowsA_hit_at_edge]
rA1 = classify_breakout(b, highsA_hit_at_edge, lowsA_hit_at_edge, breakout_idx=10, direction="up",
                         horizon_end=25, lfd_variant="fixed", lfd_fixed_bars=5)
check("Variant A (fixed=5): LFD touch exactly on the LAST bar of the window (15) -> Type 4",
      rA1.type == 4 and rA1.first_lfd_touch_idx == 15 and rA1.lfd_end_idx == 15)

lowsA_hit_after = [110] * 30
lowsA_hit_after[9] = 105
lowsA_hit_after[16] = 105  # one bar PAST the fixed window's last bar (15)
highsA_hit_after = [x + 5 for x in lowsA_hit_after]
rA2 = classify_breakout(b, highsA_hit_after, lowsA_hit_after, breakout_idx=10, direction="up",
                         horizon_end=25, lfd_variant="fixed", lfd_fixed_bars=5)
check("Variant A (fixed=5): LFD touch one bar PAST the window (16) -> ignored, Type 1",
      rA2.type == 1 and rA2.first_lfd_touch_idx is None and rA2.lfd_end_idx == 15)

# ------------------------------------------------------------------
# Variant B (lfd_variant="trigger") edge cases. breakout_idx=10,
# breakout close=100, measured_move_height=10 -> target=110 (up).
# LFD level again set to 105 (clear of the boundary's 101.5/98.5
# thresholds) to isolate the trigger-window cutoff itself.
# ------------------------------------------------------------------
closesB = [100.0] * 30
closesB[10] = 100.0
closesB[11], closesB[12] = 105.0, 107.0
closesB[13] = 110.0  # trigger bar: close reaches the target exactly here
for i in range(14, 30):
    closesB[i] = 112.0

lowsB_hit_on_trigger = [110] * 30
lowsB_hit_on_trigger[9] = 105
lowsB_hit_on_trigger[13] = 105  # LFD touched on the SAME bar the trigger fires
highsB_hit_on_trigger = [x + 5 for x in lowsB_hit_on_trigger]
rB1 = classify_breakout(b, highsB_hit_on_trigger, lowsB_hit_on_trigger, breakout_idx=10, direction="up",
                         horizon_end=25, lfd_variant="trigger", closes=closesB, measured_move_height=10.0)
check("Variant B (trigger): LFD touch ON the trigger bar itself (13) -> still counts, Type 4",
      rB1.type == 4 and rB1.first_lfd_touch_idx == 13 and rB1.lfd_end_idx == 13)

lowsB_hit_after_trigger = [110] * 30
lowsB_hit_after_trigger[9] = 105
lowsB_hit_after_trigger[14] = 105  # LFD touched the bar AFTER the trigger bar (13)
highsB_hit_after_trigger = [x + 5 for x in lowsB_hit_after_trigger]
rB2 = classify_breakout(b, highsB_hit_after_trigger, lowsB_hit_after_trigger, breakout_idx=10, direction="up",
                         horizon_end=25, lfd_variant="trigger", closes=closesB, measured_move_height=10.0)
check("Variant B (trigger): LFD touch one bar AFTER the trigger (14) -> ignored, Type 1",
      rB2.type == 1 and rB2.first_lfd_touch_idx is None and rB2.lfd_end_idx == 13)

# Variant B fallback: target price never reached anywhere in the horizon
# -> falls back to checking LFD across the FULL horizon, same as "full".
closesB_never_hit = [100.0] * 30
for i in range(11, 26):
    closesB_never_hit[i] = 105.0  # stays well below target (110) the whole horizon
lowsB_fallback = [110] * 30
lowsB_fallback[9] = 105
lowsB_fallback[25] = 105  # LFD touched on the very last bar of the horizon
highsB_fallback = [x + 5 for x in lowsB_fallback]
rB3 = classify_breakout(b, highsB_fallback, lowsB_fallback, breakout_idx=10, direction="up",
                         horizon_end=25, lfd_variant="trigger", closes=closesB_never_hit, measured_move_height=10.0)
check("Variant B (trigger): target never reached -> falls back to full horizon, LFD touch at bar 25 counts",
      rB3.type == 4 and rB3.first_lfd_touch_idx == 25 and rB3.lfd_end_idx == 25)

# ------------------------------------------------------------------
# Locked-default regression guard: confirms DEFAULT_LFD_VARIANT is really
# "trigger" now, two ways.
# ------------------------------------------------------------------

# (a) omitting lfd_variant entirely, but supplying closes/measured_move_height,
# must behave IDENTICALLY to explicit lfd_variant="trigger" (reuses the
# rB1 "hit on trigger bar" scenario).
r_default = classify_breakout(b, highsB_hit_on_trigger, lowsB_hit_on_trigger, breakout_idx=10,
                               direction="up", horizon_end=25, closes=closesB, measured_move_height=10.0)
check("Locked default: omitting lfd_variant behaves identically to explicit lfd_variant='trigger'",
      r_default.type == rB1.type and r_default.lfd_variant == "trigger"
      and r_default.first_lfd_touch_idx == rB1.first_lfd_touch_idx)

# (b) omitting lfd_variant AND closes/measured_move_height must raise
# ValueError (proves the default is genuinely "trigger", which requires
# those params, not silently "full" which wouldn't need them).
try:
    classify_breakout(b, highs1, lows1, breakout_idx=10, direction="up", horizon_end=15)
    ok_default_requires_trigger_args = False
except ValueError:
    ok_default_requires_trigger_args = True
check("Locked default: omitting lfd_variant with no closes/height raises ValueError (confirms default='trigger', not 'full')",
      ok_default_requires_trigger_args)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
if all(results):
    print("All synthetic Type 1-4 classification tests pass. Ready for real-data re-run.")
else:
    print("DO NOT PROCEED until all synthetic tests pass.")
