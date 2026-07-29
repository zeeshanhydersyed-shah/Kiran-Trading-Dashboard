"""
triangle.py
-----------
Assembles a triangle candidate from a pair of fitted Boundary objects
(upper, from pivot highs; lower, from pivot lows), built on top of
boundaries.py. This is the first stage where the three prior modules
(pivots, boundaries) come together into an actual pattern classification.

Still does NOT do breakout confirmation or the Type 1-4 post-breakout
classification -- that's the next stage after this is validated.

DESIGN DECISIONS (documented, not implicit):

1. CONVERGENCE, NOT JUST OPPOSING SLOPES. Two lines with a downward-sloping
   upper and upward-sloping lower aren't automatically a valid triangle --
   they must actually converge ahead of (or within a sane distance past)
   the current window. The apex is found by solving for where the two
   lines intersect: slope_u*x + b_u = slope_l*x + b_l. If the apex falls
   BEHIND the window (already "passed"), or absurdly far ahead (further
   than some multiple of the pattern's own width), the pair is rejected
   as non-convergent -- this is a common failure mode of naive
   implementations that only check slope signs.

2. CLASSIFICATION BY SLOPE, WITH AN EXPLICIT "FLAT" BAND BASED ON
   CUMULATIVE MOVE OVER THE ANALYZED WINDOW, NOT THE TOUCH SPAN OR A
   PER-BAR RATE. A boundary is "flat" if the total percentage move in
   its fitted (extrapolated) price from window_start_index to
   window_end_index is below flat_cumulative_pct (default 0.03, i.e. 3%).

   This went through two design iterations, each found via real PSX
   data, not synthetic tests:
     a. First version used a per-bar slope rate. Found (via KEL) to
        compound over long windows -- negligible bar-to-bar rate can
        total 8%+ drift over 80 bars, visibly not flat to the eye.
     b. Second version used cumulative move over the boundary's own
        TOUCH SPAN (first touch to last touch). Found (via another KEL
        window) to still misfire when touches cluster near one edge of
        the window: the touch span itself can show <1% move while the
        fitted line, extrapolated across the FULL window width for
        plotting/pattern purposes, moves 3%+ edge to edge. "Flat over
        the touches" and "flat over the drawn pattern" are different
        claims when touches are lopsided.
     c. Current version: measure cumulative move over window_start_index
        to window_end_index (the actual analyzed/drawn span), using the
        fitted line's price AT those bounds, not at touch points. This
        is the quantity that matches what's visually judged and what
        gets used for pattern negation / breakout logic later -- the
        boundary as it spans the whole pattern, not just where pivots
        happened to land.

     - upper flat + lower rising -> ascending triangle
     - upper falling + lower flat -> descending triangle
     - upper falling + lower rising -> symmetrical triangle
     - anything else (e.g. both falling, both rising, upper flat AND
       lower flat, upper rising) -> NOT a triangle; classify_triangle
       returns None rather than forcing a label. A parallel channel or
       a wedge is a genuinely different pattern and must not be mislabeled.

3. DURATION IS CALLER-SUPPLIED IN CALENDAR DAYS, NOT BAR COUNT. Per the
   real-PSX finding that thin names can have gaps of hundreds of days
   between consecutive bars, this module accepts explicit start/end
   dates (or a caller-computed day-count) rather than inferring duration
   from index difference. Bar-index spacing is NOT a safe proxy for time
   on PSX.

4. MINIMUM TOUCH COUNT is caller-supplied per boundary (default 2, can be
   raised to 3 for a stricter definition), consistent with boundaries.py.

5. TOUCH SPACING -- REJECTS "FORCED" TRENDLINES. Per ChartSchool's own
   spacing rule (ChartSchool, Trend Lines article): touches that are too
   close together weaken the validity of the reaction low/high being
   confirmed, and a line built mostly from adjacent/near-duplicate touch
   points is not a meaningfully validated trendline even if it fits the
   data perfectly -- it's forced. Found via direct user feedback while
   reviewing real PSX charts: some classified boundaries "matched pivots"
   but felt forced, i.e. technically fit but not what a chartist would
   draw by eye.

   Two checks, both required for a boundary to count as genuinely
   validated rather than forced:
     a. SPAN: the touches must span at least min_touch_span_fraction
        (default 0.5, i.e. 50%) of the window width. A boundary whose
        touches are all crammed into one corner of the window is not
        tracking the pattern as a whole, regardless of how well those
        few points fit a line.
     b. PAIRWISE GAP: no two touches may sit closer together than
        min_pairwise_gap_bars (default 5 bars). Near-adjacent touches
        are close to being the same reaction low/high counted twice,
        which inflates the apparent touch count without adding real
        confirmation.

   A boundary failing either check is treated as insufficiently
   validated -- assemble_triangle rejects the pair (returns None)
   rather than accepting a technically-fitting but forced line.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import date

from boundaries import Boundary


@dataclass
class TriangleCandidate:
    kind: str  # "symmetrical" | "ascending" | "descending"
    upper: Boundary
    lower: Boundary
    apex_index: float
    apex_price: float
    window_start_index: int
    window_end_index: int
    duration_days: int


def is_forced_line(
    boundary: Boundary,
    window_start_index: int,
    window_end_index: int,
    min_touch_span_fraction: float = 0.5,
    min_pairwise_gap_bars: int = 5,
) -> bool:
    """
    Returns True if the boundary's touches are too clustered to count as
    a genuinely validated trendline -- either crammed into a small part
    of the window, or containing near-duplicate adjacent touches -- per
    ChartSchool's spacing rule. See module docstring point 5.
    """
    touches = sorted(boundary.touch_indices)
    if len(touches) < 2:
        return True  # can't even check spacing with <2 touches

    window_width = window_end_index - window_start_index
    if window_width <= 0:
        return True

    touch_span = touches[-1] - touches[0]
    if touch_span < min_touch_span_fraction * window_width:
        return True  # touches crammed into one part of the window

    for i in range(1, len(touches)):
        if touches[i] - touches[i - 1] < min_pairwise_gap_bars:
            return True  # near-duplicate touches, inflated confirmation

    return False


def compute_apex(upper: Boundary, lower: Boundary) -> Optional[tuple]:
    """
    Solve for the intersection of the two boundary lines.
    Returns (apex_index, apex_price), or None if the lines are parallel
    (no intersection -- a channel, not a converging triangle).
    """
    slope_diff = upper.slope - lower.slope
    if slope_diff == 0:
        return None
    apex_index = (lower.intercept - upper.intercept) / slope_diff
    apex_price = upper.price_at(apex_index)
    return apex_index, apex_price


def classify_triangle(
    upper: Boundary,
    lower: Boundary,
    window_start_index: int,
    window_end_index: int,
    flat_cumulative_pct: float = 0.03,
) -> Optional[str]:
    """
    Classify the (upper, lower) boundary pair by direction/flatness.
    Returns None if the pair doesn't match any of the three triangle
    shapes (e.g. both rising, both falling -- not a triangle).

    Flatness is judged by the CUMULATIVE percentage move in the fitted
    (extrapolated) line's price from window_start_index to
    window_end_index -- the actual analyzed/drawn span, not the touch
    points.
    """
    def cumulative_move_pct(boundary: Boundary) -> float:
        start_price = boundary.price_at(window_start_index)
        end_price = boundary.price_at(window_end_index)
        if start_price == 0:
            return 0.0
        return (end_price - start_price) / abs(start_price)

    upper_move = cumulative_move_pct(upper)
    lower_move = cumulative_move_pct(lower)

    upper_flat = abs(upper_move) < flat_cumulative_pct
    lower_flat = abs(lower_move) < flat_cumulative_pct
    upper_falling = upper_move <= -flat_cumulative_pct
    upper_rising = upper_move >= flat_cumulative_pct
    lower_rising = lower_move >= flat_cumulative_pct
    lower_falling = lower_move <= -flat_cumulative_pct

    if upper_falling and lower_rising:
        return "symmetrical"
    if upper_flat and lower_rising:
        return "ascending"
    if upper_falling and lower_flat:
        return "descending"
    return None  # not a triangle shape: channel, wedge, or incoherent pair


def assemble_triangle(
    upper: Boundary,
    lower: Boundary,
    window_start_index: int,
    window_end_index: int,
    start_date: date,
    end_date: date,
    min_touches: int = 2,
    max_apex_distance_multiplier: float = 3.0,
    flat_cumulative_pct: float = 0.03,
    min_touch_span_fraction: float = 0.5,
    min_pairwise_gap_bars: int = 5,
) -> Optional[TriangleCandidate]:
    """
    Combine a fitted upper + lower boundary into a validated triangle
    candidate, or return None if any validity check fails.

    Checks, in order:
      1. Both boundaries meet min_touches.
      2. Both boundaries pass the touch-spacing check (not a forced
         line -- see module docstring point 5 and is_forced_line()).
      3. Direction/flatness (judged by cumulative % move over the
         analyzed window) classifies as one of the 3 triangle shapes.
      4. Lines actually converge (non-parallel) with an apex that is
         AHEAD of window_end_index (not already passed) and not further
         ahead than max_apex_distance_multiplier * window width -- an
         apex hundreds of bars away is not a usable pattern.
      5. Duration (in calendar days, caller-supplied dates) is positive.
    """
    if len(upper.touch_indices) < min_touches:
        return None
    if len(lower.touch_indices) < min_touches:
        return None

    if is_forced_line(upper, window_start_index, window_end_index,
                       min_touch_span_fraction, min_pairwise_gap_bars):
        return None
    if is_forced_line(lower, window_start_index, window_end_index,
                       min_touch_span_fraction, min_pairwise_gap_bars):
        return None

    kind = classify_triangle(
        upper, lower,
        window_start_index=window_start_index,
        window_end_index=window_end_index,
        flat_cumulative_pct=flat_cumulative_pct,
    )
    if kind is None:
        return None

    apex = compute_apex(upper, lower)
    if apex is None:
        return None
    apex_index, apex_price = apex

    window_width = window_end_index - window_start_index
    if window_width <= 0:
        return None

    if apex_index < window_end_index:
        return None
    if apex_index > window_end_index + max_apex_distance_multiplier * window_width:
        return None

    duration_days = (end_date - start_date).days
    if duration_days <= 0:
        return None

    return TriangleCandidate(
        kind=kind,
        upper=upper,
        lower=lower,
        apex_index=apex_index,
        apex_price=apex_price,
        window_start_index=window_start_index,
        window_end_index=window_end_index,
        duration_days=duration_days,
    )
