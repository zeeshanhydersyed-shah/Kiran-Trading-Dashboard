"""
fit_horizontal_level.py
------------------------
Rectangle-pattern horizontal boundary fitting. Built per the Q1 (Path B) design
decision in Rectangle_Pattern_Specification_v1.md (Section 2 / 2.1): a dedicated
fit that pins slope at exactly 0 by construction, rather than reusing
boundaries.py's free-slope fit_boundary() and classifying flatness post hoc.

Built and tested IN ISOLATION against hand-verified synthetic cases only
(test_fit_horizontal_level.py) -- no real PSX data yet, same discipline as
pivots.py / boundaries.py in the triangle study.

DESIGN DECISIONS (documented per audit discipline, not left implicit):

1. TWO MODES, per the confirmed Q6 adaptive-windowing design (Rectangle spec
   Section 3.2): exactly one boundary of a growing rectangle candidate is
   ANCHORED -- its first touch IS the window's anchor pivot, fixed by
   construction, never a discovered candidate. The other boundary is
   NON-ANCHORED and must discover its level organically as same-kind pivots
   arrive during growth.

2. ANCHORED MODE has no candidate-selection question at all (Q3 is moot for
   this boundary -- Rectangle spec Section 3, step 3's note). The anchor price
   is touch #1 by construction. TOUCH TESTING uses the FIXED anchor price
   throughout, not a moving target -- confirmed against the hand-verified
   synthetic cases (test_fit_horizontal_level.py Case A/B), where every
   candidate pivot's tolerance band is anchored to the original anchor price,
   never to an intermediate refit level. The RETURNED level is a separate
   thing: the running median of all confirmed touches (anchor + every pivot
   that passed the fixed-anchor touch test) -- a location-only refit, no
   slope, so the reported level can move slightly as more touches accumulate
   but can never "reinterpret itself as sloped" the way
   boundaries.fit_boundary()'s free-slope Theil-Sen/OLS fit can (see Rectangle
   spec Section 2.1's incremental-growth-stability argument, the primary
   reason Path B was reaffirmed). Touch membership and the reported level are
   deliberately different computations, unlike the non-anchored case below.

3. NON-ANCHORED MODE clusters pivots one at a time, in the order given
   (chronological, per the adaptive-growth window): a new pivot joins whichever
   existing candidate cluster's CURRENT level it falls within tolerance_pct of
   (ties among multiple matching clusters broken by closest price -- an
   implementation detail not covered by the confirmed spec, since none of the
   hand-verified cases exercise it; flagged here rather than left silent),
   refitting that cluster's level as the running median of its members. If no
   cluster matches, the pivot seeds a new one-member cluster. The "leading
   candidate" at any point is the cluster with the highest touch count; TIES
   ARE BROKEN BY TIGHTEST INLIER SPREAD (max-minus-min price among a cluster's
   members), never earliest-seeded cluster -- this is Q3's confirmed
   resolution (Rectangle spec Section 6, Q3): adaptive growth should let
   accumulating evidence determine the level, not lock onto whichever pivot
   happened to arrive first.

4. RECOMPUTED FROM SCRATCH EACH CALL, not incrementally optimized. Per the
   confirmed spec: "state can be recomputed from the full pivot list each
   call -- no need to optimize for incremental-only updates at this stage."
   Callers simulating a growing window call this function with successively
   longer pivot-list prefixes.

5. TOUCH TEST: abs(price - L) <= L * tolerance_pct -- identical
   percentage-of-price tolerance-band convention to boundaries.fit_boundary()
   / triangle.py, for consistency across the whole pipeline (Rectangle spec
   Section 3, step 2).

6. touch_count for the ANCHORED case includes the anchor itself (touch #1)
   even though the anchor has no index in the `pivots` list passed in --
   touch_indices only lists indices of PIVOTS (from the `pivots` argument)
   that matched; the anchor's contribution is implicit in
   touch_count = 1 + len(touch_indices). This matches the spec's own
   accounting ("touches = anchor + idx5 + idx12 = 3").
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class LevelFit:
    level: float
    touch_indices: List[int]
    touch_count: int
    valid: bool
    anchored: bool


def _median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _is_touch(price: float, level: float, tolerance_pct: float) -> bool:
    return abs(price - level) <= level * tolerance_pct


def _fit_anchored(
    pivots: List[Tuple[int, float]],
    anchor_price: float,
    tolerance_pct: float,
    min_touches: int,
) -> LevelFit:
    # Touch testing uses the FIXED anchor_price throughout (design note 2) --
    # NOT a moving target. Confirmed against Case A: idx12 (99.0) is a touch
    # of anchor=100.0 (diff 1.0 <= tol 1.5) even after idx5 (101.2) has
    # already been confirmed and would have shifted a moving reference level.
    confirmed_prices = [anchor_price]
    touch_indices: List[int] = []

    for idx, price in pivots:
        if _is_touch(price, anchor_price, tolerance_pct):
            confirmed_prices.append(price)
            touch_indices.append(idx)

    # The RETURNED level is refit once, as the median of all confirmed
    # touches -- a separate computation from touch membership (design note 2).
    level = _median(confirmed_prices)
    touch_count = 1 + len(touch_indices)
    return LevelFit(
        level=level,
        touch_indices=touch_indices,
        touch_count=touch_count,
        valid=touch_count >= min_touches,
        anchored=True,
    )


@dataclass
class _Cluster:
    member_indices: List[int] = field(default_factory=list)
    member_prices: List[float] = field(default_factory=list)
    level: float = 0.0

    @property
    def touch_count(self) -> int:
        return len(self.member_indices)

    @property
    def spread(self) -> float:
        if not self.member_prices:
            return 0.0
        return max(self.member_prices) - min(self.member_prices)

    def add(self, idx: int, price: float) -> None:
        self.member_indices.append(idx)
        self.member_prices.append(price)
        self.level = _median(self.member_prices)


def _select_leading(clusters: List[_Cluster]) -> _Cluster:
    """Leading candidate = highest touch count; ties broken by tightest
    inlier spread (Q3, confirmed 2026-07-16) -- never earliest-seeded
    cluster. This is a regression-guarded rule, not an incidental default;
    see test_fit_horizontal_level.py Case D."""
    best = clusters[0]
    for cluster in clusters[1:]:
        if cluster.touch_count > best.touch_count:
            best = cluster
        elif cluster.touch_count == best.touch_count and cluster.spread < best.spread:
            best = cluster
    return best


def _fit_non_anchored(
    pivots: List[Tuple[int, float]],
    tolerance_pct: float,
    min_touches: int,
) -> LevelFit:
    clusters: List[_Cluster] = []

    for idx, price in pivots:
        matching = [c for c in clusters if _is_touch(price, c.level, tolerance_pct)]
        if not matching:
            new_cluster = _Cluster()
            new_cluster.add(idx, price)
            clusters.append(new_cluster)
        else:
            closest = min(matching, key=lambda c: abs(price - c.level))
            closest.add(idx, price)

    if not clusters:
        return LevelFit(level=0.0, touch_indices=[], touch_count=0, valid=False, anchored=False)

    leading = _select_leading(clusters)
    return LevelFit(
        level=leading.level,
        touch_indices=list(leading.member_indices),
        touch_count=leading.touch_count,
        valid=leading.touch_count >= min_touches,
        anchored=False,
    )


def fit_horizontal_level(
    pivots: List[Tuple[int, float]],
    anchor_price: Optional[float] = None,
    tolerance_pct: float = 0.015,
    min_touches: int = 3,
) -> LevelFit:
    """
    Fit a horizontal rectangle boundary level (Rectangle spec Section 3), in
    either anchored or non-anchored mode (design notes 1-3 above).

    `pivots` must be a chronologically-ordered list of (index, price) tuples
    of ONE pivot type (all highs, or all lows -- never mixed; caller's
    responsibility, same convention as boundaries.fit_boundary()),
    representing the adaptively-growing window as it accumulates.
    """
    if anchor_price is not None:
        return _fit_anchored(pivots, anchor_price, tolerance_pct, min_touches)
    return _fit_non_anchored(pivots, tolerance_pct, min_touches)
