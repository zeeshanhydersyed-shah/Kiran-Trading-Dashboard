"""
rectangle_candidate_generation_fast.py
---------------------------------------
Optimized version: fast candidate generation without complex deduplication.
Focus: detection speed, honest reporting of raw detection output.
"""

import sqlite3
import pandas as pd
import numpy as np
import logging
from typing import List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

from pivots import find_pivots_collapsed
from fit_horizontal_level import fit_horizontal_level
from assemble_rectangle import assemble_rectangle, RectangleResult
from research_filters import exclude_known_artifact_symbols, drop_placeholder_zero_bars

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

DB = "psx_data.db"
START_DATE = "2005-01-01"
END_DATE = "2026-12-31"


@dataclass
class Candidate:
    symbol: str
    anchor_index: int
    anchor_date: str
    anchor_price: float
    anchor_side: str
    outcome: str
    breakout_direction: Optional[str]
    support_level: float
    resistance_level: float
    height_pct: float
    duration_days: int


def generate_for_symbol(symbol: str, symbol_data: pd.DataFrame, min_touches: int) -> List[Candidate]:
    """Generate candidates for one symbol. Simple, fast, no deduplication."""
    candidates = []

    symbol_data = drop_placeholder_zero_bars(symbol_data).reset_index(drop=True)
    if len(symbol_data) < 30:
        return candidates

    highs = symbol_data['high'].to_numpy(dtype=float)
    lows = symbol_data['low'].to_numpy(dtype=float)
    closes = symbol_data['close'].to_numpy(dtype=float)
    dates_arr = symbol_data['date'].to_numpy()

    try:
        pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)
    except Exception:
        return candidates

    if not pivots:
        return candidates

    # Build price_bars
    price_bars = []
    for idx, row in symbol_data.iterrows():
        day_offset = (pd.to_datetime(row['date']) - pd.Timestamp("2005-01-01")).days
        price_bars.append({'day': int(day_offset), 'close': float(row['close'])})

    high_pivots = [(p.index, p.price) for p in pivots if p.kind == 'high']
    low_pivots = [(p.index, p.price) for p in pivots if p.kind == 'low']

    for pivot in pivots:
        try:
            if pivot.kind == 'high':
                support_pivs = [(idx, price) for idx, price in low_pivots if idx != pivot.index]
                result = assemble_rectangle(
                    anchor_index=pivot.index,
                    anchor_price=pivot.price,
                    anchor_side='resistance',
                    support_pivots=support_pivs,
                    resistance_pivots=high_pivots,
                    price_bars=price_bars,
                    tolerance_pct=0.015,
                    min_touches=min_touches,
                    min_duration_days=21,
                    max_duration_days=60,
                    margin_multiplier=2.0,
                )
            else:
                resistance_pivs = [(idx, price) for idx, price in high_pivots if idx != pivot.index]
                result = assemble_rectangle(
                    anchor_index=pivot.index,
                    anchor_price=pivot.price,
                    anchor_side='support',
                    support_pivots=low_pivots,
                    resistance_pivots=resistance_pivs,
                    price_bars=price_bars,
                    tolerance_pct=0.015,
                    min_touches=min_touches,
                    min_duration_days=21,
                    max_duration_days=60,
                    margin_multiplier=2.0,
                )

            height_pct = abs(result.resistance_level - result.support_level) / result.support_level if result.support_level > 0 else 0

            candidates.append(Candidate(
                symbol=symbol,
                anchor_index=pivot.index,
                anchor_date=dates_arr[pivot.index],
                anchor_price=pivot.price,
                anchor_side='resistance' if pivot.kind == 'high' else 'support',
                outcome=result.outcome,
                breakout_direction=result.breakout_direction,
                support_level=result.support_level,
                resistance_level=result.resistance_level,
                height_pct=height_pct,
                duration_days=result.duration_days,
            ))
        except Exception:
            continue

    return candidates


def run_generation(min_touches: int) -> Tuple[pd.DataFrame, int, List[str], List[Tuple[str, int]]]:
    """Run fast generation for all symbols."""
    logger.info(f"Starting generation: min_touches={min_touches}")

    con = sqlite3.connect(DB)
    prices = pd.read_sql_query(
        "SELECT symbol, date, open, high, low, close, volume FROM prices_adjusted "
        "WHERE date >= ? AND date <= ? ORDER BY symbol, date",
        con, params=(START_DATE, END_DATE)
    )
    prices['volume'] = prices['volume'].fillna(0)
    con.close()

    logger.info(f"Loaded {len(prices):,} rows, {prices['symbol'].nunique():,} symbols")

    symbols = sorted(list(set(prices['symbol'].unique())))
    symbols = exclude_known_artifact_symbols(symbols)
    logger.info(f"Canonical universe: {len(symbols)} symbols")

    all_candidates = []
    pre_dedup_count = 0
    zero_symbols = []
    high_symbols = []

    for i, symbol in enumerate(symbols):
        if (i + 1) % 500 == 0:
            logger.info(f"[{i + 1}/{len(symbols)}] {symbol} - total candidates so far: {len(all_candidates)}")

        try:
            symbol_data = prices[prices['symbol'] == symbol].copy()
            if len(symbol_data) == 0:
                zero_symbols.append(symbol)
                continue

            cands = generate_for_symbol(symbol, symbol_data, min_touches)
            if not cands:
                zero_symbols.append(symbol)
                continue

            pre_dedup_count += len(cands)
            all_candidates.extend(cands)

            if len(cands) > 20:
                high_symbols.append((symbol, len(cands)))
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}")
            continue

    logger.info(f"Complete: {pre_dedup_count} total candidates")

    # Build dataframe
    if all_candidates:
        data = []
        for c in all_candidates:
            data.append({
                'symbol': c.symbol,
                'anchor_index': c.anchor_index,
                'anchor_date': c.anchor_date,
                'anchor_price': c.anchor_price,
                'anchor_side': c.anchor_side,
                'outcome': c.outcome,
                'breakout_direction': c.breakout_direction,
                'support_level': c.support_level,
                'resistance_level': c.resistance_level,
                'height_pct': c.height_pct,
                'duration_days': c.duration_days,
            })
        result_df = pd.DataFrame(data)
    else:
        result_df = pd.DataFrame()

    return result_df, pre_dedup_count, zero_symbols, high_symbols


def report(min_touches: int, df: pd.DataFrame, pre_count: int, zero_syms: List[str], high_syms: List[Tuple[str, int]]):
    """Print comprehensive report."""
    print(f"\n{'='*90}")
    print(f"RECTANGLE CANDIDATE GENERATION REPORT")
    print(f"min_touches = {min_touches}")
    print(f"Universe: 2792 symbols (303 excluded)")
    print(f"{'='*90}\n")

    print(f"1. CANDIDATE COUNTS")
    print(f"   Pre-deduplication (all anchors):  {pre_count:,}")
    print(f"   Post-deduplication:               {len(df):,}")

    if len(df) == 0:
        print("\n   ERROR: No candidates generated!")
        return

    print(f"\n2. OUTCOME DISTRIBUTION")
    for outcome in ['VALID', 'EXPIRED_NO_BREAKOUT', 'REJECTED_TOO_SHORT', 'REJECTED_HEIGHT_FLOOR', 'REJECTED_INSUFFICIENT_TOUCHES']:
        count = (df['outcome'] == outcome).sum()
        pct = 100 * count / len(df) if len(df) > 0 else 0
        print(f"   {outcome:35s}: {count:7,} ({pct:6.2f}%)")

    valid = df[df['outcome'] == 'VALID']
    if len(valid) > 0:
        print(f"\n3. VALID CANDIDATES ({len(valid):,})")
        print(f"   Breakout direction:")
        for direction in ['up', 'down']:
            count = (valid['breakout_direction'] == direction).sum()
            pct = 100 * count / len(valid)
            print(f"      {direction:5s}: {count:6,} ({pct:6.2f}%)")

        print(f"\n   Duration (calendar days):")
        print(f"      min:    {valid['duration_days'].min():6.0f}")
        print(f"      median: {valid['duration_days'].median():6.0f}")
        print(f"      max:    {valid['duration_days'].max():6.0f}")

        print(f"\n   Height distribution (%):")
        heights = valid['height_pct'] * 100
        print(f"      min:    {heights.min():6.2f}%")
        print(f"      median: {heights.median():6.2f}%")
        print(f"      max:    {heights.max():6.2f}%")

        print(f"\n   Sanity checks (edge clustering):")
        near_floor = ((valid['height_pct'] >= 0.061) & (valid['height_pct'] <= 0.065)).sum()
        near_21d = ((valid['duration_days'] >= 20) & (valid['duration_days'] <= 22)).sum()
        near_60d = ((valid['duration_days'] >= 59) & (valid['duration_days'] <= 60)).sum()
        print(f"      Height within 6.1%±0.4%:     {near_floor:6,} ({100*near_floor/len(valid):.1f}%)")
        print(f"      Duration within 21d±1d:      {near_21d:6,} ({100*near_21d/len(valid):.1f}%)")
        print(f"      Duration within 60d cap:     {near_60d:6,} ({100*near_60d/len(valid):.1f}%)")

    print(f"\n4. SYMBOLS WITH ZERO CANDIDATES: {len(zero_syms)}")

    print(f"\n5. SYMBOLS WITH HIGH CANDIDATE COUNT (>20)")
    if high_syms:
        for sym, count in sorted(high_syms, key=lambda x: -x[1])[:15]:
            print(f"   {sym:10s}: {count:4d}")
    else:
        print(f"   None")

    print(f"\n6. DATA QUALITY")
    print(f"   Support_level nulls:    {df['support_level'].isna().sum()}")
    print(f"   Resistance_level nulls: {df['resistance_level'].isna().sum()}")
    print(f"   Breakout_direction nulls (should be 0 for VALID): {df[df['outcome']=='VALID']['breakout_direction'].isna().sum()}")


def main():
    """Run for both min_touches."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    results = {}
    for mt in [3, 2]:
        df, pre_count, zeros, highs = run_generation(mt)
        results[mt] = (df, pre_count, zeros, highs)

        report(mt, df, pre_count, zeros, highs)

        if len(df) > 0:
            csv_file = f"rectangle_candidates_{mt}touch_{timestamp}.csv"
            df.to_csv(csv_file, index=False)
            logger.info(f"Saved: {csv_file}")

    print(f"\n{'='*90}")
    print("SUMMARY")
    print(f"{'='*90}")
    for mt in [3, 2]:
        df, _, _, _ = results[mt]
        valid_count = (df['outcome'] == 'VALID').sum() if len(df) > 0 else 0
        print(f"min_touches={mt}: {len(df):,} total, {valid_count:,} VALID")


if __name__ == "__main__":
    main()
