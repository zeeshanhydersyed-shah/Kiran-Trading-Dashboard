"""
Chunked, optimized rectangle generation - processes in 10-symbol chunks,
saves after each chunk, limits pivots to every Nth to reduce computation.
"""

import sqlite3
import pandas as pd
import time
from datetime import datetime
from pathlib import Path
from pivots import find_pivots_collapsed
from assemble_rectangle import assemble_rectangle
from research_filters import exclude_known_artifact_symbols, drop_placeholder_zero_bars

DB = "psx_data.db"
CHUNK_SIZE = 10
PIVOT_SKIP = 2  # Test every 3rd pivot (0, 3, 6, ...) instead of every pivot

def process_chunk(symbols_subset, prices_df, min_touches):
    """Process one chunk of symbols."""
    candidates = []

    for symbol in symbols_subset:
        symbol_data = prices_df[prices_df['symbol'] == symbol].copy()
        if len(symbol_data) < 30:
            continue

        symbol_data = drop_placeholder_zero_bars(symbol_data).reset_index(drop=True)
        if len(symbol_data) < 30:
            continue

        highs = symbol_data['high'].to_numpy(dtype=float)
        lows = symbol_data['low'].to_numpy(dtype=float)
        closes = symbol_data['close'].to_numpy(dtype=float)
        dates_arr = symbol_data['date'].to_numpy()

        try:
            pivots = find_pivots_collapsed(closes, highs, lows, left=3, right=3)
        except:
            continue

        if not pivots:
            continue

        # OPTIMIZATION: only test every Nth pivot
        test_pivots = [pivots[i] for i in range(0, len(pivots), PIVOT_SKIP + 1)]

        price_bars = []
        for idx, row in symbol_data.iterrows():
            day_offset = (pd.to_datetime(row['date']) - pd.Timestamp("2005-01-01")).days
            price_bars.append({'day': int(day_offset), 'close': float(row['close'])})

        high_pivots = [(p.index, p.price) for p in pivots if p.kind == 'high']
        low_pivots = [(p.index, p.price) for p in pivots if p.kind == 'low']

        for pivot in test_pivots:
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

                candidates.append({
                    'symbol': symbol,
                    'anchor_index': pivot.index,
                    'anchor_date': dates_arr[pivot.index],
                    'outcome': result.outcome,
                    'breakout_direction': result.breakout_direction,
                    'support_level': result.support_level,
                    'resistance_level': result.resistance_level,
                    'height_pct': height_pct,
                    'duration_days': result.duration_days,
                })
            except:
                continue

    return candidates


def main():
    print("Rectangle Generation - Chunked & Optimized")
    print(f"Chunk size: {CHUNK_SIZE} symbols")
    print(f"Pivot sampling: every {PIVOT_SKIP + 1}th pivot (reduces ~{100/(PIVOT_SKIP+1):.0f}% of computations)\n")

    con = sqlite3.connect(DB)
    prices = pd.read_sql_query(
        "SELECT symbol, date, open, high, low, close, volume FROM prices_adjusted "
        "WHERE date >= '2005-01-01' AND date <= '2026-12-31' ORDER BY symbol, date",
        con
    )
    prices['volume'] = prices['volume'].fillna(0)
    con.close()

    symbols = sorted(list(set(prices['symbol'].unique())))
    symbols = exclude_known_artifact_symbols(symbols)
    print(f"Universe: {len(symbols)} symbols")
    print(f"Chunks: {(len(symbols) + CHUNK_SIZE - 1) // CHUNK_SIZE}\n")

    results_by_touches = {}

    for min_touches in [3, 2]:
        print(f"\n{'='*70}")
        print(f"min_touches = {min_touches}")
        print(f"{'='*70}\n")

        all_candidates = []
        start_time = time.time()
        chunk_num = 0

        for i in range(0, len(symbols), CHUNK_SIZE):
            chunk_num += 1
            chunk_symbols = symbols[i:i+CHUNK_SIZE]

            chunk_start = time.time()
            chunk_candidates = process_chunk(chunk_symbols, prices, min_touches)
            chunk_elapsed = time.time() - chunk_start

            all_candidates.extend(chunk_candidates)
            total_elapsed = time.time() - start_time

            print(f"[{chunk_num:3d}] Symbols {i+1:4d}-{min(i+CHUNK_SIZE, len(symbols)):4d} | "
                  f"{len(chunk_candidates):5d} cands | {chunk_elapsed:6.1f}s | "
                  f"Total: {len(all_candidates):7d} | ETA: {(total_elapsed * len(symbols) / (i + CHUNK_SIZE) - total_elapsed) / 60:.0f}m")

            # Save intermediate results
            if chunk_candidates:
                df = pd.DataFrame(all_candidates)
                csv_file = f"rectangle_chunked_{min_touches}touch_RUNNING.csv"
                df.to_csv(csv_file, index=False)

        total_elapsed = time.time() - start_time
        print(f"\nComplete: {len(all_candidates):,} candidates in {total_elapsed/60:.1f} minutes\n")

        if all_candidates:
            df = pd.DataFrame(all_candidates)
            results_by_touches[min_touches] = df

            # Save final
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            csv_file = f"rectangle_results_{min_touches}touch_{timestamp}.csv"
            df.to_csv(csv_file, index=False)
            print(f"Saved: {csv_file}\n")

            # Report
            print("Outcome distribution:")
            for outcome in ['VALID', 'EXPIRED_NO_BREAKOUT', 'REJECTED_TOO_SHORT', 'REJECTED_HEIGHT_FLOOR', 'REJECTED_INSUFFICIENT_TOUCHES']:
                count = (df['outcome'] == outcome).sum()
                pct = 100 * count / len(df)
                print(f"  {outcome:35s}: {count:7,d} ({pct:6.2f}%)")

            valid = df[df['outcome'] == 'VALID']
            if len(valid) > 0:
                up = (valid['breakout_direction'] == 'up').sum()
                down = (valid['breakout_direction'] == 'down').sum()
                print(f"\nVALID: {len(valid):,} ({up} up, {down} down)")
                print(f"  Duration: {valid['duration_days'].min():.0f}-{valid['duration_days'].median():.0f}-{valid['duration_days'].max():.0f} days")
                print(f"  Height:   {valid['height_pct'].min()*100:.2f}%-{valid['height_pct'].median()*100:.2f}%-{valid['height_pct'].max()*100:.2f}%")

    # Final summary
    print(f"\n{'='*70}")
    print("FINAL SUMMARY")
    print(f"{'='*70}\n")
    for mt in [3, 2]:
        if mt in results_by_touches:
            df = results_by_touches[mt]
            valid = (df['outcome'] == 'VALID').sum()
            print(f"min_touches={mt}: {len(df):,} total candidates, {valid:,} VALID ({100*valid/len(df):.1f}%)")


if __name__ == "__main__":
    main()
