"""
test_assemble_rectangle.py
----------------------------
Synthetic tests with hand-verified known answers for assemble_rectangle().
Assert-based, per explicit instruction: if the code disagrees with the
hand-verified math, the code is wrong -- fix the code, not the expected
values.
"""

from assemble_rectangle import assemble_rectangle


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ------------------------------------------------------------------
# Case 1 -- VALID, breakout at day 35
# Anchor: support, price=100.0, day 0
# Resistance pivots: (5, 110.0), (15, 110.5), (25, 109.8)
#   -> at day 25: 3 touches, level=110.0, valid
# Support touches: anchor + (10, 100.8) + (20, 99.5)
#   -> at day 20: 3 touches, level=100.0, valid
# At day 25 (both valid): height = (110-100)/100 = 10% >= 6.1% -> passes
# Day 35 close = 112.0, breaches resistance (upper=110+1.65=111.65)
# Duration = 35 days >= 21 -> VALID
# ------------------------------------------------------------------
def test_case_1_valid_breakout():
    anchor_index = 0
    anchor_price = 100.0
    anchor_side = "support"
    support_pivots = [(10, 100.8), (20, 99.5)]
    resistance_pivots = [(5, 110.0), (15, 110.5), (25, 109.8)]

    # Build price_bars: closes that don't breach until day 35
    price_bars = []
    for day in range(61):
        close = 105.0  # Default: middle ground, no breach
        if day == 35:
            close = 112.0  # Breach resistance
        price_bars.append({"day": day, "close": close})

    result = assemble_rectangle(
        anchor_index,
        anchor_price,
        anchor_side,
        support_pivots,
        resistance_pivots,
        price_bars,
        tolerance_pct=0.015,
        min_touches=3,
        min_duration_days=21,
        max_duration_days=60,
        margin_multiplier=2.0,
    )

    assert result.outcome == "VALID", f"expected outcome=VALID, got {result.outcome}"
    assert result.duration_days == 35, f"expected duration_days=35, got {result.duration_days}"
    assert result.breakout_direction == "up", f"expected breakout_direction='up', got {result.breakout_direction}"
    assert approx(result.support_level, 100.0), f"expected support_level=100.0, got {result.support_level}"
    assert approx(result.resistance_level, 110.0), f"expected resistance_level=110.0, got {result.resistance_level}"


# ------------------------------------------------------------------
# Case 2 -- EXPIRED_NO_BREAKOUT, cap at day 60
# Anchor: support, price=50.0, day 0
# Resistance pivots: (8, 55.0), (18, 55.3), (30, 54.8)
#   -> at day 30: 3 touches, level=55.0, valid
# Support touches: anchor + (15, 50.6) + (40, 49.6)
#   -> at day 40: 3 touches, level=50.0, valid
# At day 40 (both valid): height = (55-50)/50 = 10% >= 6.1% -> passes
# All closes stay within [49.25, 50.75] support / [54.175, 55.825] resistance
# Day 60: no breach yet -> EXPIRED_NO_BREAKOUT
# ------------------------------------------------------------------
def test_case_2_expired_no_breakout():
    anchor_index = 0
    anchor_price = 50.0
    anchor_side = "support"
    support_pivots = [(15, 50.6), (40, 49.6)]
    resistance_pivots = [(8, 55.0), (18, 55.3), (30, 54.8)]

    # Build price_bars: closes that stay within bands, never breach
    price_bars = []
    for day in range(61):
        close = 52.5  # Middle ground between 50 and 55, no breach
        price_bars.append({"day": day, "close": close})

    result = assemble_rectangle(
        anchor_index,
        anchor_price,
        anchor_side,
        support_pivots,
        resistance_pivots,
        price_bars,
        tolerance_pct=0.015,
        min_touches=3,
        min_duration_days=21,
        max_duration_days=60,
        margin_multiplier=2.0,
    )

    assert result.outcome == "EXPIRED_NO_BREAKOUT", f"expected outcome=EXPIRED_NO_BREAKOUT, got {result.outcome}"
    assert result.duration_days == 60, f"expected duration_days=60, got {result.duration_days}"
    assert result.breakout_direction is None, f"expected breakout_direction=None, got {result.breakout_direction}"
    assert approx(result.support_level, 50.0), f"expected support_level=50.0, got {result.support_level}"
    assert approx(result.resistance_level, 55.0), f"expected resistance_level=55.0, got {result.resistance_level}"


# ------------------------------------------------------------------
# Case 3 -- REJECTED_TOO_SHORT, breakout at day 18
# Anchor: support, price=200.0, day 0
# Resistance pivots: (3, 215.0), (8, 215.5), (14, 214.7)
#   -> at day 14: 3 touches, level=215.0, valid
# Support touches: anchor + (5, 200.9) + (10, 199.4)
#   -> at day 10: 3 touches, level=200.0, valid
# At day 14 (both valid): height = (215-200)/200 = 7.5% >= 6.1% -> passes
# Day 18 close = 219.0, breaches resistance (upper=215+3.225=218.225)
# Duration = 18 < 21 -> REJECTED_TOO_SHORT
# ------------------------------------------------------------------
def test_case_3_rejected_too_short():
    anchor_index = 0
    anchor_price = 200.0
    anchor_side = "support"
    support_pivots = [(5, 200.9), (10, 199.4)]
    resistance_pivots = [(3, 215.0), (8, 215.5), (14, 214.7)]

    # Build price_bars: breach at day 18
    price_bars = []
    for day in range(61):
        close = 207.5  # Middle ground
        if day == 18:
            close = 219.0  # Breach resistance
        price_bars.append({"day": day, "close": close})

    result = assemble_rectangle(
        anchor_index,
        anchor_price,
        anchor_side,
        support_pivots,
        resistance_pivots,
        price_bars,
        tolerance_pct=0.015,
        min_touches=3,
        min_duration_days=21,
        max_duration_days=60,
        margin_multiplier=2.0,
    )

    assert result.outcome == "REJECTED_TOO_SHORT", f"expected outcome=REJECTED_TOO_SHORT, got {result.outcome}"
    assert result.duration_days == 18, f"expected duration_days=18, got {result.duration_days}"


# ------------------------------------------------------------------
# Case 4 -- REJECTED_HEIGHT_FLOOR
# Anchor: support, price=300.0, day 0
# Resistance pivots: (4, 308.0), (9, 308.3), (16, 307.7)
#   -> at day 16: 3 touches, level=308.0, valid
# Support touches: anchor + (6, 300.9) + (12, 299.3)
#   -> at day 12: 3 touches, level=300.0, valid
# At day 16 (both valid): height = (308-300)/300 = 2.67% < 6.1% -> REJECTED
# ------------------------------------------------------------------
def test_case_4_rejected_height_floor():
    anchor_index = 0
    anchor_price = 300.0
    anchor_side = "support"
    support_pivots = [(6, 300.9), (12, 299.3)]
    resistance_pivots = [(4, 308.0), (9, 308.3), (16, 307.7)]

    # Build price_bars (content doesn't matter, rejected before checking breaches)
    price_bars = []
    for day in range(61):
        close = 304.0
        price_bars.append({"day": day, "close": close})

    result = assemble_rectangle(
        anchor_index,
        anchor_price,
        anchor_side,
        support_pivots,
        resistance_pivots,
        price_bars,
        tolerance_pct=0.015,
        min_touches=3,
        min_duration_days=21,
        max_duration_days=60,
        margin_multiplier=2.0,
    )

    assert result.outcome == "REJECTED_HEIGHT_FLOOR", f"expected outcome=REJECTED_HEIGHT_FLOOR, got {result.outcome}"
    assert result.duration_days == 16, f"expected duration_days=16 (day both boundaries first valid), got {result.duration_days}"


TESTS = [
    ("Case 1 -- VALID, breakout at day 35", test_case_1_valid_breakout),
    ("Case 2 -- EXPIRED_NO_BREAKOUT, cap at day 60", test_case_2_expired_no_breakout),
    ("Case 3 -- REJECTED_TOO_SHORT, breakout at day 18", test_case_3_rejected_too_short),
    ("Case 4 -- REJECTED_HEIGHT_FLOOR, too close together", test_case_4_rejected_height_floor),
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
        print("All synthetic assemble_rectangle tests pass. Rectangle definitions-lock stage complete.")
    else:
        print("DO NOT PROCEED until all synthetic tests pass.")
