"""
pivots.py
---------
Isolated pivot (swing high/low) detection module for classical chart pattern
work on PSX daily data.

DESIGN DECISIONS (documented per audit discipline, not left implicit):

1. Fractal-based detection (N bars left, N bars right), NOT a fixed-window
   %/ATR ZigZag for this first version. Rationale: fractal logic is simpler
   to reason about and audit visually against real charts first; we can
   swap in an ATR-based swing definition later and compare, once we know
   the fractal baseline behaves correctly. Don't silently default -- this
   is a deliberate choice to revisit.

2. NO LOOKAHEAD: a pivot found at index i is not "usable" until index
   i + right_bars, because you need `right_bars` of future data to confirm
   it's actually a local high/low. Every pivot object carries an explicit
   `confirmed_at` index. Anything downstream (trendline fitting) must only
   reference pivots where confirmed_at <= "current" index in a backtest
   loop. This field exists specifically so that bug class cannot occur
   silently.

3. TIES: if a run of consecutive bars shares the exact same extreme price
   (common on PSX with circuit-locked names), we take the FIRST bar of the
   tied run as the pivot location. This is a deliberate, documented choice
   -- not an accident of iteration order. It matters for reproducibility.

4. STRICTNESS: "higher than both sides" uses a strict > (or < for lows).
   Equal neighbours are handled by the tie rule above, not by loosening
   the comparison silently.

NOTE: This is a standalone module distinct from breakout_signal.py's
existing ta.pivothigh/ta.pivotlow logic (left=10, right=10, tuned for
breakout-detection). This module uses left=3, right=3 by default, tuned
for finer triangle-boundary granularity. Do not merge or replace either --
different jobs, different tuning.

5. FROZEN-CLOSE COLLAPSING (added after real-data validation found the
   problem it fixes): during PSX circuit-lock / thin-trading plateaus,
   `close` can be pegged flat for many bars while `high`/`low` still wiggle
   from sporadic thin prints (single-share odd-lot quotes, bid/ask noise)
   that never reflect real price discovery. Feeding find_pivots() the raw
   high/low series in that state produces multiple spurious pivots
   scattered across a span a human chartist would draw as one flat line
   (confirmed against real TOWL/ISIL data: 3 and 7 spurious pivots
   respectively, each inside a >1-year frozen-close run). Fixed by
   collapse_frozen_closes() below: any run of >=2 consecutive bars with
   identical close is collapsed into ONE synthetic bar (high=max(high),
   low=min(low) over the run) BEFORE find_pivots() runs, so the frozen run
   occupies exactly one slot in the fractal window instead of N noisy
   slots. This is a structural fix, not a filter -- no volume threshold or
   price-move tolerance is introduced (those would need an arbitrary
   cutoff; this doesn't).
"""

from dataclasses import dataclass
from typing import List, Literal


@dataclass
class Pivot:
    index: int              # bar index where the pivot sits
    kind: Literal["high", "low"]
    price: float
    confirmed_at: int        # first index at which this pivot is knowable


def find_pivots(
    highs: List[float],
    lows: List[float],
    left: int = 3,
    right: int = 3,
) -> List[Pivot]:
    """
    Fractal pivot detection.

    A bar i is a pivot HIGH if highs[i] is strictly greater than every
    high in the window [i-left, i-1] and [i+1, i+right].
    A bar i is a pivot LOW if lows[i] is strictly less than every low in
    the same windows.

    Ties within the comparison windows: if any neighbour equals the
    candidate value, the candidate is NOT a strict local extreme and is
    rejected (see design note 3/4 above) UNLESS the tie is the candidate
    itself being the first bar of a tied plateau -- handled by scanning
    left-to-right and only accepting a bar if no earlier-tied bar in the
    plateau was already accepted as the pivot.

    Returns pivots sorted by index. confirmed_at = index + right.
    """
    n = len(highs)
    assert n == len(lows), "highs and lows must be same length"
    pivots: List[Pivot] = []

    if n == 0 or left < 1 or right < 1:
        return pivots

    for i in range(left, n - right):
        window_hi = highs[i - left:i] + highs[i + 1:i + right + 1]
        window_lo = lows[i - left:i] + lows[i + 1:i + right + 1]

        # --- pivot high check ---
        h = highs[i]
        if all(h > x for x in window_hi):
            pivots.append(Pivot(index=i, kind="high", price=h, confirmed_at=i + right))
        elif all(h >= x for x in window_hi) and any(h == x for x in window_hi):
            j = i - 1
            is_first_of_plateau = True
            while j >= 0 and highs[j] == h:
                is_first_of_plateau = False
                j -= 1
            if is_first_of_plateau:
                pivots.append(Pivot(index=i, kind="high", price=h, confirmed_at=i + right))

        # --- pivot low check ---
        lo = lows[i]
        if all(lo < x for x in window_lo):
            pivots.append(Pivot(index=i, kind="low", price=lo, confirmed_at=i + right))
        elif all(lo <= x for x in window_lo) and any(lo == x for x in window_lo):
            j = i - 1
            is_first_of_plateau = True
            while j >= 0 and lows[j] == lo:
                is_first_of_plateau = False
                j -= 1
            if is_first_of_plateau:
                pivots.append(Pivot(index=i, kind="low", price=lo, confirmed_at=i + right))

    pivots.sort(key=lambda p: (p.index, p.kind))
    return pivots


@dataclass
class CollapsedBar:
    index: int          # ORIGINAL index of the first bar of this run
    end_index: int       # ORIGINAL index of the last bar of this run
    high: float          # max(high) over the run
    low: float            # min(low) over the run
    run_length: int      # number of original bars folded into this one


def collapse_frozen_closes(
    closes: List[float],
    highs: List[float],
    lows: List[float],
) -> List[CollapsedBar]:
    """
    Collapses runs of >=2 consecutive bars with identical close into a
    single synthetic bar (see design note 5 in the module docstring).

    Position convention: the synthetic bar takes the ORIGINAL index of the
    FIRST bar of the frozen run -- consistent with find_pivots()'s existing
    "first bar of a tied plateau" convention (design note 3).

    Runs of length 1 (no repeat) pass through unchanged (run_length=1,
    index == end_index).
    """
    n = len(closes)
    assert n == len(highs) == len(lows), "closes/highs/lows must be same length"
    bars: List[CollapsedBar] = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and closes[j + 1] == closes[i]:
            j += 1
        bars.append(CollapsedBar(
            index=i,
            end_index=j,
            high=max(highs[i:j + 1]),
            low=min(lows[i:j + 1]),
            run_length=j - i + 1,
        ))
        i = j + 1
    return bars


def find_pivots_collapsed(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    left: int = 3,
    right: int = 3,
) -> List[Pivot]:
    """
    Runs collapse_frozen_closes() then find_pivots() on the resulting
    synthetic bar series, and remaps results back to ORIGINAL indices so
    callers never need to know collapsing happened.

    - Pivot.index -> the original index of the first bar of whichever
      (possibly collapsed) bar the pivot sits on.
    - Pivot.confirmed_at -> the original end_index of the collapsed bar
      that supplies the right-most confirming data point. This is the
      first ORIGINAL index at which the pivot is actually knowable --
      confirming a pivot next to a frozen run requires having seen that
      whole run, not just its first bar, so end_index (not index) is used
      here to preserve the no-lookahead guarantee across collapsing.
    """
    bars = collapse_frozen_closes(closes, highs, lows)
    c_highs = [b.high for b in bars]
    c_lows = [b.low for b in bars]
    collapsed_pivots = find_pivots(c_highs, c_lows, left=left, right=right)

    remapped: List[Pivot] = []
    for p in collapsed_pivots:
        start_bar = bars[p.index]
        confirm_bar = bars[p.confirmed_at]
        remapped.append(Pivot(
            index=start_bar.index,
            kind=p.kind,
            price=p.price,
            confirmed_at=confirm_bar.end_index,
        ))
    return remapped
