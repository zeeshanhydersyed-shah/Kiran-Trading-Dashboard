"""
stop_loss_definitions.py
-------------------------
Core, isolated logic for the stop-loss / R-multiple comparison stage:
Brandt's Last Full Day (LFD) stop vs. kiran_sim.py's rolling-low stop,
walked forward bar-by-bar on triangle-breakout candidates. Built in
isolation, tested with synthetic hand-verified cases (see
test_stop_loss_definitions.py), before any real-data run.

Per the locked definitions-lock report (this stage, prior session):

1. ENTRY = breakout-bar close (closes[breakout_idx]). NOT kiran_sim.py's
   signal_day_high+1 buy-stop -- that mechanism assumes a pending,
   not-yet-triggered breakout (signal day precedes confirmation); a
   triangle candidate's breakout_idx is already a close-confirmed event
   (boundaries.check_violation() is close-based), so there's no future
   trigger to wait for. Confirmed inapplicable, not defaulted-to.

2. LFD STOP LEVEL is the RAW structural level only -- lows[breakout_idx-1]
   for an up-breakout, highs[breakout_idx-1] for a down-breakout --
   deliberately reimplemented as a one-line, self-contained computation
   here rather than imported from breakout_classification.py. That
   module's lfd_variant machinery (full/fixed/trigger) governs how LONG
   the LFD level stays "live" for the Type 1-4 classification job; this
   stage's LFD stop is a genuinely different comparison (does the level
   ever get touched, walked forward against a competing stop, no
   supersession window at all) and must not silently inherit
   lfd_variant="trigger" behavior. raw_lfd_level() below has no
   dependency on breakout_classification.py, by construction, so a
   later import of the wrong LFD (e.g. "from breakout_classification
   import classify_breakout" to "simplify" this file) cannot happen
   without visibly changing this module's signature and its own test
   suite catching the divergence -- see
   test_raw_lfd_independent_of_trigger_supersession in the test file.

3. ROLLING-LOW STOP ("kiran-style"): kiran_sim.py itself has no rolling-
   window computation -- it reads a precomputed `support_level` field
   that traces back to backtest.py's _consolidation() (windows 5/7/10
   bars, tightest valid range under MAX_RANGE_PCT=12%, support = lowest
   low over the chosen window). Triangle candidates were never run
   through backtest.py's screener, so there is no field to look up.
   Per the confirmed §1 approach, this module reuses backtest._consolidation()
   UNMODIFIED against each candidate's OWN pre-breakout OHLC, truncated
   to end at breakout_idx-1 inclusive (closes[:breakout_idx] etc.) --
   i.e. data available as of the day immediately before the breakout,
   the same reference bar the LFD level itself uses. This avoids
   lookahead (the breakout bar's own high/low is never fed into the
   window search that's supposedly describing the PRE-breakout base).
   Stop = support * (1 - SL_BUFFER), buffer=0.01, matching kiran_sim.py's
   SL_BUFFER constant. Risk-capped at MAX_SL_PCT=6.0 (kiran_sim.py's
   value, not backtest.py's 12.0 -- this stage is explicitly comparing
   against "kiran_sim's rolling-low stop", not backtest.py's).

4. DOWN-BREAKOUT MIRROR (per confirmed §3): kiran_sim.py is long-only --
   it has no short-side stop to reuse or copy. backtest.py DOES have a
   SHORT block, but it reuses _consolidation()'s res/sup fields directly
   without re-deriving a "recent swing extreme" analogue for the short
   side (its stop = res = FULL-window high, not a recent-window one) --
   that is a different, not-mirrored design choice made in a different
   file for a different purpose, and reusing it here would silently
   import an inconsistency rather than a genuine mirror. This module
   instead builds _consolidation_mirror_short(), new code, that mirrors
   kiran_sim's actual asymmetric design: the FAR boundary (support) is
   the full-window floor, and the STOP reference (resistance) is the
   most recent min(w, SUPPORT_BARS)-bar swing high -- structurally
   identical to the long side's "recent swing low, not a stale crash
   wick" logic, just flipped. Has its own dedicated synthetic tests, not
   inferred from the long-side tests.

5. WALK-FORWARD: bar-by-bar from breakout_idx+1 to
   min(breakout_idx+90, last_available_bar_index) inclusive. Both stops
   are touch-based (intrabar high/low), matching breakout_classification.py's
   own LFD-touch convention -- a real stop order triggers on touch, not
   close. Both stop levels are HARD, exact price comparisons -- no
   tolerance band (same reasoning as breakout_classification.py design
   note 2b: these are real discrete stop-order price levels, not fitted
   boundary lines).

   Anchor-bar rule (unifies "one stop fires", "both fire same bar", and
   "neither fires"): anchor_bar = the earlier of {lfd_hit_bar,
   rolling_hit_bar} that is not None, else horizon_end (fallback: neither
   ever touched). Whichever stop(s) actually fired AT anchor_bar realize
   R = -1.0 (full risk, by construction of a stop hit). The OTHER stop
   (if it didn't fire at anchor_bar -- either it fires later, or never,
   or is unavailable) is marked-to-market using closes[anchor_bar],
   scaled by ITS OWN risk (entry - its own stop), not the other method's
   risk -- comparing realized R in each method's own units at the same
   point in time. If both fire on the same bar, both realize -1.0 and
   simultaneous_hit=True is recorded as its own outcome, not resolved by
   an arbitrary tie-break.

   If the rolling-low stop is unavailable for a candidate (no valid
   consolidation window, or valid but risk > 6%), it is recorded as such
   (status field) and its realized R is left undefined (None) -- the
   candidate ROW is kept, not dropped, per the confirmed scope decision.
"""

from dataclasses import dataclass
from typing import List, Optional

from backtest import _consolidation, MAX_RANGE_PCT, SUPPORT_BARS

SL_BUFFER = 0.01       # matches kiran_sim.py's SL_BUFFER / backtest.py's SL_BUFFER_PCT
MAX_SL_PCT = 6.0        # matches kiran_sim.py's MAX_SL_PCT (not backtest.py's 12.0)
WALK_FORWARD_HORIZON_BARS = 90


# ─────────────────────────────────────────────────────────────────────────
# LFD (raw structural level) -- deliberately independent of
# breakout_classification.py's lfd_variant machinery. See module docstring
# point 2.
# ─────────────────────────────────────────────────────────────────────────

def raw_lfd_level(highs: List[float], lows: List[float], breakout_idx: int, direction: str) -> float:
    """
    LFD reference level: low of the last full day before the breakout for
    an up-breakout, high of that same day for a down-breakout. This is
    the RAW level only -- no supersession window, no lfd_variant. Always
    "live" for the full walk-forward horizon in this module.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
    lfd_idx = breakout_idx - 1
    return lows[lfd_idx] if direction == "up" else highs[lfd_idx]


# ─────────────────────────────────────────────────────────────────────────
# Rolling-low ("kiran-style") stop
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class RollingStopResult:
    status: str              # "ok" | "skipped_risk_gt_6pct" | "no_valid_consolidation"
    stop_level: Optional[float]
    risk_pct: Optional[float]
    window: Optional[int]


def _consolidation_mirror_short(
    closes: list, highs: list, lows: list,
    windows=(5, 7, 10), max_pct=MAX_RANGE_PCT, recent_bars_cap=SUPPORT_BARS,
):
    """
    Down-breakout mirror of backtest._consolidation(), built as new code
    (see module docstring point 4) -- NOT a reuse of backtest.py's own
    SHORT block, which does not re-derive a recent-window analogue.

    Mirrors the LONG side's asymmetry exactly, flipped:
      - Support (far boundary, NOT the stop reference): full-window floor,
        min(lows[-w:]).
      - Resistance (STOP reference): most recent min(w, recent_bars_cap)
        bars' high -- "recent swing high, not a stale spike from weeks
        ago", the mirror image of the long side's "recent swing low, not
        a stale crash wick".
      - Width / tightest-window selection: identical logic to the long
        side, just support/resistance roles swapped.

    Returns the tightest valid window as a dict, or None if no window
    size produces a range within max_pct.
    """
    best = None
    n = len(closes)
    use_hl = (len(highs) == n and len(lows) == n
              and any(h != c for h, c in zip(highs, closes)))

    for w in sorted(windows):
        if n < w + 1:
            continue
        recent_c = closes[-w:]

        # Support: full window floor
        sup = min(lows[-w:]) if use_hl else min(recent_c)

        # Resistance (stop reference): only last recent_bars_cap-capped bars
        res_bars = min(w, recent_bars_cap)
        res = max(highs[-res_bars:]) if use_hl else max(recent_c[-res_bars:])

        if sup <= 0:
            continue
        width = (res - sup) / sup * 100
        if width <= max_pct:
            if best is None or width < best["range_width"]:
                best = {"window": w, "support": round(sup, 2),
                        "resistance": round(res, 2), "range_width": round(width, 2)}
    return best


def rolling_low_stop(
    closes: List[float], highs: List[float], lows: List[float],
    breakout_idx: int, direction: str, entry_price: float,
) -> RollingStopResult:
    """
    Kiran-style rolling-low stop for a triangle candidate. Truncates the
    OHLC series to end at breakout_idx-1 inclusive (closes[:breakout_idx])
    -- data available as of the day before the breakout, matching the LFD
    reference bar and avoiding lookahead into the breakout bar itself.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    c_trunc = closes[:breakout_idx]
    h_trunc = highs[:breakout_idx]
    l_trunc = lows[:breakout_idx]

    if direction == "up":
        consol = _consolidation(c_trunc, h_trunc, l_trunc)
        if consol is None:
            return RollingStopResult("no_valid_consolidation", None, None, None)
        stop = round(consol["support"] * (1 - SL_BUFFER), 2)
        if stop >= entry_price:
            return RollingStopResult("no_valid_consolidation", None, None, consol["window"])
        risk_pct = (entry_price - stop) / entry_price * 100
    else:
        consol = _consolidation_mirror_short(c_trunc, h_trunc, l_trunc)
        if consol is None:
            return RollingStopResult("no_valid_consolidation", None, None, None)
        stop = round(consol["resistance"] * (1 + SL_BUFFER), 2)
        if stop <= entry_price:
            return RollingStopResult("no_valid_consolidation", None, None, consol["window"])
        risk_pct = (stop - entry_price) / entry_price * 100

    if risk_pct > MAX_SL_PCT:
        return RollingStopResult("skipped_risk_gt_6pct", stop, round(risk_pct, 4), consol["window"])

    return RollingStopResult("ok", stop, round(risk_pct, 4), consol["window"])


# ─────────────────────────────────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class WalkForwardResult:
    entry_price: float
    lfd_level: float
    r_lfd_denom: float
    rolling_status: str
    rolling_stop: Optional[float]
    r_rolling_denom: Optional[float]
    lfd_hit_bar: Optional[int]
    rolling_hit_bar: Optional[int]
    anchor_bar: int
    simultaneous_hit: bool
    horizon_reached: bool
    realized_R_lfd: float
    realized_R_rolling: Optional[float]
    # Third arm, added for the opposite-boundary stop comparison. None/absent
    # (opposite_stop=None, the default) reproduces the original 2-stop
    # behavior above EXACTLY -- simultaneous_hit and horizon_reached are
    # still computed only from {lfd, rolling} in that case.
    opposite_stop: Optional[float] = None
    r_opposite_denom: Optional[float] = None
    opposite_hit_bar: Optional[int] = None
    realized_R_opposite: Optional[float] = None


def walk_forward(
    closes: List[float], highs: List[float], lows: List[float],
    breakout_idx: int, direction: str,
    horizon_bars: int = WALK_FORWARD_HORIZON_BARS,
    opposite_stop: Optional[float] = None,
) -> WalkForwardResult:
    """
    Bar-by-bar walk-forward from breakout_idx+1 to
    min(breakout_idx+horizon_bars, last_available_bar_index) inclusive.
    See module docstring point 5 for the anchor-bar rule.

    opposite_stop: optional third stop arm -- a FIXED price level (e.g. the
    un-broken boundary's price at the breakout bar, computed by the caller;
    this module has no dependency on boundaries.py). Touch-checked the same
    way as LFD/rolling (intrabar high/low, no tolerance band), held
    constant for the whole horizon (not re-evaluated bar-by-bar against a
    moving trendline). If None (default), behaves identically to the
    original 2-stop walk-forward.
    """
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    entry_price = closes[breakout_idx]
    lfd_level = raw_lfd_level(highs, lows, breakout_idx, direction)
    r_lfd_denom = (entry_price - lfd_level) if direction == "up" else (lfd_level - entry_price)

    rolling = rolling_low_stop(closes, highs, lows, breakout_idx, direction, entry_price)
    r_rolling_denom = None
    if rolling.status == "ok":
        r_rolling_denom = (entry_price - rolling.stop_level) if direction == "up" \
            else (rolling.stop_level - entry_price)

    r_opposite_denom = None
    if opposite_stop is not None:
        r_opposite_denom = (entry_price - opposite_stop) if direction == "up" \
            else (opposite_stop - entry_price)

    last_bar = len(closes) - 1
    horizon_end = min(breakout_idx + horizon_bars, last_bar)

    lfd_hit_bar = None
    rolling_hit_bar = None
    opposite_hit_bar = None

    rolling_active = rolling.status == "ok"
    opposite_active = r_opposite_denom is not None and r_opposite_denom > 0

    for i in range(breakout_idx + 1, horizon_end + 1):
        if direction == "up":
            lfd_hit = lows[i] <= lfd_level
            rolling_hit = rolling_active and (lows[i] <= rolling.stop_level)
            opposite_hit = opposite_active and (lows[i] <= opposite_stop)
        else:
            lfd_hit = highs[i] >= lfd_level
            rolling_hit = rolling_active and (highs[i] >= rolling.stop_level)
            opposite_hit = opposite_active and (highs[i] >= opposite_stop)

        if lfd_hit and lfd_hit_bar is None:
            lfd_hit_bar = i
        if rolling_hit and rolling_hit_bar is None:
            rolling_hit_bar = i
        if opposite_hit and opposite_hit_bar is None:
            opposite_hit_bar = i

        all_resolved = (
            lfd_hit_bar is not None
            and (not rolling_active or rolling_hit_bar is not None)
            and (not opposite_active or opposite_hit_bar is not None)
        )
        if all_resolved:
            break  # every active stop resolved, no need to keep scanning

    candidates = [b for b in (lfd_hit_bar, rolling_hit_bar, opposite_hit_bar) if b is not None]
    anchor_bar = min(candidates) if candidates else horizon_end

    lfd_fired_at_anchor = (lfd_hit_bar is not None and lfd_hit_bar == anchor_bar)
    rolling_fired_at_anchor = (rolling_hit_bar is not None and rolling_hit_bar == anchor_bar)
    opposite_fired_at_anchor = (opposite_hit_bar is not None and opposite_hit_bar == anchor_bar)
    simultaneous_hit = sum([lfd_fired_at_anchor, rolling_fired_at_anchor, opposite_fired_at_anchor]) >= 2
    horizon_reached = not (lfd_fired_at_anchor or rolling_fired_at_anchor or opposite_fired_at_anchor)

    anchor_close = closes[anchor_bar]

    def mark_to_market(denom):
        if direction == "up":
            return (anchor_close - entry_price) / denom
        return (entry_price - anchor_close) / denom

    realized_R_lfd = -1.0 if lfd_fired_at_anchor else mark_to_market(r_lfd_denom)

    realized_R_rolling = None
    if rolling.status == "ok":
        realized_R_rolling = -1.0 if rolling_fired_at_anchor else mark_to_market(r_rolling_denom)

    realized_R_opposite = None
    if opposite_active:
        realized_R_opposite = -1.0 if opposite_fired_at_anchor else mark_to_market(r_opposite_denom)

    return WalkForwardResult(
        entry_price=entry_price,
        lfd_level=lfd_level,
        r_lfd_denom=r_lfd_denom,
        rolling_status=rolling.status,
        rolling_stop=rolling.stop_level,
        r_rolling_denom=r_rolling_denom,
        lfd_hit_bar=lfd_hit_bar,
        rolling_hit_bar=rolling_hit_bar,
        anchor_bar=anchor_bar,
        simultaneous_hit=simultaneous_hit,
        horizon_reached=horizon_reached,
        realized_R_lfd=realized_R_lfd,
        realized_R_rolling=realized_R_rolling,
        opposite_stop=opposite_stop if opposite_active else None,
        r_opposite_denom=r_opposite_denom if opposite_active else None,
        opposite_hit_bar=opposite_hit_bar,
        realized_R_opposite=realized_R_opposite,
    )
