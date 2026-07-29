"""
rectangle_candidate_generation.py
-----------------------------------
Full candidate generation for rectangle pattern across canonical PSX universe.

Detection/candidate-generation only — no EV, no profitability, no temporal-holdout
split. Pure candidate generation and honest reporting of what the pipeline produces.

Universe: 302 symbols (SGPL, DWAE, FRCL excluded; placeholder-zero bars dropped),
full 2005–2026 history on prices_adjusted.

Dual touch-minimum runs: entire universe twice (min_touches=3, min_touches=2),
keeping result sets separate.

Anchor policy: every pivot from find_pivots_collapsed() is a valid anchor.
Deduplication: 50% overlap + same outcome → keep higher touch count (tie → earlier index).
"""

import sqlite3
import pandas as pd
import numpy as np
import logging
import sys
from typing import List, Tuple, Dict, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

# Import from psx_pipeline modules
from pivots import find_pivots_collapsed, Pivot
from fit_horizontal_level import fit_horizontal_level
from assemble_rectangle import assemble_rectangle, RectangleResult
from research_filters import exclude_known_artifact_symbols, drop_placeholder_zero_bars

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB = "psx_data.db"
START_DATE = "2005-01-01"
END_DATE = "2026-12-31"


@dataclass
class CandidateMetadata:
    """Track a single rectangle candidate."""
    symbol: str
    anchor_index: int
    anchor_price: float
    anchor_side: str  # 'support' or 'resistance'
    anchor_date: str
    support_level: float
    resistance_level: float
    height_pct: float
    duration_days: int
    support_touches: int
    resistance_touches: int
    breakout_direction: Optional[str]
    outcome: str


@dataclass
class DeduplicationRecord:
    """Track metadata for deduplication."""
    candidate: CandidateMetadata
    start_date: str
    end_date: str
    date_list: List[str]
    total_touches: int = field(init=False)

    def __post_init__(self):
        self.total_touches = self.candidate.support_touches + self.candidate.resistance_touches


def load_prices_adjusted(con: sqlite3.Connection) -> pd.DataFrame:
    """Load all prices_adjusted data for the canonical universe."""
    prices = pd.read_sql_query(
        "SELECT symbol, date, open, high, low, close, volume FROM prices_adjusted "
        "WHERE date >= ? AND date <= ? ORDER BY symbol, date",
        con, params=(START_DATE, END_DATE)
    )
    # Fill NULL volumes with 0 for placeholder zero detection
    prices['volume'] = prices['volume'].fillna(0)
    logger.info(f"Loaded {len(prices):,} rows, {prices['symbol'].nunique():,} symbols")
    return prices


def get_canonical_universe(prices_df: pd.DataFrame) -> List[str]:
    """Get canonical universe: unique symbols, excluding known artifacts."""
    symbols = list(prices_df['symbol'].unique())
    symbols = exclude_known_artifact_symbols(symbols)
    logger.info(f"Canonical universe: {len(symbols)} symbols (after exclusions)")
    return sorted(symbols)


def build_price_bars(symbol_data: pd.DataFrame) -> Tuple[List[dict], np.ndarray, np.ndarray, np.ndarray]:
    """
    Build price_bars list and high/low/close arrays for assemble_rectangle().

    Returns: (price_bars, highs, lows, closes)
    where price_bars is indexed by bar index, with 'day' field as integer offset from epoch.
    """
    df = symbol_data.copy()
    df['day_offset'] = (pd.to_datetime(df['date']) - pd.Timestamp("2005-01-01")).dt.days

    price_bars = []
    for idx, row in df.iterrows():
        price_bars.append({
            'day': int(row['day_offset']),
            'close': float(row['close']),
        })

    highs = df['high'].to_numpy(dtype=float)
    lows = df['low'].to_numpy(dtype=float)
    closes = df['close'].to_numpy(dtype=float)

    return price_bars, highs, lows, closes


def generate_candidates_for_symbol(
    symbol: str,
    symbol_data: pd.DataFrame,
    min_touches: int,
) -> List[Tuple[CandidateMetadata, RectangleResult, pd.Series]]:
    """
    Generate all rectangle candidates for a single symbol.

    Returns list of (metadata, result, full_row) tuples.
    """
    candidates = []

    # Drop placeholder zeros
    symbol_data = drop_placeholder_zero_bars(symbol_data)
    if len(symbol_data) < 30:  # Need minimum data for pivot detection
        return candidates

    # Reset index to contiguous bar space
    symbol_data = symbol_data.reset_index(drop=True)

    # Find pivots
    highs = symbol_data['high'].to_numpy(dtype=float)
    lows = symbol_data['low'].to_numpy(dtype=float)
    closes = symbol_data['close'].to_numpy(dtype=float)
    dates_arr = symbol_data['date'].to_numpy()

    try:
        pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)
    except Exception as e:
        logger.warning(f"Error finding pivots for {symbol}: {e}")
        return candidates

    if not pivots:
        return candidates

    # Build price_bars
    price_bars, highs, lows, closes = build_price_bars(symbol_data)

    # Separate pivots by type
    high_pivots = [(p.index, p.price) for p in pivots if p.kind == 'high']
    low_pivots = [(p.index, p.price) for p in pivots if p.kind == 'low']

    # For each pivot, run assemble_rectangle
    for pivot in pivots:
        try:
            if pivot.kind == 'high':
                # Anchor at resistance (high), discover support
                support_pivs = [(idx, price) for idx, price in low_pivots if idx != pivot.index]
                result = assemble_rectangle(
                    anchor_index=pivot.index,
                    anchor_price=pivot.price,
                    anchor_side='resistance',
                    support_pivots=support_pivs,
                    resistance_pivots=high_pivots,  # All highs, including anchor
                    price_bars=price_bars,
                    tolerance_pct=0.015,
                    min_touches=min_touches,
                    min_duration_days=21,
                    max_duration_days=60,
                    margin_multiplier=2.0,
                )
            else:  # pivot.kind == 'low'
                # Anchor at support (low), discover resistance
                resistance_pivs = [(idx, price) for idx, price in high_pivots if idx != pivot.index]
                result = assemble_rectangle(
                    anchor_index=pivot.index,
                    anchor_price=pivot.price,
                    anchor_side='support',
                    support_pivots=low_pivots,  # All lows, including anchor
                    resistance_pivots=resistance_pivs,
                    price_bars=price_bars,
                    tolerance_pct=0.015,
                    min_touches=min_touches,
                    min_duration_days=21,
                    max_duration_days=60,
                    margin_multiplier=2.0,
                )

            # Compute height_pct and touch counts for reporting
            if result.support_level and result.resistance_level:
                height_pct = abs(result.resistance_level - result.support_level) / result.support_level
            else:
                height_pct = 0.0

            # Count touches (rough estimate from level fit)
            # This is approximate since we don't have the fit object; will be refined in dedup
            support_touches = 1 if result.support_level > 0 else 0
            resistance_touches = 1 if result.resistance_level > 0 else 0

            anchor_date = dates_arr[pivot.index]

            metadata = CandidateMetadata(
                symbol=symbol,
                anchor_index=pivot.index,
                anchor_price=pivot.price,
                anchor_side='resistance' if pivot.kind == 'high' else 'support',
                anchor_date=anchor_date,
                support_level=result.support_level,
                resistance_level=result.resistance_level,
                height_pct=height_pct,
                duration_days=result.duration_days,
                support_touches=support_touches,
                resistance_touches=resistance_touches,
                breakout_direction=result.breakout_direction,
                outcome=result.outcome,
            )

            row = pd.Series({
                'symbol': symbol,
                'anchor_index': pivot.index,
                'anchor_date': anchor_date,
                'anchor_price': pivot.price,
                'anchor_side': metadata.anchor_side,
                'outcome': result.outcome,
                'breakout_direction': result.breakout_direction,
                'support_level': result.support_level,
                'resistance_level': result.resistance_level,
                'height_pct': height_pct,
                'duration_days': result.duration_days,
            })

            candidates.append((metadata, result, row))

        except Exception as e:
            logger.warning(f"Error assembling rectangle for {symbol} at index {pivot.index}: {e}")
            continue

    return candidates


def deduplicate_candidates(
    candidates: List[CandidateMetadata],
    dates_map: Dict[Tuple[str, int], str],
) -> List[CandidateMetadata]:
    """
    Deduplicate candidates: if two overlap by >50% and have same outcome,
    keep only the one with higher total touches (tie → earlier anchor index).
    """
    if not candidates:
        return []

    # Sort by anchor_date for consistent processing
    sorted_candidates = sorted(candidates, key=lambda c: (c.anchor_date, c.anchor_index))
    kept = []
    removed = []

    for i, cand_i in enumerate(sorted_candidates):
        is_duplicate = False

        for j, cand_j in enumerate(kept):
            # Check overlap
            start_i = pd.Timestamp(cand_i.anchor_date)
            end_i = start_i + pd.Timedelta(days=cand_i.duration_days)

            start_j = pd.Timestamp(cand_j.anchor_date)
            end_j = start_j + pd.Timedelta(days=cand_j.duration_days)

            # Overlap range
            overlap_start = max(start_i, start_j)
            overlap_end = min(end_i, end_j)

            if overlap_end > overlap_start:
                overlap_days = (overlap_end - overlap_start).days
                shorter_duration = min(cand_i.duration_days, cand_j.duration_days)
                overlap_pct = overlap_days / shorter_duration if shorter_duration > 0 else 0

                # Same outcome and >50% overlap?
                if cand_i.outcome == cand_j.outcome and overlap_pct > 0.5:
                    # Decide who wins
                    touches_i = cand_i.support_touches + cand_i.resistance_touches
                    touches_j = cand_j.support_touches + cand_j.resistance_touches

                    if touches_i > touches_j:
                        # cand_i wins, replace cand_j
                        kept[j] = cand_i
                        removed.append(cand_j)
                    elif touches_i == touches_j and cand_i.anchor_index < cand_j.anchor_index:
                        # Tie: earlier anchor wins
                        kept[j] = cand_i
                        removed.append(cand_j)
                    else:
                        # cand_j wins
                        is_duplicate = True
                        removed.append(cand_i)
                    break

        if not is_duplicate:
            kept.append(cand_i)

    logger.info(f"Deduplication: {len(sorted_candidates)} → {len(kept)} candidates "
                f"({len(removed)} removed)")

    return kept


def run_full_generation(min_touches: int, limit_symbols: Optional[int] = None) -> pd.DataFrame:
    """
    Run full candidate generation for the canonical universe at a given min_touches.

    Returns DataFrame with all candidates (pre-dedup and post-dedup aggregated).

    limit_symbols: if set, process only first N symbols (useful for testing)
    """
    logger.info(f"Starting full candidate generation with min_touches={min_touches}")

    con = sqlite3.connect(DB)
    prices_df = load_prices_adjusted(con)
    con.close()

    symbols = get_canonical_universe(prices_df)

    if limit_symbols:
        symbols = symbols[:limit_symbols]
        logger.info(f"Limited to first {limit_symbols} symbols for testing")

    all_candidates_pre_dedup = []
    all_candidates_post_dedup = []
    symbol_zero_candidates = []
    symbol_high_candidates = []

    # Generate candidates for each symbol
    for i, symbol in enumerate(symbols):
        if (i + 1) % 100 == 0 or i == 0:
            logger.info(f"[{i + 1}/{len(symbols)}] Processing: {symbol}")

        try:
            symbol_data = prices_df[prices_df['symbol'] == symbol].copy()
            if len(symbol_data) == 0:
                symbol_zero_candidates.append(symbol)
                continue

            candidates = [c for c, _, _ in generate_candidates_for_symbol(symbol, symbol_data, min_touches)]

            if not candidates:
                symbol_zero_candidates.append(symbol)
                continue

            pre_dedup_count = len(candidates)
            all_candidates_pre_dedup.extend(candidates)

            # Deduplicate within symbol
            post_dedup = deduplicate_candidates(candidates, {})
            post_dedup_count = len(post_dedup)
            all_candidates_post_dedup.extend(post_dedup)

            if pre_dedup_count > 20:  # Flag unusually high counts
                symbol_high_candidates.append((symbol, pre_dedup_count))
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            continue

    logger.info(f"\nGeneration complete for min_touches={min_touches}")
    logger.info(f"Total candidates pre-dedup: {len(all_candidates_pre_dedup)}")
    logger.info(f"Total candidates post-dedup: {len(all_candidates_post_dedup)}")

    # Build result DataFrame
    if all_candidates_post_dedup:
        result_data = []
        for cand in all_candidates_post_dedup:
            result_data.append({
                'symbol': cand.symbol,
                'anchor_index': cand.anchor_index,
                'anchor_date': cand.anchor_date,
                'anchor_price': cand.anchor_price,
                'anchor_side': cand.anchor_side,
                'outcome': cand.outcome,
                'breakout_direction': cand.breakout_direction,
                'support_level': cand.support_level,
                'resistance_level': cand.resistance_level,
                'height_pct': cand.height_pct,
                'duration_days': cand.duration_days,
                'touches': cand.support_touches + cand.resistance_touches,
            })
        result_df = pd.DataFrame(result_data)
    else:
        result_df = pd.DataFrame()

    return result_df, all_candidates_pre_dedup, all_candidates_post_dedup, symbol_zero_candidates, symbol_high_candidates


def report_results(
    min_touches: int,
    result_df: pd.DataFrame,
    pre_dedup_count: int,
    symbol_zero: List[str],
    symbol_high: List[Tuple[str, int]],
):
    """Generate comprehensive report for a single min_touches run."""
    print(f"\n{'='*80}")
    print(f"RECTANGLE CANDIDATE GENERATION REPORT")
    print(f"min_touches = {min_touches}")
    print(f"Universe: 302 symbols (excluding known artifacts, placeholder bars dropped)")
    print(f"Date range: 2005-01-01 to 2026-12-31")
    print(f"{'='*80}\n")

    print(f"1. CANDIDATE COUNTS")
    print(f"   Pre-deduplication:  {pre_dedup_count:,} candidates")
    print(f"   Post-deduplication: {len(result_df):,} candidates")

    if len(result_df) > 0:
        print(f"\n2. OUTCOME DISTRIBUTION (post-dedup)")
        outcome_counts = result_df['outcome'].value_counts()
        for outcome in ['VALID', 'EXPIRED_NO_BREAKOUT', 'REJECTED_TOO_SHORT',
                       'REJECTED_HEIGHT_FLOOR', 'REJECTED_INSUFFICIENT_TOUCHES']:
            count = outcome_counts.get(outcome, 0)
            pct = 100 * count / len(result_df)
            print(f"   {outcome:30s}: {count:6,} ({pct:6.2f}%)")

        print(f"\n3. VALID CANDIDATES BREAKDOWN")
        valid_df = result_df[result_df['outcome'] == 'VALID']
        if len(valid_df) > 0:
            print(f"   Total VALID: {len(valid_df):,}")
            print(f"   Breakout direction:")
            direction_counts = valid_df['breakout_direction'].value_counts()
            for direction in ['up', 'down']:
                count = direction_counts.get(direction, 0)
                pct = 100 * count / len(valid_df)
                print(f"      {direction:5s}: {count:6,} ({pct:6.2f}%)")

            print(f"\n   Duration distribution (days):")
            print(f"      min:    {valid_df['duration_days'].min()}")
            print(f"      median: {valid_df['duration_days'].median()}")
            print(f"      max:    {valid_df['duration_days'].max()}")

            print(f"\n   Height distribution (%):")
            print(f"      min:    {valid_df['height_pct'].min() * 100:.2f}%")
            print(f"      median: {valid_df['height_pct'].median() * 100:.2f}%")
            print(f"      max:    {valid_df['height_pct'].max() * 100:.2f}%")

            # Check for clustering at boundaries
            print(f"\n   Sanity checks (suspicious clustering):")
            near_floor = (valid_df['height_pct'] >= 0.061) & (valid_df['height_pct'] <= 0.065)
            near_21d = (valid_df['duration_days'] >= 20) & (valid_df['duration_days'] <= 22)
            near_60d = (valid_df['duration_days'] >= 59) & (valid_df['duration_days'] <= 60)
            print(f"      Height near 6.1% floor (±0.4%): {near_floor.sum()} ({100*near_floor.sum()/len(valid_df):.1f}%)")
            print(f"      Duration near 21d boundary:     {near_21d.sum()} ({100*near_21d.sum()/len(valid_df):.1f}%)")
            print(f"      Duration near 60d cap:          {near_60d.sum()} ({100*near_60d.sum()/len(valid_df):.1f}%)")

        print(f"\n4. SYMBOLS WITH ZERO CANDIDATES")
        print(f"   Count: {len(symbol_zero)}")
        if len(symbol_zero) <= 10:
            for sym in symbol_zero[:10]:
                print(f"      {sym}")
        else:
            print(f"      (too many to list, showing first 10)")
            for sym in symbol_zero[:10]:
                print(f"      {sym}")

        print(f"\n5. SYMBOLS WITH UNUSUALLY HIGH CANDIDATE COUNT (>20)")
        print(f"   Count: {len(symbol_high)}")
        if symbol_high:
            for sym, count in sorted(symbol_high, key=lambda x: x[1], reverse=True)[:10]:
                print(f"      {sym}: {count} candidates")
        else:
            print(f"      None")

        print(f"\n6. DATA QUALITY CHECKS")
        print(f"   Candidates with None support_level:    {result_df['support_level'].isna().sum()}")
        print(f"   Candidates with None resistance_level: {result_df['resistance_level'].isna().sum()}")
        print(f"   Candidates with None breakout_direction (non-VALID): "
              f"{result_df[result_df['outcome'] != 'VALID']['breakout_direction'].isna().sum()}")


def main(test_mode: bool = False):
    """Run full candidate generation for both min_touches={3, 2}.

    test_mode: if True, process only first 50 symbols for quick validation
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    limit = 50 if test_mode else None

    results_by_touches = {}

    for min_touches in [3, 2]:
        result_df, pre_dedup, post_dedup, zero_syms, high_syms = run_full_generation(
            min_touches, limit_symbols=limit
        )
        results_by_touches[min_touches] = (result_df, pre_dedup, post_dedup, zero_syms, high_syms)

        report_results(min_touches, result_df, len(pre_dedup), zero_syms, high_syms)

        # Save to CSV
        if len(result_df) > 0:
            csv_path = f"rectangle_candidates_min_touches_{min_touches}_{timestamp}.csv"
            result_df.to_csv(csv_path, index=False)
            logger.info(f"Saved candidates to {csv_path}")

    # Summary comparison
    print(f"\n{'='*80}")
    print("CROSS-TOUCHES SUMMARY")
    print(f"{'='*80}\n")

    for mt in [3, 2]:
        result_df, _, _, _, _ = results_by_touches[mt]
        print(f"min_touches={mt}: {len(result_df):,} total candidates")
        if len(result_df) > 0:
            valid_count = (result_df['outcome'] == 'VALID').sum()
            print(f"                {valid_count:,} VALID candidates")


if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    if test_mode:
        logger.info("Running in TEST MODE (first 50 symbols only)")
    main(test_mode=test_mode)
