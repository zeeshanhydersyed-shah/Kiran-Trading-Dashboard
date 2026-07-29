"""
fixed_pct_stop_target.py
----------------------------
TASK 2: fixed-percentage stop/target scheme, entirely independent of the
LFD/boundary machinery used everywhere else in this study.

CONFIRMED INTERPRETATION (stated explicitly per instruction, not assumed
silently): stop-loss = 2% from entry (breakout-bar close), target = 4%
from entry (fixed 1:2 risk:reward). R=1.0 unit = the 2% risk. Both fixed
percentages entirely replace the dynamic LFD/boundary stop levels for
this comparison -- this module has no dependency on stop_loss_definitions.py
or breakout_classification.py.

ONE DETAIL THE INSTRUCTION LEFT UNSPECIFIED, DECIDED HERE, FLAGGED NOT
HIDDEN: same-bar gap-through (a single bar's range touches BOTH stop and
target). Resolved conservatively -- STOP WINS on a tie, since real
intrabar sequencing isn't available and assuming the better outcome
(target) would be optimistic, not neutral. Tested explicitly (see
test_fixed_pct_stop_target.py) so this convention is visible and could be
changed if a different assumption is wanted.
"""

from dataclasses import dataclass
from typing import List, Optional

STOP_PCT = 0.02
TARGET_PCT = 0.04
HORIZON_BARS = 90


@dataclass
class FixedPctResult:
    entry_price: float
    stop_price: float
    target_price: float
    exit_bar: int
    exit_type: str  # "stop" | "target" | "horizon"
    realized_R: float
    realized_pct_of_capital: float  # using R * RISK_FRAC, computed by caller normally; here just R * STOP_PCT for raw %


def walk_forward_fixed_pct(
    closes: List[float], highs: List[float], lows: List[float],
    breakout_idx: int, direction: str,
    horizon_bars: int = HORIZON_BARS,
) -> FixedPctResult:
    if direction not in ("up", "down"):
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")

    entry = closes[breakout_idx]
    if direction == "up":
        stop = entry * (1 - STOP_PCT)
        target = entry * (1 + TARGET_PCT)
    else:
        stop = entry * (1 + STOP_PCT)
        target = entry * (1 - TARGET_PCT)

    last_bar = len(closes) - 1
    horizon_end = min(breakout_idx + horizon_bars, last_bar)

    exit_bar = None
    exit_type = None

    for i in range(breakout_idx + 1, horizon_end + 1):
        if direction == "up":
            stop_hit = lows[i] <= stop
            target_hit = highs[i] >= target
        else:
            stop_hit = highs[i] >= stop
            target_hit = lows[i] <= target

        if stop_hit and target_hit:
            exit_bar, exit_type = i, "stop"  # conservative tie-break, see module docstring
            break
        if stop_hit:
            exit_bar, exit_type = i, "stop"
            break
        if target_hit:
            exit_bar, exit_type = i, "target"
            break

    if exit_bar is None:
        exit_bar = horizon_end
        exit_type = "horizon"
        exit_close = closes[exit_bar]
        if direction == "up":
            realized_R = (exit_close - entry) / entry / STOP_PCT
        else:
            realized_R = (entry - exit_close) / entry / STOP_PCT
    elif exit_type == "stop":
        realized_R = -1.0
    else:  # target
        realized_R = TARGET_PCT / STOP_PCT  # +2.0

    return FixedPctResult(
        entry_price=entry, stop_price=stop, target_price=target,
        exit_bar=exit_bar, exit_type=exit_type,
        realized_R=realized_R, realized_pct_of_capital=realized_R * STOP_PCT * 100,
    )
