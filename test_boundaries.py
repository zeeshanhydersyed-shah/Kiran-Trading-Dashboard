"""
test_boundaries.py
-------------------
Synthetic tests with hand-verified known answers for boundary fitting.
"""

from pivots import Pivot
from boundaries import fit_boundary, check_violation


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


results = []

# ------------------------------------------------------------------
# Test 1: perfect descending line through 3 pivot highs, exact fit
# points: (0,100), (10,95), (20,90) -> slope = -0.5, intercept=100
# ------------------------------------------------------------------
pivots1 = [Pivot(0, "high", 100, 3), Pivot(10, "high", 95, 13), Pivot(20, "high", 90, 23)]
b1 = fit_boundary(pivots1)
ok1 = b1 is not None and approx(b1.slope, -0.5) and approx(b1.intercept, 100) and len(b1.touch_indices) == 3
print(f"[{'PASS' if ok1 else 'FAIL'}] perfect 3-point descending line, all touch")
if not ok1 and b1:
    print(f"    slope={b1.slope}, intercept={b1.intercept}, touches={b1.touch_indices}")
results.append(ok1)

# ------------------------------------------------------------------
# Test 2: pivot 3 sits INSIDE (below) a descending line fit by pivots
# 1,2,4 -- should NOT be forced to "touch", should NOT break the fit,
# and the final line should still pass through 1,2,4.
# ------------------------------------------------------------------
pivots2 = [
    Pivot(0, "high", 100, 3),
    Pivot(10, "high", 95, 13),
    Pivot(20, "high", 88, 23),   # interior, doesn't touch
    Pivot(30, "high", 85, 33),
]
b2 = fit_boundary(pivots2, tolerance_pct=0.015)
ok2 = (
    b2 is not None
    and approx(b2.slope, -0.5, tol=0.02)
    and 20 not in b2.touch_indices
    and 0 in b2.touch_indices
    and 10 in b2.touch_indices
    and 30 in b2.touch_indices
)
print(f"[{'PASS' if ok2 else 'FAIL'}] interior non-touching pivot excluded, line still fit through others")
if not ok2 and b2:
    print(f"    slope={b2.slope}, intercept={b2.intercept}, touches={b2.touch_indices}")
results.append(ok2)

# ------------------------------------------------------------------
# Test 3: fewer than 2 pivots -> None
# ------------------------------------------------------------------
b3 = fit_boundary([Pivot(0, "high", 100, 3)])
ok3 = b3 is None
print(f"[{'PASS' if ok3 else 'FAIL'}] single pivot returns None (can't fit a line)")
results.append(ok3)

# ------------------------------------------------------------------
# Test 4: ascending lower boundary (rising lows) fits with positive slope
# ------------------------------------------------------------------
pivots4 = [Pivot(0, "low", 50, 3), Pivot(10, "low", 55, 13), Pivot(20, "low", 60, 23)]
b4 = fit_boundary(pivots4)
ok4 = b4 is not None and approx(b4.slope, 0.5) and len(b4.touch_indices) == 3
print(f"[{'PASS' if ok4 else 'FAIL'}] ascending lower boundary, positive slope")
results.append(ok4)

# ------------------------------------------------------------------
# Test 5: flat (near-zero slope) boundary, ascending-triangle-style top
# ------------------------------------------------------------------
pivots5 = [
    Pivot(0, "high", 100, 3),
    Pivot(10, "high", 100.5, 13),
    Pivot(20, "high", 99.8, 23),
    Pivot(30, "high", 100.2, 33),
]
b5 = fit_boundary(pivots5, tolerance_pct=0.015)
ok5 = b5 is not None and abs(b5.slope) < 0.05  # near-flat
print(f"[{'PASS' if ok5 else 'FAIL'}] near-flat resistance line detected as ~flat")
if not ok5 and b5:
    print(f"    slope={b5.slope}")
results.append(ok5)

# ------------------------------------------------------------------
# Test 6: violation check -- closes staying below an upper boundary = no
# violation; one close punching decisively above it = violation flagged
# ------------------------------------------------------------------
pivots6 = [Pivot(0, "high", 100, 3), Pivot(10, "high", 95, 13), Pivot(20, "high", 90, 23)]
b6 = fit_boundary(pivots6)
closes6 = [95, 94, 90, 89, 87, 200, 84]  # index 5 = 200, a wild violation
violations6 = check_violation(b6, closes6, start_index=0, end_index=6, direction="upper")
ok6 = violations6 == [5]
print(f"[{'PASS' if ok6 else 'FAIL'}] violation correctly detected at the punch-through bar only")
if not ok6:
    print(f"    got violations: {violations6}")
results.append(ok6)

# ------------------------------------------------------------------
# Test 7: no violation when all closes respect the (upper) boundary
# ------------------------------------------------------------------
closes7 = [95, 94, 90, 89, 87, 86, 84]
violations7 = check_violation(b6, closes7, start_index=0, end_index=6, direction="upper")
ok7 = violations7 == []
print(f"[{'PASS' if ok7 else 'FAIL'}] no false-positive violations on well-behaved closes")
results.append(ok7)

# ------------------------------------------------------------------
# Test 8: REGRESSION for the silent-fallthrough bug found via real-data
# adversarial audit. Points that are genuinely scattered (no 2 of them
# are mutually consistent with any single line within tolerance) must
# return None, not a Boundary that falsely claims all 4 as touches.
# Exact repro case as reported: (0, 89.48), (3, 57.24), (22, 59.41), (36, 55.80)
# ------------------------------------------------------------------
pivots8 = [
    Pivot(0, "high", 89.48, 3),
    Pivot(3, "high", 57.24, 6),
    Pivot(22, "high", 59.41, 25),
    Pivot(36, "high", 55.80, 39),
]
b8 = fit_boundary(pivots8, tolerance_pct=0.015)
ok8 = b8 is None
print(f"[{'PASS' if ok8 else 'FAIL'}] scattered points with no genuine 2-point agreement return None")
if not ok8 and b8:
    print(f"    BUG STILL PRESENT: slope={b8.slope}, intercept={b8.intercept}, touches={b8.touch_indices}")
results.append(ok8)

print()
print(f"TOTAL: {sum(results)}/{len(results)} passed")
if all(results):
    print("All synthetic boundary tests pass. Ready for visual overlay against real PSX triangle candidates.")
else:
    print("DO NOT PROCEED until all synthetic tests pass.")
