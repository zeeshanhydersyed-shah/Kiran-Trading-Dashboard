"""
adaptive_switching_stop.py
-----------------------------
A third stop-comparison alternative, on top of the two static stops
already built (stop_loss_definitions.py's LFD and opposite-boundary
arms): a trade that STARTS on the LFD stop and SWITCHES to the
opposite-boundary stop if price breaches the original (broken) pattern
boundary before the LFD stop is ever touched. Built in isolation, tested
synthetically, before any real-data run -- same discipline as everything
before this.

MATH SPEC (locked before coding):

1. Entry = closes[breakout_idx] (unchanged from stop_loss_definitions.py).
2. lfd_level computed via stop_loss_definitions.raw_lfd_level() -- the
   same raw, un-superseded LFD level used everywhere else in this stage.
   Reused directly (imported), not recomputed by hand, to guarantee this
   rule's LFD is identical to the static-LFD baseline it's compared
   against.
3. opposite_stop is NOT recomputed here -- it is the SAME fixed price
   (opposite boundary's price at the breakout bar) already computed for
   the static opposite-boundary arm, passed in by the caller.
4. BOUNDARY-BREACH DETECTION: reuses breakout_classification.classify_breakout()
   itself (not a hand-copied formula) to get `first_breach_idx` -- the
   same touch/breach test that already distinguishes Type 2 from Type 3
   everywhere else in this study. Called with lfd_variant="full" (the
   only variant that needs no closes/measured_move_height) SOLELY to
   obtain first_breach_idx; every LFD-related field on the returned
   BreakoutClassification is discarded, never read. This keeps this
   module's own LFD (point 2) fully decoupled from lfd_variant, exactly
   like stop_loss_definitions.py's raw_lfd_level -- classify_breakout()
   is used here as a pure, tested breach-bar oracle, nothing else.

   IMPORTANT, DOCUMENTED DEVIATION: classify_breakout() is called with
   THIS STAGE'S OWN 90-trading-day walk-forward horizon
   (min(breakout_idx+90, last_bar)), NOT the narrower apex-based horizon
   (min(n-1, end+40, apex_index+5)) that produced the already-locked
   Type 1-4 classification in breakout_classification_variant_results.csv.
   The breach-test FORMULA is reused verbatim; the WINDOW it's evaluated
   over is this stage's own, for consistency with the LFD/rolling/opposite
   walk-forwards already built here. This does NOT change or recompute
   Type 1-4 anywhere -- that classification stays exactly as already
   locked. It does mean a candidate could show a breach here that the
   original (narrower-horizon) Type 2/3 classification never saw, if the
   breach happens between the old horizon's end and the new 90-bar one.
   Quantified in the synthetic test suite (test D) and checked for on
   real candidates before the full run.

5. WALK-FORWARD LOGIC, bar-by-bar from breakout_idx+1 to horizon_end:
   At each bar, if not yet switched: check LFD touch FIRST. If LFD
   touches this bar, the trade exits on LFD immediately -- no switch,
   regardless of whether this is also the breach bar (ties go to LFD,
   per explicit design). Only if LFD does NOT touch this bar is the
   breach checked: if this bar equals first_breach_idx, the trade
   switches from this bar forward (inclusive -- the breach bar itself is
   also checked against the new opposite stop, since "from that bar
   forward" is inclusive of it). Once switched, only the opposite stop is
   checked on every subsequent bar (LFD is never checked again). If the
   horizon ends with no exit, the trade is marked-to-market at the
   horizon-end close.

6. R-MULTIPLE DENOMINATOR CONVENTION -- both computed, per explicit
   instruction ("propose an answer with reasoning... report both ways"):

   CONVENTION A (fixed, PRIMARY/recommended): denominator = r_lfd_denom
   (entry's distance to the ORIGINAL LFD level) for the ENTIRE trade,
   even after switching. Reasoning: a trade's position SIZE is set at
   entry based on the risk that was actually taken at that moment (the
   LFD distance, per design point 1 -- "every trade starts on the LFD
   stop"). Widening the stop later doesn't retroactively resize the
   position; it changes how much of that ALREADY-COMMITTED risk gets
   used. Expressing the switched outcome in original-LFD-R units answers
   the honest question "how did this trade do relative to what I
   actually risked at entry" -- a stop-out at the wider opposite level
   after switching realizes MORE than -1.0 R in these units (e.g. -1.6R),
   correctly showing that switching increased realized risk beyond the
   original plan. It is also the only convention directly comparable,
   apples-to-apples, to the existing static realized_R_lfd baseline,
   since both share the same denominator whenever no switch occurs.

   CONVENTION B (re-based, SECONDARY): denominator becomes r_opposite_denom
   for any bar at or after the switch. A stop-out at the opposite level
   always realizes a clean -1.0 in this convention (by construction),
   which is simpler to read but collapses the switched-and-stopped-out
   case to look identical to a trade that was risking the wider distance
   from bar one -- it can't distinguish "switching cost me more than I
   signed up for" from "I was always going to lose this much." Reported
   as a secondary lens, not the primary metric.

   Both conventions AGREE for every trade that never switches (both
   reduce to the LFD-only case) and for the exit-on-LFD-before-breach
   case -- they only diverge for the switched subset. The numerator
   (price move from ENTRY, never re-anchored to the switch bar) is
   identical in both conventions; only the denominator differs.
"""

from dataclasses import dataclass
from typing import List, Optional

from boundaries import Boundary
from breakout_classification import classify_breakout
from stop_loss_definitions import raw_lfd_level, WALK_FORWARD_HORIZON_BARS

DEFAULT_TOLERANCE_PCT = 0.015


@dataclass
class AdaptiveSwitchResult:
    entry_price: float
    lfd_level: float
    r_lfd_denom: float
    opposite_stop: float
    r_opposite_denom: float
    first_breach_idx: Optional[int]
    switched: bool
    switch_bar: Optional[int]
    exit_bar: int
    exit_stop: Optional[str]      # "lfd" | "opposite" | None (horizon fallback)
    horizon_reached: bool
    realized_R_fixed: float       # Convention A (primary)
    realized_R_rebased: float     # Convention B (secondary)


def adaptive_switching_walk_forward(
    closes: List[float], highs: List[float], lows: List[float],
    breakout_idx: int, direction: str,
    boundary: Boundary, opposite_stop: float,
    horizon_bars: int = WALK_FORWARD_HORIZON_BARS,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> AdaptiveSwitchResult:
    """
    boundary: the ORIGINAL (broken) boundary -- upper for an up-breakout,
    lower for a down-breakout. Caller's responsibility, same convention
    as classify_breakout() elsewhere in this study.
    opposite_stop: the fixed price level already computed for the static
    opposite-boundary arm (opposite_boundary.price_at(breakout_idx)).
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    entry_price = closes[breakout_idx]
    lfd_level = raw_lfd_level(highs, lows, breakout_idx, direction)
    r_lfd_denom = (entry_price - lfd_level) if direction == "up" else (lfd_level - entry_price)
    r_opposite_denom = (entry_price - opposite_stop) if direction == "up" else (opposite_stop - entry_price)

    last_bar = len(closes) - 1
    horizon_end = min(breakout_idx + horizon_bars, last_bar)

    cbr = classify_breakout(
        boundary, highs, lows, breakout_idx, direction, horizon_end,
        tolerance_pct=tolerance_pct, lfd_variant="full",
    )
    first_breach_idx = cbr.first_breach_idx  # ONLY field read from cbr -- see module docstring point 4

    switched = False
    switch_bar = None
    exit_bar = None
    exit_stop = None

    for i in range(breakout_idx + 1, horizon_end + 1):
        if not switched:
            lfd_hit = (lows[i] <= lfd_level) if direction == "up" else (highs[i] >= lfd_level)
            if lfd_hit:
                exit_bar, exit_stop = i, "lfd"
                break
            if first_breach_idx is not None and i == first_breach_idx:
                switched = True
                switch_bar = i
                # "from that bar forward" is inclusive -- fall through to
                # also check the opposite stop on this same bar.
        if switched:
            opp_hit = (lows[i] <= opposite_stop) if direction == "up" else (highs[i] >= opposite_stop)
            if opp_hit:
                exit_bar, exit_stop = i, "opposite"
                break

    horizon_reached = exit_bar is None
    if exit_bar is None:
        exit_bar = horizon_end

    exit_close = closes[exit_bar]

    def mark_to_market(denom):
        if direction == "up":
            return (exit_close - entry_price) / denom
        return (entry_price - exit_close) / denom

    # Convention A (fixed, primary)
    if exit_stop == "lfd":
        realized_R_fixed = -1.0
    elif exit_stop == "opposite":
        realized_R_fixed = -(r_opposite_denom / r_lfd_denom)
    else:
        realized_R_fixed = mark_to_market(r_lfd_denom)

    # Convention B (re-based, secondary) -- identical to A unless switched
    if exit_stop == "lfd":
        realized_R_rebased = -1.0
    elif exit_stop == "opposite":
        realized_R_rebased = -1.0
    elif switched:
        realized_R_rebased = mark_to_market(r_opposite_denom)
    else:
        realized_R_rebased = mark_to_market(r_lfd_denom)

    return AdaptiveSwitchResult(
        entry_price=entry_price,
        lfd_level=lfd_level,
        r_lfd_denom=r_lfd_denom,
        opposite_stop=opposite_stop,
        r_opposite_denom=r_opposite_denom,
        first_breach_idx=first_breach_idx,
        switched=switched,
        switch_bar=switch_bar,
        exit_bar=exit_bar,
        exit_stop=exit_stop,
        horizon_reached=horizon_reached,
        realized_R_fixed=realized_R_fixed,
        realized_R_rebased=realized_R_rebased,
    )
