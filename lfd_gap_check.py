"""
lfd_gap_check.py
------------------
Part 1 of the gap-risk / re-entry stage: checks whether the LFD stop's
assumed clean -1.0R exit (touch-based, no gap modeling, as computed by
stop_loss_definitions.py) is realistic against the actual OPEN price of
the bar that triggered it.

MATH SPEC:

The walk-forward in stop_loss_definitions.py detects an LFD "hit" via
intrabar low/high crossing the level (lows[i] <= lfd_level for an
up-breakout), and assumes the exit fills AT the LFD level exactly,
realizing precisely -1.0R. This is optimistic whenever the trigger bar's
OPEN already gapped through the level before the bar even started
trading -- a stop order can't fill at a price the market never traded
at. If open[i] is already beyond lfd_level in the adverse direction, the
realistic fill is open[i], not lfd_level, and the realized loss exceeds
-1.0R.

gap_through(direction, open_price, lfd_level):
  up:   gapped = open_price < lfd_level        (strictly beyond, adverse)
  down: gapped = open_price > lfd_level
  Exactly AT the level (open_price == lfd_level) is NOT a gap -- a stop
  order sitting exactly at the open would still fill there.

realistic_exit_price = open_price if gapped else lfd_level (i.e. the
existing, already-computed assumption is kept unchanged when there's no
gap -- this module only ever makes realized_R MORE negative, never less).

realistic_realized_R = mark_to_market(realistic_exit_price, entry_price,
r_lfd_denom, direction) -- same mark-to-market formula already used
throughout this stage.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class GapCheckResult:
    gapped: bool
    realistic_exit_price: float
    realistic_realized_R: float
    worse_by_R: float  # realistic_realized_R - (-1.0); 0.0 if not gapped, negative if gapped


def check_lfd_gap(
    direction: str, open_price: float, lfd_level: float,
    entry_price: float, r_lfd_denom: float,
) -> GapCheckResult:
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    if direction == "up":
        gapped = open_price < lfd_level
    else:
        gapped = open_price > lfd_level

    realistic_exit_price = open_price if gapped else lfd_level

    if direction == "up":
        realistic_realized_R = (realistic_exit_price - entry_price) / r_lfd_denom
    else:
        realistic_realized_R = (entry_price - realistic_exit_price) / r_lfd_denom

    worse_by_R = realistic_realized_R - (-1.0)

    return GapCheckResult(
        gapped=gapped,
        realistic_exit_price=realistic_exit_price,
        realistic_realized_R=realistic_realized_R,
        worse_by_R=worse_by_R,
    )
