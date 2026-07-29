"""
boundaries.py
-------------
Trendline (boundary) fitting for classical chart patterns, built on top of
pivots.py. This module answers ONE question in isolation: given a set of
pivot highs (or lows), what is the best-fit boundary line, and which pivots
actually "belong" to it?

It does NOT do triangle assembly (duration, apex/convergence, breakout
confirmation) yet -- that's the next stage, built on top of this once this
is independently tested and trusted. Same discipline as pivots.py: audited
in isolation first.

DESIGN DECISIONS (documented, not implicit):

1. TOUCH != EXACT CONTACT. A pivot "touches" a boundary if it falls within
   a tolerance band around the fitted line -- not if it sits exactly on it.
   Tolerance is expressed as a percentage of price at that point (not ATR,
   for this first version -- simpler to reason about and audit; an ATR
   version can be built later and compared once this baseline works).
   Default tolerance: 1.5% of price.

   This directly addresses the "pivot 3 doesn't touch the line but pivot 4
   does" problem: pivot 3 sitting slightly inside the triangle (below a
   downward-sloping upper boundary, or above an upward-sloping lower one)
   is NOT a violation and NOT required to touch -- it's simply interior.
   Only pivots within the tolerance band count as touches; pivots clearly
   interior are ignored by the fit, not treated as failures.

2. ROBUST FIT VIA INLIER ITERATION (RANSAC-lite), not a rigid 2-point line.
   Process:
     a. Start from a Theil-Sen slope estimate (median of all pairwise
        slopes between candidate pivots) -- robust to a single outlier
        pivot, unlike ordinary least squares on only 2-3 points.
     b. Fit an initial line through that slope + median intercept.
     c. Classify each candidate pivot as inlier (within tolerance) or
        outlier.
     d. Refit (ordinary least squares) using only inliers.
     e. Repeat c-d until the inlier set stops changing (or a max
        iteration cap is hit).
   This means a later pivot (e.g. pivot 4) can pull the line's fit even
   though an earlier one (pivot 3) sits inside tolerance-not-touching --
   the fit adapts to whichever pivots are actually near the boundary,
   rather than being locked to the first two points found.

3. VIOLATION IS SEPARATE FROM TOUCH, AND IS CHECKED ON CLOSE, NOT PIVOTS.
   A boundary is "violated" if a bar's CLOSE price crosses through the
   line by more than the tolerance, in the invalidating direction, at any
   point in the pattern window. This is deliberately independent of
   pivot touch logic: an interior pivot that never violates the line is
   just interior (fine); a close that pushes through the line is a real
   violation (relevant for pattern negation later). Keeping these two
   checks separate avoids conflating "didn't touch" with "broke the
   pattern", which was the exact confusion in the original question this
   module answers.

4. MINIMUM TOUCH COUNT is a caller-supplied parameter (default 2, per
   ChartSchool's minimum), not hard-coded, so the pattern-assembly layer
   can require 3 for a stricter definition without changing this module.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import statistics

from pivots import Pivot


@dataclass
class Boundary:
    slope: float
    intercept: float          # price = slope * index + intercept
    touch_indices: List[int]  # indices of pivots that count as touches (inliers)
    all_candidate_indices: List[int]  # every pivot index considered as input

    def price_at(self, index: int) -> float:
        return self.slope * index + self.intercept


def _theil_sen_slope(points: List[Tuple[int, float]]) -> float:
    """Median of all pairwise slopes. Robust to a single outlier point."""
    slopes = []
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            xi, yi = points[i]
            xj, yj = points[j]
            if xj != xi:
                slopes.append((yj - yi) / (xj - xi))
    if not slopes:
        return 0.0
    return statistics.median(slopes)


def _ols_fit(points: List[Tuple[int, float]]) -> Tuple[float, float]:
    """Ordinary least squares line fit. Returns (slope, intercept)."""
    n = len(points)
    if n == 1:
        x0, y0 = points[0]
        return 0.0, y0 - 0.0 * x0
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    num = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    den = sum((p[0] - mean_x) ** 2 for p in points)
    if den == 0:
        return 0.0, mean_y
    slope = num / den
    intercept = mean_y - slope * mean_x
    return slope, intercept


def fit_boundary(
    pivots: List[Pivot],
    tolerance_pct: float = 0.015,
    max_iterations: int = 10,
) -> Optional[Boundary]:
    """
    Fit a robust boundary line through a list of same-kind pivots
    (all pivot highs, or all pivot lows -- caller's responsibility to
    pass a single kind).

    Returns None if fewer than 2 pivots are supplied (can't fit a line).
    """
    if len(pivots) < 2:
        return None

    points = [(p.index, p.price) for p in pivots]
    candidate_indices = [p.index for p in pivots]

    # Step 1: robust initial slope via Theil-Sen, intercept via median residual
    slope = _theil_sen_slope(points)
    residual_intercepts = [y - slope * x for x, y in points]
    intercept = statistics.median(residual_intercepts)

    # last_valid tracks the most recent (slope, intercept, inliers) state that
    # actually achieved >=2 inliers. If this stays None, no genuine boundary
    # was ever found and we must return None -- NOT fall back to the raw,
    # unfiltered candidate list. This is the fix for the bug where an initial
    # fit finding <2 inliers used to silently leak `points` (every candidate)
    # into touch_indices while reporting the unrefit Theil-Sen line, making a
    # garbage line look fully validated.
    last_valid = None
    prev_inlier_set = None

    for _ in range(max_iterations):
        # classify inliers: within tolerance_pct of price at that index
        new_inliers = []
        for x, y in points:
            predicted = slope * x + intercept
            tol = abs(predicted) * tolerance_pct
            if abs(y - predicted) <= tol:
                new_inliers.append((x, y))

        if len(new_inliers) < 2:
            # can't refit with fewer than 2 -- stop, keep whatever last_valid
            # already holds (may be None if this is the first iteration)
            break

        current_inlier_set = frozenset(new_inliers)
        slope, intercept = _ols_fit(new_inliers)
        last_valid = (slope, intercept, new_inliers)

        if current_inlier_set == prev_inlier_set:
            break
        prev_inlier_set = current_inlier_set

    if last_valid is None:
        # No genuine 2+ inlier fit was ever achieved. Returning None rather
        # than a line fit to unfiltered/outlier candidates -- an absence of
        # a boundary is a valid, honest outcome; a fabricated one is not.
        return None

    slope, intercept, inlier_points = last_valid
    touch_indices = [x for x, _ in inlier_points]

    return Boundary(
        slope=slope,
        intercept=intercept,
        touch_indices=touch_indices,
        all_candidate_indices=candidate_indices,
    )


def check_violation(
    boundary: Boundary,
    closes: List[float],
    start_index: int,
    end_index: int,
    direction: str,
    tolerance_pct: float = 0.015,
) -> List[int]:
    """
    Check whether any CLOSE price violates the boundary (crosses through
    by more than tolerance) between start_index and end_index inclusive.

    direction: "upper" means closes should stay AT OR BELOW the boundary
               (violation = close decisively above it)
               "lower" means closes should stay AT OR ABOVE the boundary
               (violation = close decisively below it)

    Returns list of bar indices where a violation occurred (empty if none).
    """
    violations = []
    for i in range(start_index, end_index + 1):
        if i < 0 or i >= len(closes):
            continue
        predicted = boundary.price_at(i)
        tol = abs(predicted) * tolerance_pct
        close = closes[i]
        if direction == "upper" and close > predicted + tol:
            violations.append(i)
        elif direction == "lower" and close < predicted - tol:
            violations.append(i)
    return violations
