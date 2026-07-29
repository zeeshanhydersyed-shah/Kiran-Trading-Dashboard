"""
lfd_reentry_chain.py
-----------------------
Part 2 of the gap-risk / re-entry stage: after a trade is stopped out on
its LFD stop, checks whether the SAME original (fitted, un-refit)
pattern boundary is crossed again at a later bar, treating that as a
brand-new, independent trade. Built in isolation, tested synthetically,
before any real-data run.

MATH SPEC:

1. LEG 1 (the original trade): entry = closes[breakout_idx], lfd_level =
   stop_loss_definitions.raw_lfd_level() at breakout_idx. Walked forward
   from breakout_idx+1 to min(breakout_idx+90, last_bar) checking ONLY
   the LFD touch condition (this part is explicitly LFD-only, per
   instruction -- rolling/opposite stops are out of scope here).

2. IF LEG 1 IS NOT STOPPED OUT (LFD never touched within its horizon):
   the chain ends at 1 leg. No re-entry check is performed -- re-entry is
   explicitly triggered by an actual stop-out, not by a trade simply
   running to horizon-close.

3. IF LEG 1 IS STOPPED OUT at bar exit_bar: search for a re-entry in
   [exit_bar+1, min(exit_bar+90, last_bar)] -- the SAME 90-bar horizon
   convention reused for consistency (not specified verbatim by the
   task; chosen here and flagged, rather than an unbounded search).
   Re-entry detection reuses boundaries.check_violation() UNMODIFIED --
   the exact same close-based test that detects the ORIGINAL breakout
   everywhere else in this study (NOT breakout_classification.py's
   touch-based retest test, which is a different job -- checking
   post-breakout behavior of an already-confirmed breakout, not
   detecting a fresh one). direction="up" -> boundary=the original upper
   boundary, check_violation(..., direction="upper"); direction="down"
   -> lower boundary, direction="lower". The boundary is NEVER refit --
   its price_at(i) is evaluated (extrapolated) at whatever later index
   check_violation() is scanning, exactly the caller-facing behavior
   confirmed already present in boundaries.py (price_at is a pure linear
   function, slope*index+intercept, with no domain restriction -- no new
   math, just calling the existing method further out than it has been
   called before in this study).

4. IF A RE-ENTRY IS FOUND at bar re_idx: LEG 2 starts fresh -- new entry
   = closes[re_idx] (that later bar's close -- NOT the original breakout
   price, and NOT reusing leg 1's LFD level). new lfd_level computed
   fresh via raw_lfd_level() at re_idx. Walked forward exactly like leg
   1, from re_idx+1 to min(re_idx+90, last_bar).

5. This repeats: each stop-out triggers a re-entry search, each re-entry
   found starts a fresh leg, up to MAX_REENTRIES (default 3, i.e. up to
   4 total legs) -- proposed and reported on, not assumed necessary.
   `cap_bound` reports whether, after the LAST allowed leg's own
   stop-out, a re-entry condition WOULD have been found (search is still
   performed for reporting purposes, just not acted on) -- this measures
   whether the cap is actually binding, not just how many legs a chain
   happened to reach.

6. FULL-CHAIN REALIZED R: each leg is an explicitly independent trade
   (new entry, new stop, new risk distance) -- NOT a single trade whose
   stop moved (contrast with the adaptive-switching-stop work, where a
   shared denominator convention was a genuine open design question).
   Here, summing each leg's OWN realized_R (each already expressed in
   its own R-multiple units, per the existing walk-forward convention)
   is the standard, well-defined way to tally a sequence of independent,
   equally-risked trades -- exactly how a trader summing R across a
   string of trades would do it. chain_realized_R = sum(leg.realized_R
   for leg in legs). Documented here as a deliberate choice, not picked
   silently, but not treated as a live ambiguity the way the adaptive
   rule's denominator was.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from boundaries import Boundary, check_violation
from stop_loss_definitions import raw_lfd_level, WALK_FORWARD_HORIZON_BARS

DEFAULT_TOLERANCE_PCT = 0.015
DEFAULT_MAX_REENTRIES = 3


@dataclass
class Leg:
    entry_bar: int
    entry_price: float
    lfd_level: float
    r_lfd_denom: float
    exit_bar: int
    exit_type: str          # "lfd" | "horizon"
    realized_R: float


@dataclass
class ChainResult:
    legs: List[Leg] = field(default_factory=list)
    n_reentries: int = 0
    cap_bound: bool = False   # a re-entry condition existed after the last allowed leg's stop-out, but the cap prevented acting on it
    chain_realized_R: float = 0.0


def _walk_one_leg(closes, highs, lows, entry_idx, direction, horizon_bars):
    entry_price = closes[entry_idx]
    lfd_level = raw_lfd_level(highs, lows, entry_idx, direction)
    r_lfd_denom = (entry_price - lfd_level) if direction == "up" else (lfd_level - entry_price)

    last_bar = len(closes) - 1
    horizon_end = min(entry_idx + horizon_bars, last_bar)

    exit_bar = None
    for i in range(entry_idx + 1, horizon_end + 1):
        hit = (lows[i] <= lfd_level) if direction == "up" else (highs[i] >= lfd_level)
        if hit:
            exit_bar = i
            break

    if exit_bar is not None:
        return Leg(entry_bar=entry_idx, entry_price=entry_price, lfd_level=lfd_level,
                    r_lfd_denom=r_lfd_denom, exit_bar=exit_bar, exit_type="lfd", realized_R=-1.0)

    exit_bar = horizon_end
    exit_close = closes[exit_bar]
    if direction == "up":
        realized_R = (exit_close - entry_price) / r_lfd_denom
    else:
        realized_R = (entry_price - exit_close) / r_lfd_denom
    return Leg(entry_bar=entry_idx, entry_price=entry_price, lfd_level=lfd_level,
               r_lfd_denom=r_lfd_denom, exit_bar=exit_bar, exit_type="horizon", realized_R=realized_R)


def _find_reentry(closes, boundary, direction, search_start, search_end):
    """Returns the first bar index in [search_start, search_end] where the
    ORIGINAL boundary is re-crossed in the breakout direction, close-based,
    via check_violation() unmodified -- or None if never."""
    if search_start > search_end:
        return None
    cv_direction = "upper" if direction == "up" else "lower"
    violations = check_violation(boundary, closes, start_index=search_start, end_index=search_end,
                                  direction=cv_direction, tolerance_pct=DEFAULT_TOLERANCE_PCT)
    return violations[0] if violations else None


def walk_reentry_chain(
    closes: List[float], highs: List[float], lows: List[float],
    breakout_idx: int, direction: str, boundary: Boundary,
    max_reentries: int = DEFAULT_MAX_REENTRIES,
    horizon_bars: int = WALK_FORWARD_HORIZON_BARS,
) -> ChainResult:
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    last_bar = len(closes) - 1
    legs = []
    n_reentries = 0
    cap_bound = False

    entry_idx = breakout_idx
    while True:
        leg = _walk_one_leg(closes, highs, lows, entry_idx, direction, horizon_bars)
        legs.append(leg)

        if leg.exit_type != "lfd":
            break  # chain ends: this leg ran to horizon-close, no re-entry check

        search_start = leg.exit_bar + 1
        search_end = min(leg.exit_bar + horizon_bars, last_bar)

        if n_reentries >= max_reentries:
            # cap already reached by a PRIOR re-entry -- check (report-only)
            # whether a re-entry condition exists here too, to measure if
            # the cap is actually binding.
            re_idx = _find_reentry(closes, boundary, direction, search_start, search_end)
            if re_idx is not None:
                cap_bound = True
            break

        re_idx = _find_reentry(closes, boundary, direction, search_start, search_end)
        if re_idx is None:
            break  # chain ends: stopped out, no re-entry found

        n_reentries += 1
        entry_idx = re_idx

    chain_realized_R = sum(leg.realized_R for leg in legs)

    return ChainResult(legs=legs, n_reentries=n_reentries, cap_bound=cap_bound,
                        chain_realized_R=chain_realized_R)
