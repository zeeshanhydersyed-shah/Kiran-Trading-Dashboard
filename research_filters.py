"""
research_filters.py
--------------------
Research-pipeline-only data-quality filters for classical pattern work on
prices_adjusted (pivots.py / boundaries.py / the triangle-research study).

These are workarounds applied AT THE RESEARCH-PIPELINE BOUNDARY for known
issues in the underlying production data. They exist so pattern-detection
research isn't corrupted by artifacts that are tracked separately and are
intentionally NOT fixed here. Nothing in this file touches stock_signals.py,
the live dashboard, or writes to psx_data.db in any way -- read-only,
in-memory filtering of a DataFrame already pulled by the caller.
"""

from typing import Iterable, List

import pandas as pd


# Symbol-level exclusion, applied UPFRONT (before any per-symbol pivot/
# boundary/triangle work starts) -- not a per-window or per-price filter.
#
# KNOWN ISSUE, TRACKED SEPARATELY, NOT FIXED HERE: SGPL, DWAE, and FRCL all
# carry the same prices_adjusted corporate-action adjustment-factor artifact
# -- a broken adjustment collapses their close (and open/high/low) to a
# near-zero pinned value (min positive close = 0.0001 for all three) held
# for a long consecutive run (600, 456, and 163 bars respectively), despite
# real trading volume throughout. First found and rejected during ticker
# selection for the original 5-ticker triangle study (2026-07-15, Section 4
# of Triangle_Pattern_Specification_v1.md) -- distinguished there from
# genuine low-priced stocks (e.g. DNCC, MWMP, OML) by the PINNED, repeated
# value under a broken adjustment factor, versus continuously-varying real
# price action. Re-confirmed still present with the same signature in the
# full 305-symbol active-universe run (Section 8 of the same document).
#
# This is a standing exclusion for ANY classical-pattern study (triangles,
# rectangles, and whatever follows) that reuses this 305-symbol active
# universe -- not specific to the triangle pipeline. Deliberately NOT fixed
# at the source (that is a separate, out-of-scope production data-quality
# task) and deliberately NOT handled as a per-price/per-window filter the
# way drop_placeholder_zero_bars() handles a different artifact -- these
# three symbols' entire usable history is compromised by this, so the
# correct fix is symbol-level exclusion, not row-level filtering.
KNOWN_ARTIFACT_SYMBOLS = frozenset({"SGPL", "DWAE", "FRCL"})


def exclude_known_artifact_symbols(symbols: Iterable[str]) -> List[str]:
    """
    Drops any symbol in KNOWN_ARTIFACT_SYMBOLS from an iterable of ticker
    symbols. Apply this to the symbol list BEFORE looping into per-symbol
    price history / pivot detection -- these symbols should never enter
    the pipeline at all for classical-pattern research, not be filtered
    row-by-row once inside it.
    """
    return [s for s in symbols if s not in KNOWN_ARTIFACT_SYMBOLS]


def drop_placeholder_zero_bars(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drops rows where open == high == low == 0.00 AND volume == 0.

    KNOWN ISSUE, TRACKED SEPARATELY, NOT FIXED HERE: confirmed
    placeholder-zero artifact in prices_adjusted -- 1,596 rows across 205
    symbols as of the 2026-07-15 pivot-validation session (repro: ISIL,
    2022-01-11 -> open=high=low=0.00, close=421.00, volume=0). These are
    not real trading days. Left in, a low of 0.00 is trivially the minimum
    of any comparison window, so find_pivots_collapsed() genuinely detects
    a fake pivot low at price=0, which then feeds a garbage fit into
    fit_boundary() (see ISIL bars 1400-1480 in the first pass of this
    study). Root cause (why the scraper/loader writes literal 0.00 instead
    of leaving these fields null on no-trade days) and whether
    stock_signals.py's live pivot lookup is also affected are OUT OF SCOPE
    here -- that's a separate production data-quality task.

    Index is reset after dropping so bar-index space stays contiguous:
    a dropped placeholder bar should not exist as a gap in the pivot
    search, it should simply not exist.
    """
    mask_placeholder = (
        (df["open"] == 0.0)
        & (df["high"] == 0.0)
        & (df["low"] == 0.0)
        & (df["volume"] == 0)
    )
    return df.loc[~mask_placeholder].reset_index(drop=True)
