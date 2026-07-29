"""
test_fit_horizontal_level.py
------------------------------
Synthetic tests with hand-verified known answers for fit_horizontal_level().
Assert-based, per explicit instruction: if the code disagrees with the
hand-verified math below, the code is wrong -- fix the code, not the
expected values.
"""

from fit_horizontal_level import fit_horizontal_level


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ------------------------------------------------------------------
# Case A -- Anchored, valid (3 touches)
# anchor_price=100.0, tolerance_pct=0.015 (band = [98.5, 101.5])
# (5, 101.2)  diff 1.2 -> touch
# (12, 99.0)  diff 1.0 -> touch
# (20, 103.0) diff 3.0 -> NOT a touch
# Expected: touches = anchor + idx5 + idx12 = 3, valid=True,
#           level = median(100.0, 101.2, 99.0) = 100.0
# ------------------------------------------------------------------
def test_case_a_anchored_valid():
    pivots = [(5, 101.2), (12, 99.0), (20, 103.0)]
    result = fit_horizontal_level(pivots, anchor_price=100.0, tolerance_pct=0.015, min_touches=3)

    assert result.anchored is True
    assert result.touch_indices == [5, 12], f"expected touch_indices=[5, 12], got {result.touch_indices}"
    assert result.touch_count == 3, f"expected touch_count=3, got {result.touch_count}"
    assert result.valid is True, "expected valid=True (3 touches >= min_touches=3)"
    assert approx(result.level, 100.0), f"expected level=100.0, got {result.level}"


# ------------------------------------------------------------------
# Case B -- Anchored, invalid (only 2 touches)
# anchor_price=200.0, tolerance band = [197, 203]
# (4, 204.0)  diff 4.0 -> NOT a touch
# (9, 195.5)  diff 4.5 -> NOT a touch
# (15, 201.0) diff 1.0 -> touch
# Expected: touches = anchor + idx15 = 2, valid=False (min_touches=3)
# ------------------------------------------------------------------
def test_case_b_anchored_invalid():
    pivots = [(4, 204.0), (9, 195.5), (15, 201.0)]
    result = fit_horizontal_level(pivots, anchor_price=200.0, tolerance_pct=0.015, min_touches=3)

    assert result.anchored is True
    assert result.touch_indices == [15], f"expected touch_indices=[15], got {result.touch_indices}"
    assert result.touch_count == 2, f"expected touch_count=2, got {result.touch_count}"
    assert result.valid is False, "expected valid=False (2 touches < min_touches=3)"


# ------------------------------------------------------------------
# Case C -- Non-anchored, single cluster resolves to valid
# (3, 95.0)   seeds cluster
# (10, 96.0)  diff from 95.0 = 1.0 <= 1.425 -> joins, level = median(95.0,96.0) = 95.5
# (18, 94.5)  diff from 95.5 = 1.0 <= 1.4325 -> joins, level = median(95.0,96.0,94.5) = 95.0
# (25, 120.0) diff from 95.0 ~= 25 -> does NOT join, seeds a separate 1-member cluster
# Expected: leading cluster touches = 3, valid=True, level = 95.0
# ------------------------------------------------------------------
def test_case_c_non_anchored_single_cluster():
    pivots = [(3, 95.0), (10, 96.0), (18, 94.5), (25, 120.0)]
    result = fit_horizontal_level(pivots, anchor_price=None, tolerance_pct=0.015, min_touches=3)

    assert result.anchored is False
    assert result.touch_indices == [3, 10, 18], f"expected touch_indices=[3, 10, 18], got {result.touch_indices}"
    assert result.touch_count == 3, f"expected touch_count=3, got {result.touch_count}"
    assert result.valid is True, "expected valid=True (3 touches >= min_touches=3)"
    assert approx(result.level, 95.0), f"expected level=95.0, got {result.level}"


# ------------------------------------------------------------------
# Case D -- Non-anchored, tie-break exercised
# (2, 100.0)  seeds cluster A
# (6, 101.0)  diff from 100.0 = 1.0 <= 1.5 -> joins A; A = {100.0, 101.0}, spread=1.0, count=2
# (11, 110.0) too far from A -> seeds cluster B
# (15, 110.2) diff from 110.0 = 0.2 <= 1.65 -> joins B; B = {110.0, 110.2}, spread=0.2, count=2
#   A and B are now TIED at count=2. Tie-break (tightest-inlier-spread) must
#   select B (spread 0.2 < A's spread 1.0), NOT A despite A being seeded
#   first (idx2 vs idx11) -- this is the case that would fail under
#   earliest-index-pivot and is asserted explicitly as a regression guard.
# (20, 110.5) diff from B's median (110.1) = 0.4 <= ~1.65 -> joins B; count=3
# Expected: leading candidate after idx15 (prefix of first 4 pivots) is B,
#           not A. Final: touches=3, valid=True, level=median(110.0,110.2,110.5)=110.2
# ------------------------------------------------------------------
def test_case_d_non_anchored_tie_break():
    pivots = [(2, 100.0), (6, 101.0), (11, 110.0), (15, 110.2), (20, 110.5)]

    # Intermediate check after idx15 (first 4 pivots): A and B are tied at
    # count=2 -- the tie-break must pick B (tighter spread), not A (earlier).
    # This is the explicit regression guard against earliest-index-pivot.
    result_at_tie = fit_horizontal_level(pivots[:4], anchor_price=None, tolerance_pct=0.015, min_touches=3)
    assert result_at_tie.touch_indices == [11, 15], (
        f"expected leading candidate to be cluster B ([11, 15]) at the tie, "
        f"got {result_at_tie.touch_indices} -- tie-break is picking the wrong cluster "
        f"(earliest-index-pivot instead of tightest-inlier-spread)"
    )
    assert result_at_tie.touch_count == 2
    assert approx(result_at_tie.level, 110.1), f"expected level=110.1 at the tie, got {result_at_tie.level}"
    assert result_at_tie.valid is False, "2 touches < min_touches=3 at this intermediate point"

    # Also check after idx11 (first 3 pivots): only one cluster (A) has count
    # 2, B has count 1 -- no tie yet, A should legitimately still lead here.
    result_before_tie = fit_horizontal_level(pivots[:3], anchor_price=None, tolerance_pct=0.015, min_touches=3)
    assert result_before_tie.touch_indices == [2, 6], (
        f"expected A ([2, 6]) to lead before the tie (B only has 1 member), "
        f"got {result_before_tie.touch_indices}"
    )

    # Final: full pivot list. B reaches 3 touches and is valid.
    result_final = fit_horizontal_level(pivots, anchor_price=None, tolerance_pct=0.015, min_touches=3)
    assert result_final.anchored is False
    assert result_final.touch_indices == [11, 15, 20], (
        f"expected final touch_indices=[11, 15, 20], got {result_final.touch_indices}"
    )
    assert result_final.touch_count == 3, f"expected touch_count=3, got {result_final.touch_count}"
    assert result_final.valid is True, "expected valid=True (3 touches >= min_touches=3)"
    assert approx(result_final.level, 110.2), f"expected level=110.2, got {result_final.level}"


TESTS = [
    ("Case A -- anchored, valid (3 touches)", test_case_a_anchored_valid),
    ("Case B -- anchored, invalid (2 touches)", test_case_b_anchored_invalid),
    ("Case C -- non-anchored, single cluster valid", test_case_c_non_anchored_single_cluster),
    ("Case D -- non-anchored, tie-break regression guard", test_case_d_non_anchored_tie_break),
]

if __name__ == "__main__":
    results = []
    for name, fn in TESTS:
        try:
            fn()
            print(f"[PASS] {name}")
            results.append(True)
        except AssertionError as e:
            print(f"[FAIL] {name}")
            print(f"    {e}")
            results.append(False)

    print()
    print(f"TOTAL: {sum(results)}/{len(results)} passed")
    if all(results):
        print("All synthetic fit_horizontal_level tests pass. Ready to proceed to assemble_rectangle() -- not in scope for this step.")
    else:
        print("DO NOT PROCEED until all synthetic tests pass.")
