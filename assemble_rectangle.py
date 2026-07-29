"""
assemble_rectangle.py
-----------------------
Rectangle pattern assembly, building on top of fit_horizontal_level().
Grows a candidate window day-by-day from an anchor pivot, fitting both
boundaries incrementally, checking for height validation, and detecting
close-based breakouts using check_violation() (reuse unchanged).

Built and tested IN ISOLATION against hand-verified synthetic cases only
(test_assemble_rectangle.py) -- no real PSX data yet.

DESIGN DECISIONS (documented per audit discipline):

1. DUAL-BOUNDARY TRACKING: exactly one boundary is anchored (at anchor_price),
   the other is non-anchored (discovers from opposite_pivots). Both are fit
   using fit_horizontal_level() incrementally as the window grows, filtering
   opposite_pivots to only those at indices <= current day.

2. HEIGHT CHECK AT FIRST DUAL-VALIDITY: the moment BOTH boundaries reach
   min_touches, compute height_pct = abs(resistance - support) / support.
   If below the floor (margin_multiplier * (2*tolerance_pct/(1-tolerance_pct)),
   ~0.061 at defaults), close immediately as REJECTED_HEIGHT_FLOOR -- do NOT
   wait for a breakout that would never qualify anyway.

3. BREAKOUT CHECK (close-based, via check_violation()): once both boundaries
   are valid and height passes, check each subsequent day's close against
   both boundaries' tolerance bands. On breach: if elapsed calendar days <
   min_duration_days (21), close as REJECTED_TOO_SHORT (per ChartSchool's
   flag/rectangle cutoff). Otherwise close as VALID.

4. CAP CHECK: if elapsed calendar days reaches max_duration_days (60) with
   both boundaries valid, height passing, and no breach, close as
   EXPIRED_NO_BREAKOUT (recorded as its own outcome, not dropped).

5. UNRESOLVED: if the non-anchored boundary never reaches min_touches before
   the cap (a fifth outcome, REJECTED_INSUFFICIENT_TOUCHES), that's out of
   scope for this pass -- flagged in docstring rather than decided silently.

6. CALENDAR DATES: duration_days is computed from anchor_index to the breach
   day (or max_duration_days) using the 'day' field in price_bars (an integer
   offset from some epoch, exact units don't matter as long as they're
   consistent for duration comparisons).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from fit_horizontal_level import fit_horizontal_level
from boundaries import check_violation, Boundary


@dataclass
class RectangleResult:
    outcome: str  # VALID, REJECTED_HEIGHT_FLOOR, REJECTED_TOO_SHORT, EXPIRED_NO_BREAKOUT
    support_level: float
    resistance_level: float
    duration_days: int
    breakout_direction: Optional[str]  # 'up' or 'down', None unless VALID


def assemble_rectangle(
    anchor_index: int,
    anchor_price: float,
    anchor_side: str,  # 'support' or 'resistance'
    support_pivots: List[Tuple[int, float]],  # (index, price) of lows, chronological
    resistance_pivots: List[Tuple[int, float]],  # (index, price) of highs, chronological
    price_bars: List[dict],  # [{day, close, ...}, ...] indexed by bar index
    tolerance_pct: float = 0.015,
    min_touches: int = 3,
    min_duration_days: int = 21,
    max_duration_days: int = 60,
    margin_multiplier: float = 2.0,
) -> RectangleResult:
    """
    Assemble a rectangle candidate from an anchor pivot and support/resistance
    pivots, growing the window day-by-day. Return the final outcome.

    anchor_side: 'support' (anchor is at support level, resistance discovered) or
                 'resistance' (anchor is at resistance level, support discovered).
    support_pivots: chronological stream of (index, price) for all support pivots (lows).
                   When anchor_side='support', the anchor itself at anchor_index
                   is EXCLUDED from this list (anchor is passed separately).
    resistance_pivots: chronological stream of (index, price) for all resistance pivots (highs).
                      When anchor_side='resistance', the anchor itself at anchor_index
                      is EXCLUDED from this list (anchor is passed separately).
    price_bars: daily bars with 'day' (integer offset) and 'close' fields.
    """
    if anchor_side not in ("support", "resistance"):
        raise ValueError(f"anchor_side must be 'support' or 'resistance', got {anchor_side}")

    # Track state as we grow the window day-by-day
    support_level = None
    resistance_level = None
    support_valid = False
    resistance_valid = False
    both_valid_day = None
    height_valid = False
    breakout_day = None
    breakout_direction = None

    anchor_day = price_bars[anchor_index]["day"]

    # For each day from anchor_index onwards
    for current_index in range(anchor_index, len(price_bars)):
        current_day = price_bars[current_index]["day"]
        current_duration = current_day - anchor_day

        # Incremental fit: filter pivots to those at indices <= current_index
        filtered_support = [(idx, price) for idx, price in support_pivots if idx <= current_index]
        filtered_resistance = [(idx, price) for idx, price in resistance_pivots if idx <= current_index]

        if anchor_side == "support":
            # Anchor is support, discover resistance
            support_fit = fit_horizontal_level(filtered_support, anchor_price=anchor_price, tolerance_pct=tolerance_pct, min_touches=min_touches)
            support_level = support_fit.level
            support_valid = support_fit.valid

            resistance_fit = fit_horizontal_level(filtered_resistance, anchor_price=None, tolerance_pct=tolerance_pct, min_touches=min_touches)
            resistance_level = resistance_fit.level
            resistance_valid = resistance_fit.valid
        else:  # anchor_side == 'resistance'
            # Anchor is resistance, discover support
            resistance_fit = fit_horizontal_level(filtered_resistance, anchor_price=anchor_price, tolerance_pct=tolerance_pct, min_touches=min_touches)
            resistance_level = resistance_fit.level
            resistance_valid = resistance_fit.valid

            support_fit = fit_horizontal_level(filtered_support, anchor_price=None, tolerance_pct=tolerance_pct, min_touches=min_touches)
            support_level = support_fit.level
            support_valid = support_fit.valid

        # Once both valid, check height and then breakout
        if support_valid and resistance_valid and both_valid_day is None:
            both_valid_day = current_day

            # Height check
            height_pct = abs(resistance_level - support_level) / support_level
            min_height = margin_multiplier * (2 * tolerance_pct / (1 - tolerance_pct))

            if height_pct < min_height:
                return RectangleResult(
                    outcome="REJECTED_HEIGHT_FLOOR",
                    support_level=support_level,
                    resistance_level=resistance_level,
                    duration_days=current_duration,
                    breakout_direction=None,
                )

            height_valid = True

        # Breakout check (only if both valid and height passed)
        if height_valid and breakout_day is None:
            close = price_bars[current_index]["close"]

            # Create synthetic Boundary objects for check_violation
            # Resistance boundary: slope=0, intercept=resistance_level
            resistance_boundary = Boundary(slope=0.0, intercept=resistance_level, touch_indices=[], all_candidate_indices=[])

            # Support boundary: slope=0, intercept=support_level
            support_boundary = Boundary(slope=0.0, intercept=support_level, touch_indices=[], all_candidate_indices=[])

            # Check for breach: we only need to check today's close
            resistance_breach = check_violation(
                resistance_boundary,
                [close],  # Single-element list with just today's close
                start_index=0,
                end_index=0,
                direction="upper",
                tolerance_pct=tolerance_pct,
            )

            support_breach = check_violation(
                support_boundary,
                [close],
                start_index=0,
                end_index=0,
                direction="lower",
                tolerance_pct=tolerance_pct,
            )

            if resistance_breach or support_breach:
                breakout_day = current_day
                breakout_duration = current_day - anchor_day

                if breakout_duration < min_duration_days:
                    return RectangleResult(
                        outcome="REJECTED_TOO_SHORT",
                        support_level=support_level,
                        resistance_level=resistance_level,
                        duration_days=breakout_duration,
                        breakout_direction=None,
                    )

                breakout_direction = "up" if resistance_breach else "down"
                return RectangleResult(
                    outcome="VALID",
                    support_level=support_level,
                    resistance_level=resistance_level,
                    duration_days=breakout_duration,
                    breakout_direction=breakout_direction,
                )

        # Cap check
        if current_duration >= max_duration_days and height_valid:
            return RectangleResult(
                outcome="EXPIRED_NO_BREAKOUT",
                support_level=support_level,
                resistance_level=resistance_level,
                duration_days=max_duration_days,
                breakout_direction=None,
            )

    # If we've exhausted all price_bars without reaching max_duration_days
    # and without returning above, we've hit the end of data
    # (shouldn't happen in normal use, but handle it gracefully)
    if height_valid:
        return RectangleResult(
            outcome="EXPIRED_NO_BREAKOUT",
            support_level=support_level,
            resistance_level=resistance_level,
            duration_days=price_bars[-1]["day"] - anchor_day,
            breakout_direction=None,
        )

    # If we get here, one or both boundaries never reached min_touches
    # (REJECTED_INSUFFICIENT_TOUCHES -- out of scope, flagged in docstring)
    return RectangleResult(
        outcome="REJECTED_INSUFFICIENT_TOUCHES",
        support_level=support_level or 0.0,
        resistance_level=resistance_level or 0.0,
        duration_days=price_bars[-1]["day"] - anchor_day,
        breakout_direction=None,
    )
