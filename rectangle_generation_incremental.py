"""
Incremental rectangle generation with progress tracking and periodic saves.
Saves results as they're generated so we get partial output even if interrupted.
"""

import sqlite3
import pandas as pd
import time
from datetime import datetime
from pivots import find_pivots_collapsed
from assemble_rectangle import assemble_rectangle
from research_filters import exclude_known_artifact_symbols, drop_placeholder_zero_bars

DB = "psx_data.db"
START_DATE = "2005-01-01"
END_DATE = "2026-12-31"

def run_incremental(min_touches: int):
    """Run generation with incremental saves."""
    print(f"\n{'='*80}")
    print(f"Starting: min_touches={min_touches}")
    print(f"{'='*80}\n")

    con = sqlite3.connect(DB)
    prices = pd.read_sql_query(
        "SELECT symbol, date, open, high, low, close, volume FROM prices_adjusted "
        "WHERE date >= ? AND date <= ? ORDER BY symbol, date",
        con, params=(START_DATE, END_DATE)
    )
    prices['volume'] = prices['volume'].fillna(0)
    con.close()

    symbols = sorted(list(set(prices['symbol'].unique())))
    symbols = exclude_known_artifact_symbols(symbols)
    print(f"Processing {len(symbols)} symbols\n")

    all_results = []
    total_candidates = 0
    start_time = time.time()
    save_interval = 100  # Save every N symbols

    for i, symbol in enumerate(symbols):
        symbol_data = prices[prices['symbol'] == symbol].copy()
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

        # Build price_bars
        price_bars = []
        for idx, row in symbol_data.iterrows():
            day_offset = (pd.to_datetime(row['date']) - pd.Timestamp("2005-01-01")).days
            price_bars.append({'day': int(day_offset), 'close': float(row['close'])})

        high_pivots = [(p.index, p.price) for p in pivots if p.kind == 'high']
        low_pivots = [(p.index, p.price) for p in pivots if p.kind == 'low']

        symbol_candidates = 0
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

                all_results.append({
                    'symbol': symbol,
                    'anchor_index': pivot.index,
                    'anchor_date': dates_arr[pivot.index],
                    'anchor_price': pivot.price,
                    'anchor_side': 'resistance' if pivot.kind == 'high' else 'support',
                    'outcome': result.outcome,
                    'breakout_direction': result.breakout_direction,
                    'support_level': result.support_level,
                    'resistance_level': result.resistance_level,
                    'height_pct': height_pct,
                    'duration_days': result.duration_days,
                })
                symbol_candidates += 1
                total_candidates += 1
            except:
                continue

        # Progress update every save_interval
        if (i + 1) % save_interval == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            remaining = (len(symbols) - i - 1) / rate if rate > 0 else 0
            print(f"[{i+1:4d}/{len(symbols)}] {symbol:10s} +{symbol_candidates:3d} cands | "
                  f"Total: {total_candidates:7d} | "
                  f"Rate: {rate:.1f} sym/s | ETA: {remaining/60:.0f} min")

            # Save intermediate results
            if len(all_results) > 0:
                df = pd.DataFrame(all_results)
                csv_file = f"rectangle_gen_{min_touches}touch_PARTIAL.csv"
                df.to_csv(csv_file, index=False)

    # Final save and report
    elapsed = time.time() - start_time
    print(f"\nComplete in {elapsed/60:.1f} minutes")
    print(f"Total candidates: {total_candidates}")

    if len(all_results) > 0:
        df = pd.DataFrame(all_results)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        csv_file = f"rectangle_candidates_{min_touches}touch_{timestamp}.csv"
        df.to_csv(csv_file, index=False)
        print(f"Saved: {csv_file}")

        # Quick report
        print(f"\nOutcome distribution:")
        for outcome in ['VALID', 'EXPIRED_NO_BREAKOUT', 'REJECTED_TOO_SHORT', 'REJECTED_HEIGHT_FLOOR', 'REJECTED_INSUFFICIENT_TOUCHES']:
            count = (df['outcome'] == outcome).sum()
            pct = 100 * count / len(df)
            print(f"  {outcome:35s}: {count:7,d} ({pct:6.2f}%)")

        valid = df[df['outcome'] == 'VALID']
        if len(valid) > 0:
            print(f"\nVALID: {len(valid)} candidates")
            for direction in ['up', 'down']:
                count = (valid['breakout_direction'] == direction).sum()
                print(f"  {direction}: {count}")
    else:
        print("No candidates generated!")

    return len(all_results) if all_results else 0

# Run both min_touches levels
print("Rectangle Candidate Generation - Incremental")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

for min_touches in [3, 2]:
    count = run_incremental(min_touches)
    print(f"min_touches={min_touches}: {count} candidates\n")

print("Done!")
