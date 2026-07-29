"""
breakout_classification.py
----------------------------
Type 1-4 post-breakout classification (Kibar/TechCharts framework,
Brandt's Last Full Day / negation-level concept), built on top of
pivots.py, boundaries.py, and triangle.py. This is the stage after
breakout-occurrence counting -- classifies WHAT KIND of breakout each
already-detected breakout was, not whether one occurred.

Still does NOT do stop-loss / R-multiple / entry-exit logic -- that is
the next stage after this.

SOURCES: Aksel Kibar / TechCharts "A Framework for Classifying Chart
Pattern Breakouts" (blog.techcharts.net, 2026-07-14), and Peter Brandt's
original Last Full Day (LFD) / 3-Day Trailing Stop concept. Confirmed via
direct fetch of the TechCharts article (not assumed) that the Last Full
Day reference level mirrors by direction: for an upside breakout it is
the LOW of the last full day still inside the pattern before the
breakout ("stop just below that day's low"); for a downside breakdown it
is the HIGH of that same day ("stop just above that day's high"). This
resolves the one open ambiguity flagged before coding.

DESIGN DECISIONS (documented, not implicit):

1. NEGATION LEVEL = LFD LEVEL, A DELIBERATE SIMPLIFICATION OF THE SOURCE
   FRAMEWORK. The TechCharts source treats "LFD Low violation" (its
   Type 3) and "chart pattern negation level violation" (its Type 4) as
   TWO DIFFERENT, increasingly severe thresholds -- Type 3 breaches the
   LFD level but the pattern's own deeper structural negation level still
   holds; Type 4 breaches that deeper level too. This module, per
   explicit instruction, collapses them into ONE level: the negation
   level IS the LFD level. This changes what "Type 3 vs Type 4" means
   here relative to the named source -- Type 4 in this module fires on
   the same LFD touch that would only be a Type 3 warning sign in the
   original two-tier framework. Documented so this deviation from the
   named source is never silently assumed to be identical to it.

2. TWO DIFFERENT TOUCH TESTS, EACH WITH A DELIBERATELY DIFFERENT
   TOLERANCE CONVENTION:
     a. BOUNDARY touch/breach uses the same tolerance_pct band as
        fit_boundary()/check_violation() elsewhere in this study (default
        1.5%) -- the boundary is a continuously extrapolated, fitted
        trendline, not a discrete historical price, so "close enough" is
        the right operational test, consistent with how this project
        already treats boundary interactions everywhere else.
          - "touched": price reaches within tolerance_pct of the
            boundary (may be slightly through it, within tolerance).
          - "breached": price crosses DECISIVELY beyond tolerance to the
            far side. Breach is a strict subset of touch by construction
            (breach implies touch, never the reverse) -- the breach
            threshold (1 - tolerance_pct) is always tighter than the
            touch threshold (1 + tolerance_pct).
     b. LFD touch is a HARD, EXACT price comparison -- no tolerance band.
        Brandt's own methodology is literally a stop-order placement
        ("stop just below that day's low") -- a real discrete historical
        price level, and a stop order triggers on any touch, not a
        percentage-tolerance approximation of one. A tolerance band here
        would invent slack the original concept doesn't have.

3. TOUCH-BASED, NOT CLOSE-BASED (per explicit instruction, confirmed
   against Kibar's stated methodology that stops trigger on touch): both
   the boundary and LFD checks use intrabar HIGH/LOW, never close. This
   is deliberately different from check_violation() in boundaries.py
   (used for breakout-OCCURRENCE detection elsewhere in this study),
   which is close-based -- these are two different jobs (did a breakout
   happen at all vs. how did price behave intrabar after one already
   did), not an inconsistency.

4. CLASSIFICATION PRIORITY ORDER: Type 4 (LFD touched) checked first,
   then Type 3 (boundary breached), then Type 2 (boundary touched), else
   Type 1 -- because these conditions are not mutually exclusive as raw
   per-bar events (a Type 4 case will typically also have breached the
   boundary somewhere along the way to reaching the LFD level), and the
   classification reports the single WORST outcome that occurred within
   the horizon, not the first one chronologically.

5. EVALUATION WINDOW: breakout_idx+1 through horizon_end INCLUSIVE, where
   horizon_end is the same min(window_end+40, apex_index+5) horizon
   already used for breakout-occurrence counting elsewhere in this study
   -- not a new or different window. BOUNDARY touch/breach is ALWAYS
   evaluated over this full window, in every lfd_variant below -- only
   the LFD-touch window length changes between variants (see note 6).

6. LFD WINDOW-LENGTH ISSUE, FOUND VIA REAL DATA (2026-07-15 follow-up):
   checking LFD touch across the FULL breakout-occurrence horizon (up to
   ~45 bars) made Type 4 fire on 69% of all 544 real candidates, including
   the majority of clean "up"/"down" breakouts -- far too liberal relative
   to Kibar's own stated practice, where the LFD low is an INITIAL stop
   only, meant to be superseded by trailing-stop methods once the trade
   develops, not tested indefinitely. Three variants available via the
   `lfd_variant` parameter, all still callable directly for comparison:
     - "full": LFD checked across the full horizon (the original,
       unmodified behavior).
     - "fixed": LFD checked only for `lfd_fixed_bars` bars after the
       breakout (e.g. 5 or 10) -- after that, a later LFD touch no longer
       counts toward Type 3/4, even though boundary touch/breach keeps
       being checked over the full horizon as always.
     - "trigger": LFD is "live" only until the CLOSE first reaches the
       breakout price plus/minus the candidate's own measured-move height
       in the breakout direction (i.e. the pattern's own price objective
       is reached) -- once hit, LFD is superseded from the NEXT bar
       onward (the trigger bar itself is the last bar LFD is still
       checked on, since supersession is a consequence of that bar's own
       close). If the target is never reached within the horizon, this
       variant falls back to checking LFD across the full horizon, same
       as "full".

   LOCKED DECISION (2026-07-15): "trigger" is the default (DEFAULT_LFD_VARIANT
   below) going forward, chosen over "fixed" after a 544-candidate 3-way
   comparison (full vs fixed_5 vs fixed_10 vs trigger). Reasoning: fixed_5
   cut the up/down false-Type-4 rate the most (to ~39%) but degraded the
   sequential-outcome-to-Type-4 mapping the most severely (98.4% -> 54.4%
   -- a 5-bar window is too short to even catch many genuine reversals it
   should catch). fixed_10 and trigger land in a similar middle ground on
   both axes (up/down Type-4 rate ~43-52%, sequential mapping ~74-75%);
   trigger was chosen over fixed_10 because its cutoff is derived from the
   pattern's OWN measured-move height rather than an arbitrary bar count,
   consistent with how every other tolerance/threshold in this study
   (fit_boundary, is_forced_line, flat_cumulative_pct) is defined relative
   to the pattern's own geometry, not a fixed constant.

   CARRIED FORWARD, NOT RESOLVED BY THIS DECISION: even under "trigger",
   46.6% of clean "up" breakouts and 52.1% of clean "down" breakouts still
   touch their own LFD level at some point before the trigger threshold is
   reached. This is an open, unquantified finding -- not something locking
   the trigger variant fixes -- carried into the next stage (stop-loss /
   R-multiple comparison) for proper measurement, not resolved here.
"""

from dataclasses import dataclass
from typing import List, Optional

from boundaries import Boundary

DEFAULT_TOLERANCE_PCT = 0.015
DEFAULT_LFD_VARIANT = "trigger"  # locked 2026-07-15, see design note 6


@dataclass
class BreakoutClassification:
    type: int  # 1, 2, 3, or 4
    breakout_idx: int
    direction: str  # "up" or "down"
    lfd_idx: int
    lfd_level: float
    lfd_variant: str  # "full" | "fixed" | "trigger"
    lfd_end_idx: int  # last bar index LFD was actually checked on
    boundary_touched: bool
    boundary_breached: bool
    lfd_touched: bool
    first_touch_idx: Optional[int]
    first_breach_idx: Optional[int]
    first_lfd_touch_idx: Optional[int]


def _resolve_lfd_end_idx(
    lfd_variant: str,
    breakout_idx: int,
    horizon_end: int,
    direction: str,
    lfd_fixed_bars: Optional[int],
    closes: Optional[List[float]],
    measured_move_height: Optional[float],
) -> int:
    """Determines the last bar index (inclusive) LFD is checked on, per
    lfd_variant. See design note 6."""
    if lfd_variant == "full":
        return horizon_end

    if lfd_variant == "fixed":
        if lfd_fixed_bars is None:
            raise ValueError("lfd_fixed_bars is required when lfd_variant='fixed'")
        return min(breakout_idx + lfd_fixed_bars, horizon_end)

    if lfd_variant == "trigger":
        if closes is None or measured_move_height is None:
            raise ValueError("closes and measured_move_height are required when lfd_variant='trigger'")
        breakout_close = closes[breakout_idx]
        target = (breakout_close + measured_move_height if direction == "up"
                  else breakout_close - measured_move_height)
        for i in range(breakout_idx + 1, horizon_end + 1):
            hit = closes[i] >= target if direction == "up" else closes[i] <= target
            if hit:
                return i  # LFD still checked on the trigger bar itself, not after
        return horizon_end  # target never reached -- fall back to full horizon

    raise ValueError(f"lfd_variant must be 'full', 'fixed', or 'trigger', got {lfd_variant!r}")


def classify_breakout(
    boundary: Boundary,
    highs: List[float],
    lows: List[float],
    breakout_idx: int,
    direction: str,
    horizon_end: int,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    lfd_variant: str = DEFAULT_LFD_VARIANT,
    lfd_fixed_bars: Optional[int] = None,
    closes: Optional[List[float]] = None,
    measured_move_height: Optional[float] = None,
) -> BreakoutClassification:
    """
    Classify a single breakout as Type 1 (momentum), Type 2 (controlled
    retest), Type 3 (hard retest, boundary breached), or Type 4 (failed,
    LFD/negation level touched).

    boundary: the line that was broken AT the breakout (upper boundary
        for an "up" direction, lower boundary for a "down" direction --
        caller's responsibility to pass the correct one).
    highs, lows: the full intrabar high/low series for the symbol, in
        the same bar-index space the boundary was fit against.
    breakout_idx: bar index of the breakout (the first violation).
    direction: "up" or "down".
    horizon_end: last bar index to evaluate (inclusive) -- same horizon
        already used for breakout-occurrence counting. BOUNDARY
        touch/breach is always evaluated over this full window regardless
        of lfd_variant (see design note 5).
    tolerance_pct: boundary touch/breach tolerance (see design note 2a).
        Does NOT apply to the LFD check (see design note 2b).
    lfd_variant: "trigger" (default, LOCKED 2026-07-15), "fixed", or
        "full" -- see design note 6. "trigger" (the default) REQUIRES
        closes and measured_move_height -- callers relying on the default
        must supply both. "fixed" requires lfd_fixed_bars instead.

    LFD level: lows[breakout_idx - 1] for an up-breakout, or
    highs[breakout_idx - 1] for a down-breakout -- the reference bar
    immediately preceding the breakout bar. Unaffected by lfd_variant --
    only how LONG that level stays "live" changes.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    lfd_idx = breakout_idx - 1
    lfd_level = lows[lfd_idx] if direction == "up" else highs[lfd_idx]

    lfd_end_idx = _resolve_lfd_end_idx(
        lfd_variant, breakout_idx, horizon_end, direction,
        lfd_fixed_bars, closes, measured_move_height,
    )

    first_touch_idx = None
    first_breach_idx = None
    first_lfd_touch_idx = None

    for i in range(breakout_idx + 1, horizon_end + 1):
        boundary_price = boundary.price_at(i)

        if direction == "up":
            touched = lows[i] <= boundary_price * (1 + tolerance_pct)
            breached = lows[i] < boundary_price * (1 - tolerance_pct)
            lfd_hit = lows[i] <= lfd_level
        else:
            touched = highs[i] >= boundary_price * (1 - tolerance_pct)
            breached = highs[i] > boundary_price * (1 + tolerance_pct)
            lfd_hit = highs[i] >= lfd_level

        if touched and first_touch_idx is None:
            first_touch_idx = i
        if breached and first_breach_idx is None:
            first_breach_idx = i
        if lfd_hit and i <= lfd_end_idx and first_lfd_touch_idx is None:
            first_lfd_touch_idx = i

    boundary_touched = first_touch_idx is not None
    boundary_breached = first_breach_idx is not None
    lfd_touched = first_lfd_touch_idx is not None

    if lfd_touched:
        btype = 4
    elif boundary_breached:
        btype = 3
    elif boundary_touched:
        btype = 2
    else:
        btype = 1

    return BreakoutClassification(
        type=btype,
        breakout_idx=breakout_idx,
        direction=direction,
        lfd_idx=lfd_idx,
        lfd_level=lfd_level,
        lfd_variant=lfd_variant,
        lfd_end_idx=lfd_end_idx,
        boundary_touched=boundary_touched,
        boundary_breached=boundary_breached,
        lfd_touched=lfd_touched,
        first_touch_idx=first_touch_idx,
        first_breach_idx=first_breach_idx,
        first_lfd_touch_idx=first_lfd_touch_idx,
    )
