"""
100-symbol representative sample: fast completion with extrapolation.
Runs on symbols 0, 28, 56, 84, ... (every 28th symbol = ~100 symbols)
to get statistically representative coverage across the alphabet.
"""

import sqlite3
import pandas as pd
import time
from datetime import datetime
from pivots import find_pivots_collapsed
from assemble_rectangle import assemble_rectangle
from research_filters import exclude_known_artifact_symbols, drop_placeholder_zero_bars

DB = "psx_data.db"

print(f"Rectangle Generation - 100-Symbol Sample")
print(f"Started: {datetime.now().strftime('%H:%M:%S')}\n")

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
print(f"Sampling every {len(symbols)//100}th symbol = ~100 symbols\n")

# Sample: every Nth symbol
step = max(1, len(symbols) // 100)
sample_symbols = symbols[::step][:100]
print(f"Sample size: {len(sample_symbols)} symbols\n")

results_by_touches = {}

for min_touches in [3, 2]:
    print(f"\nmin_touches={min_touches}")
    print("=" * 60)

    candidates = []
    start = time.time()

    for i, symbol in enumerate(sample_symbols):
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

        if (i + 1) % 20 == 0:
            elapsed = time.time() - start
            print(f"  [{i+1:3d}/{len(sample_symbols)}] {symbol:10s} | {len(candidates):6d} candidates | {elapsed:.0f}s")

    elapsed = time.time() - start
    print(f"  Complete: {len(candidates):,} candidates in {elapsed:.0f}s\n")

    if candidates:
        df = pd.DataFrame(candidates)
        results_by_touches[min_touches] = df

        # Save
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        csv_file = f"rectangle_sample_100sym_{min_touches}touch_{timestamp}.csv"
        df.to_csv(csv_file, index=False)
        print(f"  Saved: {csv_file}\n")

        # Report
        print(f"  Outcome distribution:")
        for outcome in ['VALID', 'EXPIRED_NO_BREAKOUT', 'REJECTED_TOO_SHORT', 'REJECTED_HEIGHT_FLOOR', 'REJECTED_INSUFFICIENT_TOUCHES']:
            count = (df['outcome'] == outcome).sum()
            pct = 100 * count / len(df)
            print(f"    {outcome:35s}: {count:5,d} ({pct:6.2f}%)")

        valid = df[df['outcome'] == 'VALID']
        if len(valid) > 0:
            up = (valid['breakout_direction'] == 'up').sum()
            down = (valid['breakout_direction'] == 'down').sum()
            print(f"\n  VALID: {len(valid):,} ({up} up, {down} down)")
            print(f"    Duration: {valid['duration_days'].min():.0f}–{valid['duration_days'].median():.0f}–{valid['duration_days'].max():.0f} days")
            print(f"    Height:   {valid['height_pct'].min()*100:.2f}%–{valid['height_pct'].median()*100:.2f}%–{valid['height_pct'].max()*100:.2f}%")

# Summary
print(f"\n{'='*60}")
print("SAMPLE SUMMARY (100 symbols, scaled to full universe)")
print(f"{'='*60}\n")

for mt in [3, 2]:
    if mt in results_by_touches:
        df = results_by_touches[mt]
        total = len(df)
        valid = (df['outcome'] == 'VALID').sum()

        # Rough extrapolation: sample is ~100/2792, so multiply by 28
        scale_factor = len(symbols) / len(sample_symbols)
        scaled_total = int(total * scale_factor)
        scaled_valid = int(valid * scale_factor)

        print(f"min_touches={mt}:")
        print(f"  Sample:      {total:,} candidates ({valid:,} VALID)")
        print(f"  Extrapolated: {scaled_total:,} candidates ({scaled_valid:,} VALID)")

print(f"\nNote: Extrapolation assumes sample is representative.")
print(f"Full universe run would take 1-3 hours due to computational scale.")
